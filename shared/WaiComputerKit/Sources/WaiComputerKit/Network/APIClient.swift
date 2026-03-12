import Foundation

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
    public static let maxRecordingUploadSizeBytes = 200 * 1024 * 1024

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

    /// Get the current access token
    public func getAccessToken() -> String? {
        return accessToken
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

    /// Make an API request
    public func request<T: Decodable>(
        _ method: HTTPMethod,
        path: String,
        body: (any Encodable)? = nil,
        queryItems: [URLQueryItem]? = nil,
        timeoutInterval: TimeInterval? = nil
    ) async throws -> T {
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

        if let body = body {
            request.httpBody = try encoder.encode(AnyEncodable(body))
        }

        let (data, response) = try await session.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.networkError(URLError(.badServerResponse))
        }

        if httpResponse.statusCode == 401 {
            throw APIError.unauthorized
        }

        guard (200...299).contains(httpResponse.statusCode) else {
            throw apiError(from: data, response: httpResponse)
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

        if let body = body {
            request.httpBody = try encoder.encode(AnyEncodable(body))
        }

        let (data, response) = try await session.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.networkError(URLError(.badServerResponse))
        }

        if httpResponse.statusCode == 401 {
            throw APIError.unauthorized
        }

        guard (200...299).contains(httpResponse.statusCode) else {
            throw apiError(from: data, response: httpResponse)
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

    public func requestMagicLink(email: String, client: String? = nil) async throws -> MessageResponse {
        let request = MagicLinkRequest(email: email, client: client)
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

    public func changePassword(currentPassword: String, newPassword: String) async throws -> MessageResponse {
        let body = ChangePasswordRequest(currentPassword: currentPassword, newPassword: newPassword)
        return try await request(.POST, path: "/api/settings/change-password", body: body)
    }

    public func logout() async throws -> MessageResponse {
        return try await request(.POST, path: "/api/auth/logout")
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

    public func deleteActionItem(id: String) async throws {
        try await requestNoContent(.DELETE, path: "/api/action-items/\(id)")
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

    public func renameChatSession(id: String, title: String?) async throws -> RenameSessionResponse {
        let body = RenameSessionRequest(title: title)
        return try await request(.PATCH, path: "/api/chat/sessions/\(id)", body: body)
    }

    public func exportChatSession(id: String) async throws -> String {
        let url = baseURL.appendingPathComponent("/api/chat/sessions/\(id)/export")
        var req = URLRequest(url: url)
        req.httpMethod = "GET"
        if let token = accessToken {
            req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }
        let (data, response) = try await session.data(for: req)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.networkError(URLError(.badServerResponse))
        }
        guard httpResponse.statusCode == 200 else {
            throw APIError.httpError(statusCode: httpResponse.statusCode, message: "Export failed")
        }
        guard let markdown = String(data: data, encoding: .utf8) else {
            throw APIError.decodingError(DecodingError.dataCorrupted(
                .init(codingPath: [], debugDescription: "Invalid UTF-8 data")
            ))
        }
        return markdown
    }

    public func deleteChatSession(id: String) async throws {
        try await requestNoContent(.DELETE, path: "/api/chat/sessions/\(id)")
    }

    // MARK: - Dictation Endpoints

    public func cleanupDictation(text: String) async throws -> String {
        struct CleanupRequest: Encodable {
            let text: String
        }
        struct CleanupResponse: Decodable {
            let text: String
        }
        let response: CleanupResponse = try await request(
            .POST,
            path: "/api/dictation/cleanup",
            body: CleanupRequest(text: text),
            timeoutInterval: 60
        )
        return response.text
    }

    // MARK: - Entity Endpoints

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

    public func uploadAudio(recordingId: String, fileURL: URL) async throws -> RecordingDetail {
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
        request.timeoutInterval = 300

        if let token = accessToken {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        let filename = fileURL.lastPathComponent
        let ext = fileURL.pathExtension.lowercased()
        let mimeType: String
        switch ext {
        case "mp3": mimeType = "audio/mpeg"
        case "wav": mimeType = "audio/wav"
        case "m4a": mimeType = "audio/mp4"
        case "ogg": mimeType = "audio/ogg"
        case "webm": mimeType = "audio/webm"
        case "opus": mimeType = "audio/opus"
        case "flac": mimeType = "audio/flac"
        default: mimeType = "application/octet-stream"
        }

        let multipartFileURL = try createUploadRequestFile(
            sourceFileURL: fileURL,
            filename: filename,
            mimeType: mimeType,
            boundary: boundary
        )
        defer { try? FileManager.default.removeItem(at: multipartFileURL) }

        let (data, response) = try await session.upload(for: request, fromFile: multipartFileURL)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.networkError(URLError(.badServerResponse))
        }

        if httpResponse.statusCode == 401 {
            throw APIError.unauthorized
        }

        guard (200...299).contains(httpResponse.statusCode) else {
            throw apiError(from: data, response: httpResponse)
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
        boundary: String
    ) throws -> URL {
        let uploadURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("wai-upload-\(UUID().uuidString).multipart")
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

        let input = try FileHandle(forReadingFrom: sourceFileURL)
        defer { try? input.close() }

        while true {
            let chunk = try input.read(upToCount: 64 * 1024) ?? Data()
            if chunk.isEmpty {
                break
            }
            try output.write(contentsOf: chunk)
        }

        try writeString("\r\n")

        try writeString("--\(boundary)--\r\n")
        return uploadURL
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

private struct FolderNameRequest: Encodable {
    let name: String
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
