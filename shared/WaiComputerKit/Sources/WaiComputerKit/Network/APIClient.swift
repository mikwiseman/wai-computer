import Foundation

/// API errors
public enum APIError: Error, Sendable {
    case invalidURL
    case noData
    case decodingError(Error)
    case httpError(statusCode: Int, message: String?)
    case networkError(Error)
    case unauthorized
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
    private let baseURL: URL
    private var accessToken: String?
    private let session: URLSession

    private let encoder: JSONEncoder
    private let decoder: JSONDecoder

    public init(
        baseURL: URL,
        accessToken: String? = nil,
        session: URLSession? = nil
    ) {
        self.baseURL = baseURL
        self.accessToken = accessToken

        if let session {
            self.session = session
        } else {
            let config = URLSessionConfiguration.default
            config.timeoutIntervalForRequest = 30
            self.session = URLSession(configuration: config)
        }

        self.encoder = JSONEncoder()
        self.decoder = JSONDecoder()

        // Configure date decoding
        self.decoder.dateDecodingStrategy = .custom { decoder in
            let container = try decoder.singleValueContainer()
            let dateString = try container.decode(String.self)

            // Try ISO8601 with fractional seconds
            let formatter = ISO8601DateFormatter()
            formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            if let date = formatter.date(from: dateString) {
                return date
            }

            // Try ISO8601 without fractional seconds
            formatter.formatOptions = [.withInternetDateTime]
            if let date = formatter.date(from: dateString) {
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

    /// Get the current access token
    public func getAccessToken() -> String? {
        return accessToken
    }

    /// Make an API request
    public func request<T: Decodable>(
        _ method: HTTPMethod,
        path: String,
        body: (any Encodable)? = nil,
        queryItems: [URLQueryItem]? = nil
    ) async throws -> T {
        var urlComponents = URLComponents(url: baseURL.appendingPathComponent(path), resolvingAgainstBaseURL: true)
        urlComponents?.queryItems = queryItems

        guard let url = urlComponents?.url else {
            throw APIError.invalidURL
        }

        var request = URLRequest(url: url)
        request.httpMethod = method.rawValue
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        if let token = accessToken {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        if let body = body {
            request.httpBody = try encoder.encode(body)
        }

        let (data, response) = try await session.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.networkError(URLError(.badServerResponse))
        }

        if httpResponse.statusCode == 401 {
            throw APIError.unauthorized
        }

        guard (200...299).contains(httpResponse.statusCode) else {
            let message = String(data: data, encoding: .utf8)
            throw APIError.httpError(statusCode: httpResponse.statusCode, message: message)
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
        body: (any Encodable)? = nil
    ) async throws {
        let url = baseURL.appendingPathComponent(path)

        var request = URLRequest(url: url)
        request.httpMethod = method.rawValue
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        if let token = accessToken {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        if let body = body {
            request.httpBody = try encoder.encode(body)
        }

        let (data, response) = try await session.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.networkError(URLError(.badServerResponse))
        }

        if httpResponse.statusCode == 401 {
            throw APIError.unauthorized
        }

        guard (200...299).contains(httpResponse.statusCode) else {
            let message = String(data: data, encoding: .utf8)
            throw APIError.httpError(statusCode: httpResponse.statusCode, message: message)
        }
    }

    // MARK: - Auth Endpoints

    public func register(email: String, password: String) async throws -> TokenResponse {
        let request = RegisterRequest(email: email, password: password)
        return try await self.request(.POST, path: "/api/auth/register", body: request)
    }

    public func login(email: String, password: String) async throws -> TokenResponse {
        let request = LoginRequest(email: email, password: password)
        return try await self.request(.POST, path: "/api/auth/login", body: request)
    }

    public func requestMagicLink(email: String) async throws -> MessageResponse {
        let request = MagicLinkRequest(email: email)
        return try await self.request(.POST, path: "/api/auth/magic-link", body: request)
    }

    public func verifyMagicLink(token: String) async throws -> TokenResponse {
        let request = VerifyMagicLinkRequest(token: token)
        return try await self.request(.POST, path: "/api/auth/verify-magic", body: request)
    }

    public func refreshToken() async throws -> TokenResponse {
        return try await request(.POST, path: "/api/auth/refresh")
    }

    public func getCurrentUser() async throws -> User {
        return try await request(.GET, path: "/api/auth/me")
    }

    // MARK: - Recording Endpoints

    public func listRecordings(skip: Int = 0, limit: Int = 50, type: RecordingType? = nil) async throws -> [Recording] {
        var queryItems = [
            URLQueryItem(name: "skip", value: "\(skip)"),
            URLQueryItem(name: "limit", value: "\(limit)")
        ]
        if let type = type {
            queryItems.append(URLQueryItem(name: "type", value: type.rawValue))
        }
        return try await request(.GET, path: "/api/recordings", queryItems: queryItems)
    }

    public func createRecording(title: String? = nil, type: RecordingType = .note, language: String = "en") async throws -> Recording {
        let request = CreateRecordingRequest(title: title, type: type, language: language)
        return try await self.request(.POST, path: "/api/recordings", body: request)
    }

    public func getRecording(id: String) async throws -> RecordingDetail {
        return try await request(.GET, path: "/api/recordings/\(id)")
    }

    public func deleteRecording(id: String) async throws {
        try await requestNoContent(.DELETE, path: "/api/recordings/\(id)")
    }

    public func getTranscript(recordingId: String) async throws -> [Segment] {
        return try await request(.GET, path: "/api/recordings/\(recordingId)/transcript")
    }

    public func getSummary(recordingId: String) async throws -> Summary {
        return try await request(.GET, path: "/api/recordings/\(recordingId)/summary")
    }

    public func generateSummary(recordingId: String) async throws -> Summary {
        return try await request(.POST, path: "/api/recordings/\(recordingId)/generate-summary")
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

    // MARK: - Chat Endpoints

    public func sendChatMessage(question: String, sessionId: String? = nil, recordingIds: [String]? = nil) async throws -> ChatResponse {
        let body = ChatRequest(question: question, sessionId: sessionId, recordingIds: recordingIds)
        return try await request(.POST, path: "/api/chat", body: body)
    }

    public func listChatSessions() async throws -> [ChatSessionListItem] {
        return try await request(.GET, path: "/api/chat/sessions")
    }

    public func getChatSession(id: String) async throws -> ChatSessionDetail {
        return try await request(.GET, path: "/api/chat/sessions/\(id)")
    }

    public func deleteChatSession(id: String) async throws {
        try await requestNoContent(.DELETE, path: "/api/chat/sessions/\(id)")
    }

    // MARK: - Entity Endpoints

    public func listEntities(type: EntityType? = nil) async throws -> [Entity] {
        var queryItems: [URLQueryItem]? = nil
        if let type = type {
            queryItems = [URLQueryItem(name: "type", value: type.rawValue)]
        }
        return try await request(.GET, path: "/api/entities", queryItems: queryItems)
    }

    public func getEntity(id: String) async throws -> EntityDetail {
        return try await request(.GET, path: "/api/entities/\(id)")
    }
}

/// Simple message response
public struct MessageResponse: Codable, Sendable {
    public let message: String
}
