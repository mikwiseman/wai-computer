import Foundation
import Sentry

private struct AnyEncodable: Encodable {
    private let encodeImpl: (Encoder) throws -> Void

    init(_ value: any Encodable) {
        self.encodeImpl = value.encode(to:)
    }

    func encode(to encoder: Encoder) throws {
        try encodeImpl(encoder)
    }
}

/// API errors
public enum APIError: Error, LocalizedError, Sendable {
    case invalidURL
    case noData
    case decodingError(Error)
    case httpError(statusCode: Int, message: String?)
    case networkError(Error)
    case unauthorized

    public var errorDescription: String? {
        switch self {
        case .invalidURL:
            return "Invalid URL."
        case .noData:
            return "No data received from server."
        case .decodingError(let error):
            return "Failed to parse server response: \(error.localizedDescription)"
        case .httpError(let statusCode, let message):
            if let message, !message.isEmpty {
                return message
            }
            return "Server error (\(statusCode))"
        case .networkError(let error):
            return "Network error: \(error.localizedDescription)"
        case .unauthorized:
            return "Session expired. Please log in again."
        }
    }

    public var uploadFailureCode: String {
        switch self {
        case .httpError(let statusCode, _) where statusCode == 413:
            return "file_too_large"
        default:
            return "upload_failed"
        }
    }
}

/// HTTP methods
public enum HTTPMethod: String, Sendable {
    case GET
    case POST
    case PUT
    case PATCH
    case DELETE
}

/// API Client for WaiComputer backend
public actor APIClient {
    public static let maxRecordingUploadSizeBytes = 1024 * 1024 * 1024

    private let baseURL: URL
    private var accessToken: String? {
        didSet { accessTokenExpiry = accessToken.flatMap(Self.jwtExpiry(of:)) }
    }
    private var refreshToken: String?
    /// Decoded `exp` of the current access token. Lets requests refresh
    /// PROACTIVELY instead of discovering expiry via a 401 round-trip — after
    /// an idle night, that 401→refresh→retry dance added ~500ms to the
    /// dictation hot path (first-token latency threshold events).
    private var accessTokenExpiry: Date?
    /// Refresh this many seconds before the token actually expires.
    private static let proactiveRefreshSkew: TimeInterval = 60
    private let session: URLSession

    private let encoder: JSONEncoder
    private let decoder: JSONDecoder

    /// Called when tokens are refreshed. Parameters: (accessToken, refreshToken).
    /// Use this to persist new tokens to Keychain.
    public var onTokenRefreshed: (@Sendable (String, String) -> Void)?

    /// Called when authentication fails permanently (refresh token expired/invalid).
    /// Use this to transition to the login screen.
    public var onAuthenticationFailed: (@Sendable () -> Void)?

    /// Guards against concurrent refresh attempts — only one refresh at a time.
    private var isRefreshing = false
    private var refreshWaiters: [CheckedContinuation<String, Error>] = []

    public init(
        baseURL: URL,
        accessToken: String? = nil,
        session: URLSession? = nil
    ) {
        self.baseURL = baseURL
        self.accessToken = accessToken
        self.accessTokenExpiry = accessToken.flatMap(Self.jwtExpiry(of:))

        if let session {
            self.session = session
        } else {
            let config = URLSessionConfiguration.default
            config.timeoutIntervalForRequest = 30
            self.session = URLSession(configuration: config)
        }

        self.encoder = JSONEncoder()
        self.encoder.dateEncodingStrategy = .iso8601
        self.decoder = JSONDecoder()

        // Configure date decoding
        self.decoder.dateDecodingStrategy = .custom { decoder in
            let container = try decoder.singleValueContainer()
            let dateString = try container.decode(String.self)

            // Try ISO8601 with fractional seconds and timezone
            let isoFormatter = ISO8601DateFormatter()
            isoFormatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            if let date = isoFormatter.date(from: dateString) {
                return date
            }

            // Try ISO8601 without fractional seconds but with timezone
            isoFormatter.formatOptions = [.withInternetDateTime]
            if let date = isoFormatter.date(from: dateString) {
                return date
            }

            // Try timezone-less with fractional seconds (Python's .isoformat())
            let dfWithFrac = DateFormatter()
            dfWithFrac.dateFormat = "yyyy-MM-dd'T'HH:mm:ss.SSSSSS"
            dfWithFrac.locale = Locale(identifier: "en_US_POSIX")
            dfWithFrac.timeZone = TimeZone(secondsFromGMT: 0)
            if let date = dfWithFrac.date(from: dateString) {
                return date
            }

            // Try timezone-less without fractional seconds
            let dfNoFrac = DateFormatter()
            dfNoFrac.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
            dfNoFrac.locale = Locale(identifier: "en_US_POSIX")
            dfNoFrac.timeZone = TimeZone(secondsFromGMT: 0)
            if let date = dfNoFrac.date(from: dateString) {
                return date
            }

            throw DecodingError.dataCorruptedError(
                in: container,
                debugDescription: "Cannot decode date: \(dateString)"
            )
        }
    }

    /// Set the access token for authenticated requests
    public func setAccessToken(_ token: String?) {
        self.accessToken = token
    }

    /// Set the refresh token for auto-refresh
    public func setRefreshToken(_ token: String?) {
        self.refreshToken = token
    }

    /// Get the current access token
    public func getAccessToken() -> String? {
        return accessToken
    }

    /// Get the current refresh token
    public func getRefreshToken() -> String? {
        return refreshToken
    }

    /// Set the callback for token refresh events
    public func setOnTokenRefreshed(_ callback: @escaping @Sendable (String, String) -> Void) {
        self.onTokenRefreshed = callback
    }

    /// Set the callback for authentication failure (auto-refresh failed)
    public func setOnAuthenticationFailed(_ callback: @escaping @Sendable () -> Void) {
        self.onAuthenticationFailed = callback
    }

    private func apiError(from data: Data, response: HTTPURLResponse) -> APIError {
        APIError.httpError(
            statusCode: response.statusCode,
            message: errorMessage(from: data, statusCode: response.statusCode)
        )
    }

    private func errorMessage(from data: Data, statusCode: Int) -> String? {
        if !data.isEmpty,
           let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let detail = object["detail"] as? String,
           !detail.isEmpty {
            return detail
        }

        if !data.isEmpty,
           let text = String(data: data, encoding: .utf8)?
            .trimmingCharacters(in: .whitespacesAndNewlines),
           !text.isEmpty,
           !text.hasPrefix("<!DOCTYPE"),
           !text.hasPrefix("<html") {
            return text
        }

        if statusCode == 413 {
            return "File too large. Maximum size is \(Self.maxRecordingUploadSizeBytes / (1024 * 1024))MB."
        }

        return HTTPURLResponse.localizedString(forStatusCode: statusCode).capitalized
    }

    // MARK: - Auto-refresh

    /// Decode the `exp` claim of a JWT without verifying the signature — the
    /// client only needs to know when its OWN token expires.
    static func jwtExpiry(of token: String) -> Date? {
        let parts = token.split(separator: ".")
        guard parts.count >= 2 else { return nil }
        var payload = String(parts[1])
            .replacingOccurrences(of: "-", with: "+")
            .replacingOccurrences(of: "_", with: "/")
        while payload.count % 4 != 0 { payload += "=" }
        guard let data = Data(base64Encoded: payload),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let exp = object["exp"] as? TimeInterval else {
            return nil
        }
        return Date(timeIntervalSince1970: exp)
    }

    private func shouldProactivelyRefresh() -> Bool {
        guard refreshToken != nil, let expiry = accessTokenExpiry else { return false }
        return Date() >= expiry.addingTimeInterval(-Self.proactiveRefreshSkew)
    }

    /// Attempt to refresh tokens. Coalesces concurrent calls — only one refresh in flight.
    /// Returns the new access token on success.
    private func autoRefresh() async throws -> String {
        let refreshPath = "/api/auth/refresh"

        // If already refreshing, wait for the result
        if isRefreshing {
            return try await withCheckedThrowingContinuation { continuation in
                refreshWaiters.append(continuation)
            }
        }

        guard let rt = refreshToken else {
            throw APIError.unauthorized
        }

        isRefreshing = true

        do {
            let body = RefreshTokenRequest(refreshToken: rt)
            let bodyData = try encoder.encode(AnyEncodable(body))

            var urlComponents = URLComponents(
                url: baseURL.appendingPathComponent("/api/auth/refresh"),
                resolvingAgainstBaseURL: true
            )
            urlComponents?.queryItems = nil

            guard let url = urlComponents?.url else {
                throw APIError.invalidURL
            }

            var req = URLRequest(url: url)
            req.httpMethod = "POST"
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = bodyData

            let data: Data
            let response: URLResponse
            do {
                (data, response) = try await session.data(for: req)
            } catch {
                let requestError = APIError.networkError(error)
                SentryHelper.captureRequestFailure(
                    requestError,
                    method: "POST",
                    path: refreshPath,
                    extras: ["authFlow": "refresh"]
                )
                throw requestError
            }

            guard let httpResponse = response as? HTTPURLResponse else {
                let requestError = APIError.networkError(URLError(.badServerResponse))
                SentryHelper.captureRequestFailure(
                    requestError,
                    method: "POST",
                    path: refreshPath,
                    extras: ["authFlow": "refresh"]
                )
                throw requestError
            }

            guard (200...299).contains(httpResponse.statusCode) else {
                let requestError = if httpResponse.statusCode == 401 {
                    APIError.unauthorized
                } else {
                    apiError(from: data, response: httpResponse)
                }
                SentryHelper.captureRequestFailure(
                    requestError,
                    method: "POST",
                    path: refreshPath,
                    extras: ["authFlow": "refresh"]
                )
                throw requestError
            }

            let authResponse = try decoder.decode(AuthResponse.self, from: data)
            accessToken = authResponse.accessToken
            if let newRefreshToken = authResponse.refreshToken {
                refreshToken = newRefreshToken
                onTokenRefreshed?(authResponse.accessToken, newRefreshToken)
            }

            // Resume all waiters with new token
            let waiters = refreshWaiters
            refreshWaiters = []
            isRefreshing = false
            for waiter in waiters {
                waiter.resume(returning: authResponse.accessToken)
            }

            return authResponse.accessToken
        } catch {
            // Resume all waiters with failure
            let waiters = refreshWaiters
            refreshWaiters = []
            isRefreshing = false
            for waiter in waiters {
                waiter.resume(throwing: error)
            }
            throw error
        }
    }

    /// Handle a 401 response: try auto-refresh, or signal auth failure.
    /// Returns new access token if refresh succeeded, throws if not.
    private func handleUnauthorized(path: String) async throws -> String {
        // Don't try to refresh auth endpoints themselves
        if path.hasSuffix("/auth/refresh") || path.hasSuffix("/auth/login")
            || path.hasSuffix("/auth/register") || path.hasSuffix("/auth/verify-magic") {
            throw APIError.unauthorized
        }

        guard refreshToken != nil else {
            onAuthenticationFailed?()
            throw APIError.unauthorized
        }

        do {
            return try await autoRefresh()
        } catch {
            onAuthenticationFailed?()
            throw APIError.unauthorized
        }
    }

    // MARK: - Auth-retry core

    /// Perform an HTTP call with automatic 401 refresh-and-retry.
    /// The `perform` closure executes the actual network call (data or upload).
    private func performWithAuthRetry(
        _ request: inout URLRequest,
        path: String,
        method: String,
        extras: [String: Any] = [:],
        perform: (URLRequest) async throws -> (Data, URLResponse)
    ) async throws -> (Data, HTTPURLResponse) {
        // Refresh a (nearly) expired token BEFORE the call instead of paying a
        // guaranteed 401 round-trip. Best-effort: on refresh failure, fall
        // through — the regular 401 handling below stays authoritative.
        if shouldProactivelyRefresh() {
            if let refreshed = try? await autoRefresh() {
                request.setValue("Bearer \(refreshed)", forHTTPHeaderField: "Authorization")
                SentryHelper.addBreadcrumb(
                    category: "auth",
                    message: "token refreshed proactively",
                    data: ["path": path]
                )
            }
        }
        let data: Data
        let response: URLResponse
        Log.api.info("→ \(method) \(path)")
        do {
            (data, response) = try await perform(request)
        } catch {
            var sentryExtras: [String: Any] = ["path": path, "method": method]
            sentryExtras.merge(extras) { _, new in new }
            SentryHelper.captureRequestFailure(
                APIError.networkError(error),
                method: method,
                path: path,
                extras: sentryExtras
            )
            Log.api.error("✗ \(method) \(path) failed")
            throw APIError.networkError(error)
        }

        guard let httpResponse = response as? HTTPURLResponse else {
            Log.api.error("✗ \(method) \(path) invalid response")
            throw APIError.networkError(URLError(.badServerResponse))
        }

        Log.api.info("← \(method) \(path) (\(httpResponse.statusCode))")

        SentryHelper.addBreadcrumb(
            category: "api",
            message: "\(method) \(path)",
            data: ["statusCode": httpResponse.statusCode]
        )

        if httpResponse.statusCode == 401 {
            SentryHelper.addBreadcrumb(category: "auth", message: "token refresh triggered", data: ["path": path])
            let newToken: String
            do {
                newToken = try await handleUnauthorized(path: path)
                SentryHelper.addBreadcrumb(category: "auth", message: "token refreshed")
            } catch {
                SentryHelper.addBreadcrumb(category: "auth", message: "auth failed", level: .error)
                throw error
            }
            request.setValue("Bearer \(newToken)", forHTTPHeaderField: "Authorization")

            let retryData: Data
            let retryResponse: URLResponse
            do {
                (retryData, retryResponse) = try await perform(request)
            } catch {
                var sentryExtras: [String: Any] = ["path": path, "method": method, "retry": true]
                sentryExtras.merge(extras) { _, new in new }
                SentryHelper.captureRequestFailure(
                    APIError.networkError(error),
                    method: method,
                    path: path,
                    extras: sentryExtras
                )
                throw APIError.networkError(error)
            }

            guard let retryHttp = retryResponse as? HTTPURLResponse else {
                throw APIError.networkError(URLError(.badServerResponse))
            }
            if retryHttp.statusCode == 401 {
                SentryHelper.addBreadcrumb(category: "auth", message: "auth failed after refresh", level: .error)
                onAuthenticationFailed?()
                throw APIError.unauthorized
            }
            guard (200...299).contains(retryHttp.statusCode) else {
                let error = apiError(from: retryData, response: retryHttp)
                SentryHelper.captureRequestFailure(
                    error,
                    method: method,
                    path: path,
                    extras: extras
                )
                throw error
            }
            return (retryData, retryHttp)
        }

        guard (200...299).contains(httpResponse.statusCode) else {
            let error = apiError(from: data, response: httpResponse)
            SentryHelper.captureRequestFailure(
                error,
                method: method,
                path: path,
                extras: extras
            )
            throw error
        }

        return (data, httpResponse)
    }

    /// Build a URLRequest for a JSON API call.
    private func buildJSONRequest(
        method: HTTPMethod,
        path: String,
        body: (any Encodable)?,
        queryItems: [URLQueryItem]?,
        timeoutInterval: TimeInterval?
    ) throws -> URLRequest {
        var urlComponents = URLComponents(url: baseURL.appendingPathComponent(path), resolvingAgainstBaseURL: true)
        urlComponents?.queryItems = queryItems

        guard let url = urlComponents?.url else {
            throw APIError.invalidURL
        }

        var request = URLRequest(url: url)
        request.httpMethod = method.rawValue
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let timeoutInterval {
            request.timeoutInterval = timeoutInterval
        }
        if let token = accessToken {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        #if DEBUG
        // Debug-only billing enforcement for testers. Release builds must
        // ignore stale local flags because the Settings toggle is not shipped.
        if Self.debugPaymentModeOverrideEnabled {
            request.setValue("enforce", forHTTPHeaderField: "X-WaiComputer-Payment-Mode")
        }
        #endif
        if let body = body {
            request.httpBody = try encoder.encode(AnyEncodable(body))
        }
        return request
    }

    #if DEBUG
    private static var debugPaymentModeOverrideEnabled: Bool {
        UserDefaults.standard.bool(forKey: "paymentModeEnabled")
    }
    #endif

    // MARK: - Request methods

    /// Make an API request
    public func request<T: Decodable>(
        _ method: HTTPMethod,
        path: String,
        body: (any Encodable)? = nil,
        queryItems: [URLQueryItem]? = nil,
        timeoutInterval: TimeInterval? = nil
    ) async throws -> T {
        var request = try buildJSONRequest(method: method, path: path, body: body, queryItems: queryItems, timeoutInterval: timeoutInterval)

        let (data, _) = try await performWithAuthRetry(&request, path: path, method: method.rawValue) { req in
            try await self.session.data(for: req)
        }

        do {
            return try decoder.decode(T.self, from: data)
        } catch {
            throw APIError.decodingError(error)
        }
    }

    /// Make an API request that returns no content
    public func requestNoContent(
        _ method: HTTPMethod,
        path: String,
        body: (any Encodable)? = nil,
        queryItems: [URLQueryItem]? = nil,
        timeoutInterval: TimeInterval? = nil
    ) async throws {
        var request = try buildJSONRequest(method: method, path: path, body: body, queryItems: queryItems, timeoutInterval: timeoutInterval)

        _ = try await performWithAuthRetry(&request, path: path, method: method.rawValue) { req in
            try await self.session.data(for: req)
        }
    }

    /// Make an authenticated API request that returns raw response bytes.
    public func requestData(
        _ method: HTTPMethod,
        path: String,
        body: (any Encodable)? = nil,
        queryItems: [URLQueryItem]? = nil,
        timeoutInterval: TimeInterval? = nil
    ) async throws -> Data {
        var request = try buildJSONRequest(
            method: method,
            path: path,
            body: body,
            queryItems: queryItems,
            timeoutInterval: timeoutInterval
        )
        let (data, _) = try await performWithAuthRetry(&request, path: path, method: method.rawValue) { req in
            try await self.session.data(for: req)
        }
        return data
    }

    // MARK: - System & Self-hosting

    public func getSystemInfo() async throws -> SystemInfo {
        return try await request(.GET, path: "/api/system/info")
    }

    public func getDataOwnershipMap() async throws -> DataOwnershipMap {
        return try await request(.GET, path: "/api/system/data-map")
    }

    public func getSelfHostMigrationContract() async throws -> SelfHostMigrationContract {
        return try await request(.GET, path: "/api/self-host/migration/contract")
    }

    public func startSelfHostProvision(
        _ request: SelfHostProvisionRequest
    ) async throws -> SelfHostProvisionResponse {
        return try await self.request(.POST, path: "/api/self-host/provision", body: request)
    }

    // MARK: - Agents

    public func getAgentCapabilities() async throws -> AgentCapabilitiesResponse {
        return try await request(.GET, path: "/api/agents/capabilities")
    }

    public func listAgents(limit: Int? = nil) async throws -> AgentListResponse {
        let queryItems = limit.map { [URLQueryItem(name: "limit", value: "\($0)")] }
        return try await request(.GET, path: "/api/agents", queryItems: queryItems)
    }

    public func createAgent(_ request: AgentCreateRequest) async throws -> AgentDefinition {
        return try await self.request(.POST, path: "/api/agents", body: request)
    }

    public func updateAgent(
        agentId: String,
        _ request: AgentUpdateRequest
    ) async throws -> AgentDefinition {
        return try await self.request(.PATCH, path: "/api/agents/\(agentId)", body: request)
    }

    public func deleteAgent(agentId: String) async throws {
        try await requestNoContent(.DELETE, path: "/api/agents/\(agentId)")
    }

    public func startAgentRun(
        agentId: String,
        _ request: StartAgentRunRequest = StartAgentRunRequest()
    ) async throws -> AgentRun {
        return try await self.request(.POST, path: "/api/agents/\(agentId)/runs", body: request)
    }

    public func listAgentRuns(
        agentId: String,
        status: String? = nil,
        limit: Int? = nil
    ) async throws -> AgentRunListResponse {
        var queryItems: [URLQueryItem] = []
        if let status {
            queryItems.append(URLQueryItem(name: "status", value: status))
        }
        if let limit {
            queryItems.append(URLQueryItem(name: "limit", value: "\(limit)"))
        }
        return try await request(
            .GET,
            path: "/api/agents/\(agentId)/runs",
            queryItems: queryItems.isEmpty ? nil : queryItems
        )
    }

    public func listAllAgentRuns(status: String? = nil, limit: Int? = nil) async throws -> AgentRunListResponse {
        var queryItems: [URLQueryItem] = []
        if let status {
            queryItems.append(URLQueryItem(name: "status", value: status))
        }
        if let limit {
            queryItems.append(URLQueryItem(name: "limit", value: "\(limit)"))
        }
        return try await request(
            .GET,
            path: "/api/agents/runs",
            queryItems: queryItems.isEmpty ? nil : queryItems
        )
    }

    public func getAgentRun(agentId: String, runId: String) async throws -> AgentRun {
        return try await request(.GET, path: "/api/agents/\(agentId)/runs/\(runId)")
    }

    public func listAgentRunSteps(agentId: String, runId: String) async throws -> AgentStepListResponse {
        return try await request(.GET, path: "/api/agents/\(agentId)/runs/\(runId)/steps")
    }

    public func cancelAgentRun(
        agentId: String,
        runId: String,
        reason: String? = nil
    ) async throws -> AgentRun {
        struct CancelBody: Codable {
            let reason: String?
        }
        return try await request(
            .POST,
            path: "/api/agents/\(agentId)/runs/\(runId)/cancel",
            body: CancelBody(reason: reason)
        )
    }

    public func listAgentActions(status: String? = "pending", limit: Int? = nil) async throws -> AgentActionListResponse {
        var queryItems: [URLQueryItem] = []
        if let status {
            queryItems.append(URLQueryItem(name: "status", value: status))
        }
        if let limit {
            queryItems.append(URLQueryItem(name: "limit", value: "\(limit)"))
        }
        return try await request(
            .GET,
            path: "/api/agents/actions",
            queryItems: queryItems.isEmpty ? nil : queryItems
        )
    }

    public func listAgentRunActions(agentId: String, runId: String) async throws -> AgentActionListResponse {
        return try await request(.GET, path: "/api/agents/\(agentId)/runs/\(runId)/actions")
    }

    public func resolveAgentAction(
        agentId: String,
        runId: String,
        actionId: String,
        _ request: ResolveAgentActionRequest
    ) async throws -> ResolveAgentActionResponse {
        return try await self.request(
            .POST,
            path: "/api/agents/\(agentId)/runs/\(runId)/actions/\(actionId)/resolve",
            body: request
        )
    }

    // MARK: - Reminders

    public func listReminders(status: String? = "pending", limit: Int? = nil) async throws -> ReminderListResponse {
        var queryItems: [URLQueryItem] = []
        if let status {
            queryItems.append(URLQueryItem(name: "status", value: status))
        }
        if let limit {
            queryItems.append(URLQueryItem(name: "limit", value: "\(limit)"))
        }
        return try await request(
            .GET,
            path: "/api/reminders",
            queryItems: queryItems.isEmpty ? nil : queryItems
        )
    }

    public func createReminder(_ request: ReminderCreateRequest) async throws -> Reminder {
        return try await self.request(.POST, path: "/api/reminders", body: request)
    }

    public func cancelReminder(reminderId: String) async throws -> Reminder {
        return try await request(.POST, path: "/api/reminders/\(reminderId)/cancel")
    }

    // MARK: - Devices / Mac-edge channel

    /// Advertise this device's presence (and register it on first call).
    public func deviceHeartbeat(
        platform: String,
        name: String? = nil,
        deviceId: String? = nil
    ) async throws -> DeviceHeartbeatResponse {
        let body = DeviceHeartbeatRequest(platform: platform, name: name, deviceId: deviceId)
        return try await request(.POST, path: "/api/devices/heartbeat", body: body)
    }

    /// Drain approved desktop actions queued for this device.
    public func drainDesktopActions(deviceId: String) async throws -> DesktopActionQueue {
        return try await request(.GET, path: "/api/devices/\(deviceId)/desktop-actions")
    }

    /// Approve (once/always) or reject a pending companion action proposed
    /// during a chat turn. The approval ledger + side effect live server-side.
    public func resolveCompanionAction(
        chatId: String,
        actionId: String,
        _ request: CompanionResolveActionRequest
    ) async throws -> CompanionResolveActionResponse {
        return try await self.request(
            .POST,
            path: "/api/companion/chats/\(chatId)/actions/\(actionId)/resolve",
            body: request
        )
    }

    /// Report the outcome of a dispatched desktop action back to the cloud.
    public func reportDesktopResult(
        chatId: String,
        actionId: String,
        deviceId: String,
        status: DesktopResultStatus,
        payload: [String: CompanionJSONValue]? = nil
    ) async throws -> DesktopResultResponse {
        let body = DesktopResultRequest(deviceId: deviceId, status: status, payload: payload)
        return try await request(
            .POST,
            path: "/api/companion/chats/\(chatId)/actions/\(actionId)/desktop_result",
            body: body
        )
    }

    /// Approve (once/always) or reject a pending Companion chat action. The side
    /// effect runs exactly once on the server for an approval; rejection cascades
    /// to siblings. `timeout == deny` is enforced server-side.
    public func resolveCompanionAction(
        chatId: String,
        actionId: String,
        decision: CompanionActionDecision
    ) async throws -> ResolveCompanionActionResponse {
        let body = ResolveCompanionActionRequest(decision: decision.wireValue)
        return try await request(
            .POST,
            path: "/api/companion/chats/\(chatId)/actions/\(actionId)/resolve",
            body: body
        )
    }

    /// Report the outcome of an agent-originated desktop action back to the cloud.
    public func reportAgentDesktopResult(
        agentId: String,
        runId: String,
        actionId: String,
        deviceId: String,
        status: DesktopResultStatus,
        payload: [String: CompanionJSONValue]? = nil
    ) async throws -> DesktopResultResponse {
        let body = DesktopResultRequest(deviceId: deviceId, status: status, payload: payload)
        return try await request(
            .POST,
            path: "/api/agents/\(agentId)/runs/\(runId)/actions/\(actionId)/desktop_result",
            body: body
        )
    }

    // MARK: - Auth Endpoints

    public func register(
        email: String,
        password: String,
        region: String? = nil,
        locale: String? = nil,
        acceptedLegalTerms: Bool
    ) async throws -> AuthResponse {
        let request = RegisterRequest(
            email: email,
            password: password,
            region: region,
            locale: locale,
            acceptedLegalTerms: acceptedLegalTerms
        )
        return try await self.request(.POST, path: "/api/auth/register", body: request)
    }

    public func login(email: String, password: String, locale: String? = nil) async throws -> AuthResponse {
        let request = LoginRequest(email: email, password: password, locale: locale)
        return try await self.request(.POST, path: "/api/auth/login", body: request)
    }

    public func requestMagicLink(
        email: String,
        client: String? = nil,
        region: String? = nil,
        locale: String? = nil,
        acceptedLegalTerms: Bool? = nil,
        legalTermsVersion: String? = nil,
        legalPrivacyVersion: String? = nil
    ) async throws -> MessageResponse {
        let request = MagicLinkRequest(
            email: email,
            client: client,
            region: region,
            locale: locale,
            acceptedLegalTerms: acceptedLegalTerms,
            legalTermsVersion: legalTermsVersion,
            legalPrivacyVersion: legalPrivacyVersion
        )
        return try await self.request(.POST, path: "/api/auth/magic-link", body: request)
    }

    public func requestPasswordReset(email: String, locale: String? = nil) async throws -> MessageResponse {
        let request = PasswordResetRequest(email: email, locale: locale)
        return try await self.request(.POST, path: "/api/auth/forgot-password", body: request)
    }

    public func verifyMagicLink(token: String) async throws -> AuthResponse {
        let request = VerifyMagicLinkRequest(token: token)
        return try await self.request(.POST, path: "/api/auth/verify-magic", body: request)
    }

    public func getCurrentUser() async throws -> User {
        return try await request(.GET, path: "/api/auth/me")
    }

    public func changePassword(currentPassword: String, newPassword: String) async throws -> MessageResponse {
        let body = ChangePasswordRequest(currentPassword: currentPassword, newPassword: newPassword)
        return try await request(.POST, path: "/api/settings/change-password", body: body)
    }

    public func logout(refreshToken: String? = nil) async throws -> MessageResponse {
        let body = LogoutRequest(refreshToken: refreshToken)
        return try await request(.POST, path: "/api/auth/logout", body: body)
    }

    /// Permanently delete the signed-in account and all of its server-side data.
    ///
    /// Backend: `DELETE /api/auth/me` → cascades through recordings, folders,
    /// entities, tags, and refresh tokens. After a successful call the caller
    /// must clear local tokens and route back to the auth screen — the
    /// returned message is advisory only.
    public func deleteAccount() async throws -> MessageResponse {
        return try await request(.DELETE, path: "/api/auth/me")
    }

    // MARK: - Settings Endpoints

    public func getSettings() async throws -> UserSettings {
        return try await request(.GET, path: "/api/settings")
    }

    public func getTranscriptionOptions() async throws -> TranscriptionOptions {
        return try await request(.GET, path: "/api/settings/transcription-options")
    }

    public func updateSettings(_ settings: UpdateSettingsRequest) async throws -> UserSettings {
        return try await request(.PATCH, path: "/api/settings", body: settings)
    }

    // MARK: - Identity & Voice Sharing

    public func getIdentity() async throws -> UserIdentity {
        return try await request(.GET, path: "/api/settings/identity")
    }

    public func updateIdentity(_ patch: UpdateIdentityRequest) async throws -> UserIdentity {
        return try await request(.PATCH, path: "/api/settings/identity", body: patch)
    }

    public func getVoiceSharing() async throws -> VoiceSharingState {
        return try await request(.GET, path: "/api/settings/voice-sharing")
    }

    public func enableVoiceSharing() async throws -> VoiceSharingState {
        struct EmptyBody: Encodable {}
        return try await request(.POST, path: "/api/settings/voice-sharing", body: EmptyBody())
    }

    public func disableVoiceSharing() async throws -> VoiceSharingState {
        return try await request(.DELETE, path: "/api/settings/voice-sharing")
    }

    // MARK: - Telegram

    public func getTelegramLinkStatus() async throws -> TelegramLinkStatus {
        return try await request(.GET, path: "/api/telegram/link")
    }

    public func startTelegramLink() async throws -> TelegramPairing {
        struct EmptyBody: Encodable {}
        return try await request(.POST, path: "/api/telegram/link/start", body: EmptyBody())
    }

    public func claimTelegramLinkCode(_ code: String) async throws -> TelegramLinkStatus {
        return try await request(
            .POST,
            path: "/api/telegram/link/claim",
            body: TelegramLinkCodeClaimRequest(code: code)
        )
    }

    public func unlinkTelegram() async throws {
        try await requestNoContent(.DELETE, path: "/api/telegram/link")
    }

    // MARK: - Recording Endpoints

    public func listRecordings(
        skip: Int = 0,
        limit: Int = 50,
        type: RecordingType? = nil,
        folderId: String? = nil,
        trashed: Bool = false
    ) async throws -> [Recording] {
        var queryItems = [
            URLQueryItem(name: "skip", value: "\(skip)"),
            URLQueryItem(name: "limit", value: "\(limit)"),
            URLQueryItem(name: "trashed", value: trashed ? "true" : "false")
        ]
        if let type = type {
            queryItems.append(URLQueryItem(name: "type", value: type.rawValue))
        }
        if let folderId {
            queryItems.append(URLQueryItem(name: "folder_id", value: folderId))
        }
        return try await request(.GET, path: "/api/recordings", queryItems: queryItems)
    }

    public func createRecording(
        title: String? = nil,
        type: RecordingType = .note,
        language: String = "en",
        folderId: String? = nil
    ) async throws -> Recording {
        let request = CreateRecordingRequest(title: title, type: type, language: language, folderId: folderId)
        return try await self.request(.POST, path: "/api/recordings", body: request)
    }

    public func getRecording(id: String) async throws -> RecordingDetail {
        return try await request(.GET, path: "/api/recordings/\(id)")
    }

    public func updateRecording(id: String, title: String? = nil, type: RecordingType? = nil) async throws -> Recording {
        let body = UpdateRecordingRequestBody(title: title, type: type?.rawValue)
        return try await request(.PATCH, path: "/api/recordings/\(id)", body: body)
    }

    public func moveRecording(id: String, folderId: String?) async throws -> Recording {
        let body = UpdateRecordingRequestBody(folderId: folderId, includeFolderId: true)
        return try await request(.PATCH, path: "/api/recordings/\(id)", body: body)
    }

    public func deleteRecording(id: String, permanent: Bool = false) async throws {
        let queryItems = permanent ? [URLQueryItem(name: "permanent", value: "true")] : nil
        try await requestNoContent(.DELETE, path: "/api/recordings/\(id)", queryItems: queryItems)
    }

    public func restoreRecording(id: String) async throws -> Recording {
        return try await request(.POST, path: "/api/recordings/\(id)/restore")
    }

    public func bulkRecordingOperation(
        recordingIds: [String],
        action: BulkRecordingAction,
        folderId: String? = nil
    ) async throws -> BulkRecordingOperationResponse {
        let body = BulkRecordingOperationRequest(
            recordingIds: recordingIds,
            action: action,
            folderId: folderId
        )
        return try await request(.POST, path: "/api/recordings/bulk", body: body)
    }

    public func createRecordingShareLink(id: String) async throws -> RecordingShareLink {
        return try await request(.POST, path: "/api/recordings/\(id)/share")
    }

    public func getTranscript(recordingId: String) async throws -> [Segment] {
        return try await request(.GET, path: "/api/recordings/\(recordingId)/transcript")
    }

    // MARK: - People (known speakers)

    public func listPeople() async throws -> [Person] {
        return try await request(.GET, path: "/api/people")
    }

    public func createPerson(displayName: String, color: String? = nil) async throws -> Person {
        let body = CreatePersonRequestBody(displayName: displayName, color: color)
        return try await request(.POST, path: "/api/people", body: body)
    }

    public func updatePerson(
        id: String,
        displayName: String? = nil,
        color: String? = nil
    ) async throws -> Person {
        let body = UpdatePersonRequestBody(displayName: displayName, color: color)
        return try await request(.PATCH, path: "/api/people/\(id)", body: body)
    }

    public func deletePerson(id: String) async throws {
        try await requestNoContent(.DELETE, path: "/api/people/\(id)")
    }

    public func mergePeople(sourceId: String, intoPersonId: String) async throws -> Person {
        let body = MergePersonRequestBody(intoPersonId: intoPersonId)
        return try await request(.POST, path: "/api/people/\(sourceId)/merge", body: body)
    }

    /// Map every segment in the recording matching ``rawLabel`` to the given person,
    /// or create a new Person if ``newDisplayName`` is provided. Exactly one must be set.
    public func assignSpeaker(
        recordingId: String,
        rawLabel: String,
        personId: String? = nil,
        newDisplayName: String? = nil
    ) async throws -> RecordingDetail {
        let body = AssignSpeakerRequestBody(
            rawLabel: rawLabel,
            personId: personId,
            newDisplayName: newDisplayName
        )
        return try await request(
            .POST,
            path: "/api/recordings/\(recordingId)/assign-speaker",
            body: body
        )
    }

    public func rematchSpeakers(recordingId: String) async throws -> RematchSpeakersResponse {
        try await request(.POST, path: "/api/recordings/\(recordingId)/rematch")
    }

    /// Submit an in-memory audio sample for first-time (or recurring) voice enrollment.
    ///
    /// Backend expects a multipart upload with `audio` (file), optional `display_name`,
    /// and optional `person_id`. Sample must be 5-60 seconds.
    public func enrollVoice(
        audio: Data,
        filename: String = "enrollment.wav",
        mimeType: String = "audio/wav",
        displayName: String? = nil,
        personId: String? = nil
    ) async throws -> VoiceEnrollmentResponse {
        let path = "/api/voice-enrollment"
        let url = baseURL.appendingPathComponent(path)

        let boundary = "Boundary-\(UUID().uuidString)"
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 120

        if let token = accessToken {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        let multipartFileURL = try createVoiceEnrollmentRequestFile(
            audio: audio,
            filename: filename,
            mimeType: mimeType,
            displayName: displayName,
            personId: personId,
            boundary: boundary
        )
        defer { try? FileManager.default.removeItem(at: multipartFileURL) }

        let (data, _) = try await performWithAuthRetry(
            &request,
            path: path,
            method: "POST"
        ) { req in
            try await self.session.upload(for: req, fromFile: multipartFileURL)
        }

        do {
            return try decoder.decode(VoiceEnrollmentResponse.self, from: data)
        } catch {
            throw APIError.decodingError(error)
        }
    }

    private func createVoiceEnrollmentRequestFile(
        audio: Data,
        filename: String,
        mimeType: String,
        displayName: String?,
        personId: String?,
        boundary: String
    ) throws -> URL {
        let uploadURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("wai-enroll-\(UUID().uuidString).multipart")
        FileManager.default.createFile(atPath: uploadURL.path, contents: nil)
        let output = try FileHandle(forWritingTo: uploadURL)
        defer { try? output.close() }

        func writeString(_ string: String) throws {
            try output.write(contentsOf: Data(string.utf8))
        }

        try writeString("--\(boundary)\r\n")
        try writeString("Content-Disposition: form-data; name=\"audio\"; filename=\"\(filename)\"\r\n")
        try writeString("Content-Type: \(mimeType)\r\n\r\n")
        try output.write(contentsOf: audio)
        try writeString("\r\n")

        if let displayName, !displayName.isEmpty {
            try writeString("--\(boundary)\r\n")
            try writeString("Content-Disposition: form-data; name=\"display_name\"\r\n\r\n")
            try writeString(displayName)
            try writeString("\r\n")
        }
        if let personId, !personId.isEmpty {
            try writeString("--\(boundary)\r\n")
            try writeString("Content-Disposition: form-data; name=\"person_id\"\r\n\r\n")
            try writeString(personId)
            try writeString("\r\n")
        }

        try writeString("--\(boundary)--\r\n")
        return uploadURL
    }

    public func getSummary(recordingId: String) async throws -> Summary {
        return try await request(.GET, path: "/api/recordings/\(recordingId)/summary")
    }

    public func generateSummary(recordingId: String) async throws -> Summary {
        return try await request(.POST, path: "/api/recordings/\(recordingId)/generate-summary")
    }

    public func getSummaryGeneration(recordingId: String) async throws -> SummaryGenerationState {
        return try await request(.GET, path: "/api/recordings/\(recordingId)/summary-generation")
    }

    public func startSummaryGeneration(recordingId: String) async throws -> SummaryGenerationState {
        return try await request(.POST, path: "/api/recordings/\(recordingId)/summary-generation")
    }

    public func getRecordingSummaryAudio(recordingId: String) async throws -> SummaryAudioState {
        return try await request(.GET, path: "/api/recordings/\(recordingId)/summary/audio")
    }

    public func startRecordingSummaryAudio(recordingId: String) async throws -> SummaryAudioState {
        return try await request(.POST, path: "/api/recordings/\(recordingId)/summary/audio")
    }

    public func downloadRecordingSummaryAudio(recordingId: String) async throws -> Data {
        return try await requestData(.GET, path: "/api/recordings/\(recordingId)/summary/audio/file")
    }

    /// Export recording transcript in the given format (markdown, txt, srt).
    /// Pass `locale` ("en"/"ru") so export headers follow the app UI language
    /// rather than the recording's detected audio language (126).
    public func exportRecording(
        id: String,
        format: String,
        locale: String? = nil,
        style: String? = nil
    ) async throws -> String {
        let path = "/api/recordings/\(id)/export"
        let url = baseURL.appendingPathComponent("/api/recordings/\(id)/export")
        var components = URLComponents(url: url, resolvingAgainstBaseURL: false)!
        var queryItems = [URLQueryItem(name: "format", value: format)]
        if let locale {
            queryItems.append(URLQueryItem(name: "locale", value: locale))
        }
        if let style {
            queryItems.append(URLQueryItem(name: "style", value: style))
        }
        components.queryItems = queryItems
        var req = URLRequest(url: components.url!)
        req.httpMethod = "GET"
        if let token = accessToken {
            req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        let data: Data
        let response: URLResponse
        do {
            (data, response) = try await session.data(for: req)
        } catch {
            let requestError = APIError.networkError(error)
            SentryHelper.captureRequestFailure(
                requestError,
                method: "GET",
                path: path,
                extras: ["format": format]
            )
            throw requestError
        }
        guard let httpResponse = response as? HTTPURLResponse else {
            let requestError = APIError.networkError(URLError(.badServerResponse))
            SentryHelper.captureRequestFailure(
                requestError,
                method: "GET",
                path: path,
                extras: ["format": format]
            )
            throw requestError
        }
        guard httpResponse.statusCode == 200 else {
            let requestError = APIError.httpError(
                statusCode: httpResponse.statusCode,
                message: "Export failed"
            )
            SentryHelper.captureRequestFailure(
                requestError,
                method: "GET",
                path: path,
                extras: ["format": format]
            )
            throw requestError
        }
        guard let text = String(data: data, encoding: .utf8) else {
            let requestError = APIError.decodingError(DecodingError.dataCorrupted(
                .init(codingPath: [], debugDescription: "Invalid UTF-8 data")
            ))
            SentryHelper.captureRequestFailure(
                requestError,
                method: "GET",
                path: path,
                extras: ["format": format]
            )
            throw requestError
        }
        return text
    }

    public func starRecording(id: String) async throws -> Recording {
        return try await request(.POST, path: "/api/recordings/\(id)/star")
    }

    public func unstarRecording(id: String) async throws -> Recording {
        return try await request(.DELETE, path: "/api/recordings/\(id)/star")
    }

    public func listStarredRecordings() async throws -> [Recording] {
        let queryItems = [URLQueryItem(name: "starred", value: "true")]
        return try await request(.GET, path: "/api/recordings", queryItems: queryItems)
    }

    // MARK: - Search Endpoints

    public func search(query: String, limit: Int = 20, offset: Int = 0) async throws -> SearchResponse {
        let queryItems = [
            URLQueryItem(name: "q", value: query),
            URLQueryItem(name: "limit", value: "\(limit)"),
            URLQueryItem(name: "offset", value: "\(offset)")
        ]
        return try await request(.GET, path: "/api/search", queryItems: queryItems)
    }

    public func semanticSearch(query: String, limit: Int = 20, threshold: Double = 0.3) async throws -> SearchResponse {
        let queryItems = [
            URLQueryItem(name: "q", value: query),
            URLQueryItem(name: "limit", value: "\(limit)"),
            URLQueryItem(name: "threshold", value: "\(threshold)")
        ]
        return try await request(.GET, path: "/api/search/semantic", queryItems: queryItems)
    }

    public func fulltextSearch(query: String, limit: Int = 20, offset: Int = 0) async throws -> SearchResponse {
        let queryItems = [
            URLQueryItem(name: "q", value: query),
            URLQueryItem(name: "limit", value: "\(limit)"),
            URLQueryItem(name: "offset", value: "\(offset)")
        ]
        return try await request(.GET, path: "/api/search/fts", queryItems: queryItems)
    }

    /// Unified RRF search across recordings AND items (the "search everything" box).
    public func unifiedSearch(query: String, limit: Int = 20) async throws -> UnifiedSearchResponse {
        let queryItems = [
            URLQueryItem(name: "q", value: query),
            URLQueryItem(name: "limit", value: "\(limit)")
        ]
        return try await request(.GET, path: "/api/search/all", queryItems: queryItems)
    }

    // MARK: - Universal Inbox

    public func listInbox(
        sourceKind: InboxSourceKind? = nil,
        status: InboxStatusFilter? = nil,
        folderId: String? = nil,
        limit: Int = 50,
        cursor: String? = nil
    ) async throws -> InboxResponse {
        var queryItems: [URLQueryItem] = [
            URLQueryItem(name: "limit", value: "\(limit)")
        ]
        if let sourceKind {
            queryItems.append(URLQueryItem(name: "source_kind", value: sourceKind.rawValue))
        }
        if let status {
            queryItems.append(URLQueryItem(name: "status", value: status.rawValue))
        }
        if let folderId {
            queryItems.append(URLQueryItem(name: "folder_id", value: folderId))
        }
        if let cursor {
            queryItems.append(URLQueryItem(name: "cursor", value: cursor))
        }
        return try await request(.GET, path: "/api/inbox", queryItems: queryItems)
    }

    // MARK: - Items (universal "add anything") Endpoints

    public func createItem(
        source: String = "paste",
        kind: String = "note",
        title: String? = nil,
        body: String? = nil,
        url: String? = nil,
        folderId: String? = nil
    ) async throws -> Item {
        let payload = CreateItemRequest(
            source: source, kind: kind, title: title, body: body, url: url, folderId: folderId
        )
        return try await request(.POST, path: "/api/items", body: payload)
    }

    public func listItems(
        source: String? = nil,
        kind: String? = nil,
        folderId: String? = nil,
        limit: Int = 50,
        offset: Int = 0
    ) async throws -> ItemListResponse {
        var queryItems: [URLQueryItem] = [
            URLQueryItem(name: "limit", value: "\(limit)"),
            URLQueryItem(name: "offset", value: "\(offset)")
        ]
        if let source = source { queryItems.append(URLQueryItem(name: "source", value: source)) }
        if let kind = kind { queryItems.append(URLQueryItem(name: "kind", value: kind)) }
        if let folderId = folderId {
            queryItems.append(URLQueryItem(name: "folder_id", value: folderId))
        }
        return try await request(.GET, path: "/api/items", queryItems: queryItems)
    }

    public func getItem(id: String) async throws -> Item {
        return try await request(.GET, path: "/api/items/\(id)")
    }

    /// Upload a document (PDF / text / markdown) from disk as an item. Streams
    /// the multipart body from a temp file (`session.upload(fromFile:)`) rather
    /// than holding it all in memory in the request.
    private struct MediaProcessingMarker: Decodable {
        let status: String
        let recordingId: String

        private enum CodingKeys: String, CodingKey {
            case status
            case recordingId = "recording_id"
        }
    }

    public func uploadItem(
        fileURL: URL,
        folderId: String? = nil,
        title: String? = nil
    ) async throws -> ItemUploadOutcome {
        // Videos upload as their audio track when AVFoundation can extract it
        // locally (mp4/mov/m4v) — a fraction of the bytes. Containers it can't
        // read (mkv/webm/…) upload whole; the server's ffmpeg pipeline extracts.
        // The original (video) filename is kept so the recording title derives
        // from it, not from the temp file.
        var payloadURL = fileURL
        var uploadFilename = fileURL.lastPathComponent
        var extractedTempURL: URL?
        if MediaImportSupport.isVideoExtension(fileURL.pathExtension) {
            if let extracted = await MediaAudioExtractor.extractAudioForUpload(source: fileURL) {
                payloadURL = extracted
                extractedTempURL = extracted
                uploadFilename =
                    fileURL.deletingPathExtension().lastPathComponent + ".m4a"
            }
        }
        defer {
            if let extractedTempURL {
                try? FileManager.default.removeItem(at: extractedTempURL)
            }
        }

        // Same client cap as recordings; media shares the server's
        // UPLOAD_MAX_BYTES and would 413 there anyway.
        let itemFileSize = try fileSize(at: payloadURL)
        if itemFileSize > Int64(Self.maxRecordingUploadSizeBytes) {
            throw APIError.httpError(
                statusCode: 413,
                message: "File too large. Maximum size is \(Self.maxRecordingUploadSizeBytes / (1024 * 1024))MB."
            )
        }

        let path = "/api/items/upload"
        let url = baseURL.appendingPathComponent(path)
        let boundary = "Boundary-\(UUID().uuidString)"
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue(
            "multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type"
        )
        // Matches uploadAudio: large videos upload for minutes, and the interval
        // is an idle timeout — it only fires when bytes stop flowing.
        request.timeoutInterval = 600
        if let token = accessToken {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        let multipartFileURL = try createItemUploadRequestFile(
            fileURL: payloadURL,
            uploadFilename: uploadFilename,
            folderId: folderId,
            title: title,
            boundary: boundary
        )
        defer { try? FileManager.default.removeItem(at: multipartFileURL) }

        let (data, response) = try await performWithAuthRetry(
            &request, path: path, method: "POST"
        ) { req in
            try await self.session.upload(for: req, fromFile: multipartFileURL)
        }

        // Audio/video are accepted as 202 (staged + transcribed in the background);
        // documents come back as a 201 Item.
        if response.statusCode == 202 {
            do {
                let marker = try decoder.decode(MediaProcessingMarker.self, from: data)
                return .recording(status: marker.status, recordingId: marker.recordingId)
            } catch {
                throw APIError.decodingError(error)
            }
        }
        do {
            return .item(try decoder.decode(Item.self, from: data))
        } catch {
            throw APIError.decodingError(error)
        }
    }

    private func itemUploadMimeType(_ ext: String) -> String {
        switch ext.lowercased() {
        case "pdf": return "application/pdf"
        case "md", "markdown": return "text/markdown"
        case "txt", "text": return "text/plain"
        default:
            // Every importable audio/video container shares the media table
            // (mirrors the backend's EXTENSION_TO_CONTENT_TYPE).
            return MediaImportSupport.mimeType(forExtension: ext)
        }
    }

    private func createItemUploadRequestFile(
        fileURL: URL,
        uploadFilename: String? = nil,
        folderId: String?,
        title: String?,
        boundary: String
    ) throws -> URL {
        let filename = uploadFilename ?? fileURL.lastPathComponent
        let mimeType = itemUploadMimeType(fileURL.pathExtension)

        let uploadURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("wai-item-\(UUID().uuidString).multipart")
        FileManager.default.createFile(atPath: uploadURL.path, contents: nil)
        let output = try FileHandle(forWritingTo: uploadURL)
        defer { try? output.close() }

        func writeString(_ string: String) throws {
            try output.write(contentsOf: Data(string.utf8))
        }

        try writeString("--\(boundary)\r\n")
        try writeString(
            "Content-Disposition: form-data; name=\"file\"; filename=\"\(filename)\"\r\n"
        )
        try writeString("Content-Type: \(mimeType)\r\n\r\n")

        // Chunked file→file copy, like uploadAudio: a large video must never
        // sit in the app's memory as one Data blob.
        let input = try FileHandle(forReadingFrom: fileURL)
        defer { try? input.close() }
        while true {
            let chunk = try input.read(upToCount: 64 * 1024) ?? Data()
            if chunk.isEmpty {
                break
            }
            try output.write(contentsOf: chunk)
        }
        try writeString("\r\n")

        if let folderId, !folderId.isEmpty {
            try writeString("--\(boundary)\r\n")
            try writeString("Content-Disposition: form-data; name=\"folder_id\"\r\n\r\n")
            try writeString(folderId)
            try writeString("\r\n")
        }
        if let title, !title.isEmpty {
            try writeString("--\(boundary)\r\n")
            try writeString("Content-Disposition: form-data; name=\"title\"\r\n\r\n")
            try writeString(title)
            try writeString("\r\n")
        }

        try writeString("--\(boundary)--\r\n")
        return uploadURL
    }

    /// Move a material into a folder, or out of one with `folderId: nil`.
    public func moveItem(id: String, folderId: String?) async throws -> Item {
        return try await request(
            .PATCH,
            path: "/api/items/\(id)",
            body: FolderAssignmentBody(folderId: folderId)
        )
    }

    public func deleteItem(id: String) async throws {
        try await requestNoContent(.DELETE, path: "/api/items/\(id)")
    }

    public func getItemSummaryAudio(itemId: String) async throws -> SummaryAudioState {
        return try await request(.GET, path: "/api/items/\(itemId)/summary/audio")
    }

    public func startItemSummaryAudio(itemId: String) async throws -> SummaryAudioState {
        return try await request(.POST, path: "/api/items/\(itemId)/summary/audio")
    }

    public func downloadItemSummaryAudio(itemId: String) async throws -> Data {
        return try await requestData(.GET, path: "/api/items/\(itemId)/summary/audio/file")
    }

    // MARK: - Comparison Sets (forward several -> compare)

    public func createComparison(
        itemIds: [String],
        title: String? = nil,
        intent: String? = nil
    ) async throws -> ComparisonSet {
        let payload = CreateComparisonRequest(itemIds: itemIds, title: title, intent: intent)
        return try await request(.POST, path: "/api/comparisons", body: payload)
    }

    public func listComparisons(limit: Int = 50, offset: Int = 0) async throws -> [ComparisonListEntry] {
        let queryItems = [
            URLQueryItem(name: "limit", value: "\(limit)"),
            URLQueryItem(name: "offset", value: "\(offset)")
        ]
        return try await request(.GET, path: "/api/comparisons", queryItems: queryItems)
    }

    public func getComparison(id: String) async throws -> ComparisonSet {
        return try await request(.GET, path: "/api/comparisons/\(id)")
    }

    public func deleteComparison(id: String) async throws {
        try await requestNoContent(.DELETE, path: "/api/comparisons/\(id)")
    }

    // MARK: - Action Items Endpoints

    public func listActionItems(status: ActionItem.Status? = nil, priority: ActionItem.Priority? = nil) async throws -> [ActionItem] {
        var queryItems: [URLQueryItem] = []
        if let status = status {
            queryItems.append(URLQueryItem(name: "status", value: status.rawValue))
        }
        if let priority = priority {
            queryItems.append(URLQueryItem(name: "priority", value: priority.rawValue))
        }
        return try await request(.GET, path: "/api/action-items", queryItems: queryItems.isEmpty ? nil : queryItems)
    }

    public func updateActionItem(id: String, status: ActionItem.Status) async throws -> ActionItem {
        let body = ["status": status.rawValue]
        return try await request(.PATCH, path: "/api/action-items/\(id)", body: body)
    }

    public func deleteActionItem(id: String) async throws {
        try await requestNoContent(.DELETE, path: "/api/action-items/\(id)")
    }

    // MARK: - Dictation Persistence Endpoints

    public func listDictationEntries() async throws -> [DictationEntryDTO] {
        return try await request(.GET, path: "/api/dictation/entries")
    }

    public func createDictationEntry(
        _ request: CreateDictationEntryRequest
    ) async throws -> DictationEntryDTO {
        return try await self.request(.POST, path: "/api/dictation/entries", body: request)
    }

    public func deleteDictationEntry(clientEntryID: UUID) async throws {
        try await requestNoContent(
            .DELETE,
            path: "/api/dictation/entries/\(clientEntryID.uuidString.lowercased())"
        )
    }

    public func listDictationDictionary() async throws -> [DictionaryWordDTO] {
        return try await request(.GET, path: "/api/dictation/dictionary")
    }

    public func createDictionaryWord(
        _ request: CreateDictionaryWordRequest
    ) async throws -> DictionaryWordDTO {
        return try await self.request(.POST, path: "/api/dictation/dictionary", body: request)
    }

    public func deleteDictionaryWord(clientWordID: UUID) async throws {
        try await requestNoContent(
            .DELETE,
            path: "/api/dictation/dictionary/\(clientWordID.uuidString.lowercased())"
        )
    }

    // MARK: - Chat Endpoints

    // MARK: - Companion Endpoints

    public func createCompanionChat(scope: CompanionScope? = nil) async throws -> CompanionConversation {
        struct Body: Encodable { let scope: CompanionScope? }
        return try await request(.POST, path: "/api/companion/chats", body: Body(scope: scope))
    }

    public func listCompanionChats(limit: Int? = nil, before: String? = nil) async throws -> CompanionConversationList {
        var query: [URLQueryItem] = []
        if let limit { query.append(URLQueryItem(name: "limit", value: String(limit))) }
        if let before { query.append(URLQueryItem(name: "before", value: before)) }
        return try await request(.GET, path: "/api/companion/chats", queryItems: query.isEmpty ? nil : query)
    }

    public func getCompanionChat(
        chatId: String,
        messagesLimit: Int? = nil,
        beforeMessageId: String? = nil
    ) async throws -> CompanionConversationDetail {
        var query: [URLQueryItem] = []
        if let messagesLimit { query.append(URLQueryItem(name: "messages_limit", value: String(messagesLimit))) }
        if let beforeMessageId { query.append(URLQueryItem(name: "before_message_id", value: beforeMessageId)) }
        return try await request(
            .GET,
            path: "/api/companion/chats/\(chatId)",
            queryItems: query.isEmpty ? nil : query
        )
    }

    public func patchCompanionChat(
        chatId: String,
        title: String? = nil,
        scope: CompanionScope? = nil,
        pinned: Bool? = nil,
        archived: Bool? = nil
    ) async throws -> CompanionConversation {
        struct Body: Encodable {
            let title: String?
            let scope: CompanionScope?
            let pinned: Bool?
            let archived: Bool?
        }
        return try await request(
            .PATCH,
            path: "/api/companion/chats/\(chatId)",
            body: Body(title: title, scope: scope, pinned: pinned, archived: archived)
        )
    }

    /// Move a Wai chat into a folder, or out of one with `folderId: nil`.
    public func moveCompanionChat(chatId: String, folderId: String?) async throws -> CompanionConversation {
        return try await request(
            .PATCH,
            path: "/api/companion/chats/\(chatId)",
            body: FolderAssignmentBody(folderId: folderId)
        )
    }

    public func deleteCompanionChat(chatId: String) async throws {
        try await requestNoContent(.DELETE, path: "/api/companion/chats/\(chatId)")
    }

    /// Open an SSE stream for a new turn. Yields typed events until the server
    /// emits `done` or `error`. Refreshes the access token once on 401 before
    /// surfacing the failure to the caller.
    public func streamCompanionMessage(
        chatId: String,
        content: String,
        viewingRecordingId: String? = nil,
        viewingFolderId: String? = nil,
        clientCapabilities: [String] = ["actions_v1", "agent_chat_v2"],
        now: Date = Date(),
        timeZone: TimeZone = .current,
        calendar: Calendar = .current
    ) async throws -> AsyncStream<CompanionStreamEvent> {
        // Per-turn working memory the server cannot guess: the user's local
        // calendar date (the server only knows UTC), their IANA timezone, and
        // whatever recording/folder they have open right now. This is what
        // lets the agent resolve "yesterday" / "вчера" / "this week"
        // correctly. Date format is the strict ISO YYYY-MM-DD that the
        // backend Pydantic model expects.
        struct Body: Encodable {
            let content: String
            let client_local_date: String
            let client_timezone: String
            let viewing_recording_id: String?
            let viewing_folder_id: String?
            let client_capabilities: [String]
        }
        var dayCal = calendar
        dayCal.timeZone = timeZone
        let dayFormatter = DateFormatter()
        dayFormatter.calendar = dayCal
        dayFormatter.locale = Locale(identifier: "en_US_POSIX")
        dayFormatter.timeZone = timeZone
        dayFormatter.dateFormat = "yyyy-MM-dd"
        let body = Body(
            content: content,
            client_local_date: dayFormatter.string(from: now),
            client_timezone: timeZone.identifier,
            viewing_recording_id: viewingRecordingId,
            viewing_folder_id: viewingFolderId,
            client_capabilities: clientCapabilities
        )
        let path = "/api/companion/chats/\(chatId)/messages"

        func buildRequest() throws -> URLRequest {
            var request = try buildJSONRequest(
                method: .POST,
                path: path,
                body: body,
                queryItems: nil,
                timeoutInterval: nil
            )
            request.setValue("text/event-stream", forHTTPHeaderField: "Accept")
            request.setValue("no-cache", forHTTPHeaderField: "Cache-Control")
            return request
        }

        func openStream(with request: URLRequest) async throws -> (URLSession.AsyncBytes, HTTPURLResponse) {
            Log.api.info("→ POST \(path)")
            let bytes: URLSession.AsyncBytes
            let response: URLResponse
            do {
                (bytes, response) = try await session.bytes(for: request)
            } catch {
                SentryHelper.captureRequestFailure(
                    APIError.networkError(error),
                    method: "POST",
                    path: path
                )
                Log.api.error("✗ POST \(path) failed")
                throw APIError.networkError(error)
            }
            guard let httpResponse = response as? HTTPURLResponse else {
                throw APIError.networkError(URLError(.badServerResponse))
            }
            Log.api.info("← POST \(path) (\(httpResponse.statusCode))")
            SentryHelper.addBreadcrumb(
                category: "api",
                message: "POST \(path)",
                data: ["statusCode": httpResponse.statusCode]
            )
            return (bytes, httpResponse)
        }

        let initialRequest = try buildRequest()
        var (bytes, response) = try await openStream(with: initialRequest)

        if response.statusCode == 401 {
            SentryHelper.addBreadcrumb(
                category: "auth",
                message: "token refresh triggered",
                data: ["path": path]
            )
            // Drain the error body so the underlying connection closes cleanly
            // before we try to refresh.
            for try await _ in bytes {}
            let newToken: String
            do {
                newToken = try await handleUnauthorized(path: path)
                SentryHelper.addBreadcrumb(category: "auth", message: "token refreshed")
            } catch {
                SentryHelper.addBreadcrumb(category: "auth", message: "auth failed", level: .error)
                throw error
            }
            var retryRequest = try buildRequest()
            retryRequest.setValue("Bearer \(newToken)", forHTTPHeaderField: "Authorization")
            let retried = try await openStream(with: retryRequest)
            if retried.1.statusCode == 401 {
                SentryHelper.addBreadcrumb(
                    category: "auth",
                    message: "auth failed after refresh",
                    level: .error
                )
                onAuthenticationFailed?()
                throw APIError.unauthorized
            }
            bytes = retried.0
            response = retried.1
        }

        guard (200..<300).contains(response.statusCode) else {
            let bodyData = await Self.collectBody(bytes)
            let error = apiError(from: bodyData, response: response)
            SentryHelper.captureRequestFailure(error, method: "POST", path: path)
            throw error
        }
        return companionEvents(bytes: bytes)
    }

    /// Drain an `AsyncBytes` stream into a `Data` blob so we can surface the
    /// server's `detail` on non-2xx. Capped at 64 KB — error bodies should
    /// always be much smaller.
    private static func collectBody(_ bytes: URLSession.AsyncBytes) async -> Data {
        var data = Data()
        let cap = 64 * 1024
        do {
            for try await byte in bytes {
                if data.count >= cap { break }
                data.append(byte)
            }
        } catch {
            // Discard — error path is best-effort.
        }
        return data
    }

    // MARK: - Dictation Endpoints

    private func normalizedDictationVocabulary(_ vocabulary: [String]) -> [String] {
        var seen = Set<String>()
        return vocabulary.compactMap { raw -> String? in
            let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !trimmed.isEmpty else { return nil }
            let key = trimmed.lowercased()
            guard seen.insert(key).inserted else { return nil }
            return trimmed
        }
    }

    public func cleanupDictation(
        text: String,
        vocabulary: [String] = [],
        context: DictationCleanupContext? = nil
    ) async throws -> String {
        struct CleanupRequest: Encodable {
            let text: String
            let vocabulary: [String]?
            let context: DictationCleanupContext?
        }
        struct CleanupResponse: Decodable {
            let text: String
        }
        // Trim + dedupe (case-insensitive, preserving first-seen order) before
        // sending. Empty vocab is sent as nil so older backends parsing the
        // request stay happy with the existing schema.
        let cleaned = normalizedDictationVocabulary(vocabulary)
        let payload = CleanupRequest(
            text: text,
            vocabulary: cleaned.isEmpty ? nil : cleaned,
            context: context
        )
        let response: CleanupResponse = try await request(
            .POST,
            path: "/api/dictation/cleanup",
            body: payload,
            timeoutInterval: 60
        )
        return response.text
    }

    public func streamCleanupDictation(
        text: String,
        vocabulary: [String] = [],
        context: DictationCleanupContext? = nil
    ) async throws -> AsyncStream<DictationCleanupStreamEvent> {
        struct CleanupRequest: Encodable {
            let text: String
            let vocabulary: [String]?
            let context: DictationCleanupContext?
        }
        let cleaned = normalizedDictationVocabulary(vocabulary)
        let payload = CleanupRequest(
            text: text,
            vocabulary: cleaned.isEmpty ? nil : cleaned,
            context: context
        )
        let path = "/api/dictation/cleanup/stream"

        func buildRequest() throws -> URLRequest {
            var request = try buildJSONRequest(
                method: .POST,
                path: path,
                body: payload,
                queryItems: nil,
                timeoutInterval: 60
            )
            request.setValue("text/event-stream", forHTTPHeaderField: "Accept")
            request.setValue("no-cache", forHTTPHeaderField: "Cache-Control")
            return request
        }

        func openStream(with request: URLRequest) async throws -> (URLSession.AsyncBytes, HTTPURLResponse) {
            Log.api.info("→ POST \(path)")
            let bytes: URLSession.AsyncBytes
            let response: URLResponse
            do {
                (bytes, response) = try await session.bytes(for: request)
            } catch {
                SentryHelper.captureRequestFailure(
                    APIError.networkError(error),
                    method: "POST",
                    path: path
                )
                Log.api.error("✗ POST \(path) failed")
                throw APIError.networkError(error)
            }
            guard let httpResponse = response as? HTTPURLResponse else {
                throw APIError.networkError(URLError(.badServerResponse))
            }
            Log.api.info("← POST \(path) (\(httpResponse.statusCode))")
            SentryHelper.addBreadcrumb(
                category: "api",
                message: "POST \(path)",
                data: ["statusCode": httpResponse.statusCode]
            )
            return (bytes, httpResponse)
        }

        let initialRequest = try buildRequest()
        var (bytes, response) = try await openStream(with: initialRequest)

        if response.statusCode == 401 {
            SentryHelper.addBreadcrumb(
                category: "auth",
                message: "token refresh triggered",
                data: ["path": path]
            )
            for try await _ in bytes {}
            let newToken: String
            do {
                newToken = try await handleUnauthorized(path: path)
                SentryHelper.addBreadcrumb(category: "auth", message: "token refreshed")
            } catch {
                SentryHelper.addBreadcrumb(category: "auth", message: "auth failed", level: .error)
                throw error
            }
            var retryRequest = try buildRequest()
            retryRequest.setValue("Bearer \(newToken)", forHTTPHeaderField: "Authorization")
            let retried = try await openStream(with: retryRequest)
            if retried.1.statusCode == 401 {
                SentryHelper.addBreadcrumb(
                    category: "auth",
                    message: "auth failed after refresh",
                    level: .error
                )
                onAuthenticationFailed?()
                throw APIError.unauthorized
            }
            bytes = retried.0
            response = retried.1
        }

        guard (200..<300).contains(response.statusCode) else {
            let bodyData = await Self.collectBody(bytes)
            let error = apiError(from: bodyData, response: response)
            SentryHelper.captureRequestFailure(error, method: "POST", path: path)
            throw error
        }
        return dictationCleanupEvents(bytes: bytes)
    }

    public func translateDictation(
        text: String,
        targetLanguageCode: String,
        targetLanguageName: String,
        vocabulary: [String] = [],
        context: DictationCleanupContext? = nil
    ) async throws -> String {
        struct TranslationRequest: Encodable {
            let text: String
            let targetLanguageCode: String
            let targetLanguageName: String
            let vocabulary: [String]?
            let context: DictationCleanupContext?

            enum CodingKeys: String, CodingKey {
                case text
                case targetLanguageCode = "target_language_code"
                case targetLanguageName = "target_language_name"
                case vocabulary
                case context
            }
        }
        struct TranslationResponse: Decodable {
            let text: String
        }
        let cleaned = normalizedDictationVocabulary(vocabulary)
        let payload = TranslationRequest(
            text: text,
            targetLanguageCode: targetLanguageCode,
            targetLanguageName: targetLanguageName,
            vocabulary: cleaned.isEmpty ? nil : cleaned,
            context: context
        )
        let response: TranslationResponse = try await request(
            .POST,
            path: "/api/dictation/translate",
            body: payload,
            timeoutInterval: 60
        )
        return response.text
    }

    /// Command mode: apply a dictated instruction to the selected text, or
    /// generate text for the cursor when `selectedText` is nil.
    public func transformDictation(
        instruction: String,
        selectedText: String? = nil,
        vocabulary: [String] = [],
        context: DictationCleanupContext? = nil
    ) async throws -> String {
        struct TransformRequest: Encodable {
            let instruction: String
            let selectedText: String?
            let vocabulary: [String]?
            let context: DictationCleanupContext?

            enum CodingKeys: String, CodingKey {
                case instruction
                case selectedText = "selected_text"
                case vocabulary
                case context
            }
        }
        struct TransformResponse: Decodable {
            let text: String
        }
        let cleaned = normalizedDictationVocabulary(vocabulary)
        let payload = TransformRequest(
            instruction: instruction,
            selectedText: selectedText,
            vocabulary: cleaned.isEmpty ? nil : cleaned,
            context: context
        )
        let response: TransformResponse = try await request(
            .POST,
            path: "/api/dictation/transform",
            body: payload,
            timeoutInterval: 60
        )
        return response.text
    }

    // MARK: - Dictation Snippets

    public struct DictationSnippetPayload: Codable, Equatable, Sendable {
        public let clientSnippetId: UUID
        public let trigger: String
        public let expansion: String
        public let occurredAt: Date

        public init(clientSnippetId: UUID, trigger: String, expansion: String, occurredAt: Date) {
            self.clientSnippetId = clientSnippetId
            self.trigger = trigger
            self.expansion = expansion
            self.occurredAt = occurredAt
        }

        enum CodingKeys: String, CodingKey {
            case clientSnippetId = "client_snippet_id"
            case trigger
            case expansion
            case occurredAt = "occurred_at"
        }
    }

    public func listDictationSnippets() async throws -> [DictationSnippetPayload] {
        try await request(.GET, path: "/api/dictation/snippets")
    }

    public func createDictationSnippet(
        _ snippet: DictationSnippetPayload
    ) async throws -> DictationSnippetPayload {
        try await request(.POST, path: "/api/dictation/snippets", body: snippet)
    }

    public func deleteDictationSnippet(clientSnippetId: UUID) async throws {
        try await requestNoContent(
            .DELETE,
            path: "/api/dictation/snippets/\(clientSnippetId.uuidString.lowercased())"
        )
    }

    // MARK: - Realtime Voice Endpoints

    public func createRealtimeTranscriptionSession(
        language: String = "multi",
        channels: Int = 1,
        purpose: RealtimeTranscriptionPurpose = .recording,
        keyterms: [String] = [],
        replacements: [RealtimeTranscriptionReplacement] = []
    ) async throws -> RealtimeTranscriptionSessionConfig {
        let body = CreateRealtimeTranscriptionSessionRequest(
            language: language,
            channels: channels,
            purpose: purpose,
            keyterms: keyterms,
            replacements: replacements
        )
        return try await request(.POST, path: "/api/transcription/session", body: body)
    }

    public func createRealtimeVoiceSession(
        mode: RealtimeVoiceMode = .conversation,
        modelId: String? = nil,
        includeConversationId: Bool = false,
        branchId: String? = nil,
        environment: String? = nil
    ) async throws -> RealtimeVoiceSession {
        let body = CreateRealtimeVoiceSessionRequest(
            mode: mode,
            modelId: modelId,
            includeConversationId: includeConversationId,
            branchId: branchId,
            environment: environment
        )
        return try await request(.POST, path: "/api/voice/session", body: body)
    }

    // MARK: - Folder Endpoints

    public func listFolders() async throws -> [Folder] {
        return try await request(.GET, path: "/api/folders")
    }

    public func createFolder(name: String) async throws -> Folder {
        return try await request(.POST, path: "/api/folders", body: FolderNameRequest(name: name))
    }

    public func updateFolder(id: String, name: String) async throws -> Folder {
        return try await request(.PATCH, path: "/api/folders/\(id)", body: FolderNameRequest(name: name))
    }

    public func deleteFolder(id: String) async throws {
        try await requestNoContent(.DELETE, path: "/api/folders/\(id)")
    }

    // MARK: - File Upload

    public func saveLiveTranscript(
        recordingId: String,
        segments: [LiveTranscriptSegment],
        durationSeconds: Int
    ) async throws -> RecordingDetail {
        let body = SaveTranscriptRequest(
            segments: segments.map { TranscriptSegmentRequest(segment: $0) },
            durationSeconds: durationSeconds
        )
        return try await request(.POST, path: "/api/recordings/\(recordingId)/transcript", body: body)
    }

    public func uploadAudio(
        recordingId: String,
        fileURL: URL,
        clientDurationSeconds: Int? = nil,
        clientFileSizeBytes: Int64? = nil,
        captureMetadataJSON: String? = nil
    ) async throws -> RecordingDetail {
        // `clientFileSizeBytes` is retained for source compatibility. The
        // multipart field is populated from the bytes actually copied into the
        // request body so a file-size race during finalization cannot poison
        // the server-side upload.
        let fileSize = try fileSize(at: fileURL)
        if fileSize > Int64(Self.maxRecordingUploadSizeBytes) {
            throw APIError.httpError(
                statusCode: 413,
                message: "File too large. Maximum size is \(Self.maxRecordingUploadSizeBytes / (1024 * 1024))MB."
            )
        }

        let path = "/api/recordings/\(recordingId)/upload"
        let url = baseURL.appendingPathComponent(path)

        let boundary = "Boundary-\(UUID().uuidString)"
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 600

        if let token = accessToken {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        let filename = fileURL.lastPathComponent
        let ext = fileURL.pathExtension.lowercased()
        let mimeType = MediaImportSupport.mimeType(forExtension: ext)

        let uploadRequestFile = try createUploadRequestFile(
            sourceFileURL: fileURL,
            filename: filename,
            mimeType: mimeType,
            boundary: boundary,
            clientDurationSeconds: clientDurationSeconds,
            captureMetadataJSON: captureMetadataJSON
        )
        defer { try? FileManager.default.removeItem(at: uploadRequestFile.url) }

        if uploadRequestFile.copiedFileSizeBytes > Int64(Self.maxRecordingUploadSizeBytes) {
            throw APIError.httpError(
                statusCode: 413,
                message: "File too large. Maximum size is \(Self.maxRecordingUploadSizeBytes / (1024 * 1024))MB."
            )
        }

        let (data, _) = try await performWithAuthRetry(
            &request,
            path: path,
            method: "POST",
            extras: ["recordingId": recordingId]
        ) { req in
            try await self.session.upload(for: req, fromFile: uploadRequestFile.url)
        }

        do {
            return try decoder.decode(RecordingDetail.self, from: data)
        } catch {
            throw APIError.decodingError(error)
        }
    }

    private func fileSize(at url: URL) throws -> Int64 {
        let values = try url.resourceValues(forKeys: [.fileSizeKey])
        return Int64(values.fileSize ?? 0)
    }

    private func createUploadRequestFile(
        sourceFileURL: URL,
        filename: String,
        mimeType: String,
        boundary: String,
        clientDurationSeconds: Int?,
        captureMetadataJSON: String? = nil
    ) throws -> (url: URL, copiedFileSizeBytes: Int64) {
        let uploadURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("wai-upload-\(UUID().uuidString).multipart")
        FileManager.default.createFile(atPath: uploadURL.path, contents: nil)

        let output = try FileHandle(forWritingTo: uploadURL)
        defer { try? output.close() }

        func writeString(_ string: String) throws {
            try output.write(contentsOf: Data(string.utf8))
        }

        func writeField(name: String, value: String) throws {
            try writeString("--\(boundary)\r\n")
            try writeString("Content-Disposition: form-data; name=\"\(name)\"\r\n\r\n")
            try writeString("\(value)\r\n")
        }

        if let clientDurationSeconds, clientDurationSeconds > 0 {
            try writeField(
                name: "client_duration_seconds",
                value: String(clientDurationSeconds)
            )
        }

        if let captureMetadataJSON, !captureMetadataJSON.isEmpty {
            try writeField(name: "capture_metadata", value: captureMetadataJSON)
        }

        try writeString("--\(boundary)\r\n")
        try writeString(
            "Content-Disposition: form-data; name=\"file\"; filename=\"\(filename)\"\r\n"
        )
        try writeString("Content-Type: \(mimeType)\r\n\r\n")

        let input = try FileHandle(forReadingFrom: sourceFileURL)
        defer { try? input.close() }

        var copiedFileSizeBytes: Int64 = 0
        while true {
            let chunk = try input.read(upToCount: 64 * 1024) ?? Data()
            if chunk.isEmpty {
                break
            }
            copiedFileSizeBytes += Int64(chunk.count)
            try output.write(contentsOf: chunk)
        }

        try writeString("\r\n")

        try writeField(
            name: "client_file_size_bytes",
            value: String(copiedFileSizeBytes)
        )

        try writeString("--\(boundary)--\r\n")
        return (uploadURL, copiedFileSizeBytes)
    }
}

private struct CreateItemRequest: Encodable {
    var source: String
    var kind: String
    var title: String?
    var body: String?
    var url: String?
    var folderId: String?

    private enum CodingKeys: String, CodingKey {
        case source
        case kind
        case title
        case body
        case url
        case folderId = "folder_id"
    }
}

private struct CreateComparisonRequest: Encodable {
    var itemIds: [String]
    var title: String?
    var intent: String?

    private enum CodingKeys: String, CodingKey {
        case itemIds = "item_ids"
        case title
        case intent
    }
}

/// PATCH body that always emits folder_id — null moves the object out of its
/// folder, a uuid moves it in. An absent key would mean "keep", which is
/// never what a move call wants.
private struct FolderAssignmentBody: Encodable {
    let folderId: String?

    private enum CodingKeys: String, CodingKey {
        case folderId = "folder_id"
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        if let folderId {
            try container.encode(folderId, forKey: .folderId)
        } else {
            try container.encodeNil(forKey: .folderId)
        }
    }
}

private struct UpdateRecordingRequestBody: Encodable {
    var title: String?
    var type: String?
    var folderId: String?
    var includeFolderId = false

    private enum CodingKeys: String, CodingKey {
        case title
        case type
        case folderId = "folder_id"
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        if let title {
            try container.encode(title, forKey: .title)
        }
        if let type {
            try container.encode(type, forKey: .type)
        }
        if includeFolderId {
            if let folderId {
                try container.encode(folderId, forKey: .folderId)
            } else {
                try container.encodeNil(forKey: .folderId)
            }
        }
    }
}

private struct BulkRecordingOperationRequest: Encodable {
    let recordingIds: [String]
    let action: BulkRecordingAction
    let folderId: String?

    private enum CodingKeys: String, CodingKey {
        case recordingIds = "recording_ids"
        case action
        case folderId = "folder_id"
    }
}

private struct FolderNameRequest: Encodable {
    let name: String
}

private struct CreatePersonRequestBody: Encodable {
    let displayName: String
    let color: String?

    private enum CodingKeys: String, CodingKey {
        case displayName = "display_name"
        case color
    }
}

private struct UpdatePersonRequestBody: Encodable {
    let displayName: String?
    let color: String?

    private enum CodingKeys: String, CodingKey {
        case displayName = "display_name"
        case color
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        if let displayName {
            try container.encode(displayName, forKey: .displayName)
        }
        if let color {
            try container.encode(color, forKey: .color)
        }
    }
}

private struct MergePersonRequestBody: Encodable {
    let intoPersonId: String

    private enum CodingKeys: String, CodingKey {
        case intoPersonId = "into_person_id"
    }
}

private struct AssignSpeakerRequestBody: Encodable {
    let rawLabel: String
    let personId: String?
    let newDisplayName: String?

    private enum CodingKeys: String, CodingKey {
        case rawLabel = "raw_label"
        case personId = "person_id"
        case newDisplayName = "new_display_name"
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(rawLabel, forKey: .rawLabel)
        if let personId {
            try container.encode(personId, forKey: .personId)
        }
        if let newDisplayName {
            try container.encode(newDisplayName, forKey: .newDisplayName)
        }
    }
}

private struct TranscriptSegmentRequest: Encodable {
    let text: String
    let speaker: String?
    let startMs: Int
    let endMs: Int
    let confidence: Double?

    init(segment: LiveTranscriptSegment) {
        text = segment.text
        speaker = segment.speaker
        startMs = segment.startMs
        endMs = segment.endMs
        confidence = segment.confidence
    }

    private enum CodingKeys: String, CodingKey {
        case text
        case speaker
        case startMs = "start_ms"
        case endMs = "end_ms"
        case confidence
    }
}

private struct SaveTranscriptRequest: Encodable {
    let segments: [TranscriptSegmentRequest]
    let durationSeconds: Int

    private enum CodingKeys: String, CodingKey {
        case segments
        case durationSeconds = "duration_seconds"
    }
}

/// Simple message response
public struct MessageResponse: Codable, Sendable {
    public let message: String
}
