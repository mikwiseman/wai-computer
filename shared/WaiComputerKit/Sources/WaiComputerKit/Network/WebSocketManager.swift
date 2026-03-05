import Foundation

public enum WebSocketConnectionError: Error, LocalizedError, Sendable {
    case disconnected(Error?)
    case readyTimeout
    case serverError(String?)
    case superseded

    public var errorDescription: String? {
        switch self {
        case .disconnected(let error):
            return error?.localizedDescription ?? "The WebSocket disconnected before it was ready."
        case .readyTimeout:
            return "Timed out waiting for the recording WebSocket to become ready."
        case .serverError(let message):
            return message ?? "The server rejected the recording WebSocket connection."
        case .superseded:
            return "The WebSocket connection was replaced by a newer connection attempt."
        }
    }
}

/// WebSocket message types
public enum WebSocketMessageType: String, Codable, Sendable {
    case audio
    case transcript
    case status
    case end
}

/// Outgoing audio message
public struct AudioMessage: Codable, Sendable {
    public var type: String = "audio"
    public let data: String
    public let timestamp: Int64

    public init(data: String, timestamp: Int64) {
        self.data = data
        self.timestamp = timestamp
    }

    private enum CodingKeys: String, CodingKey {
        case type, data, timestamp
    }
}

/// Incoming transcript message
public struct TranscriptMessage: Codable, Sendable {
    public let type: String
    public let text: String
    public let speaker: String?
    public let isFinal: Bool
    public let startMs: Int
    public let endMs: Int

    private enum CodingKeys: String, CodingKey {
        case type
        case text
        case speaker
        case isFinal = "is_final"
        case startMs = "start_ms"
        case endMs = "end_ms"
    }
}

/// Status message
public struct StatusMessage: Codable, Sendable {
    public let type: String
    public let status: String
    public let message: String?
}

/// WebSocket event
public enum WebSocketEvent: Sendable {
    case connected
    case transcript(TranscriptMessage)
    case status(StatusMessage)
    case disconnected(Error?)
}

private protocol WebSocketTasking: Sendable {
    func resume()
    func send(_ message: URLSessionWebSocketTask.Message) async throws
    func receive() async throws -> URLSessionWebSocketTask.Message
    func cancel(with closeCode: URLSessionWebSocketTask.CloseCode, reason: Data?)
}

private final class URLSessionWebSocketTransport: WebSocketTasking, @unchecked Sendable {
    private let task: URLSessionWebSocketTask

    init(task: URLSessionWebSocketTask) {
        self.task = task
    }

    func resume() {
        task.resume()
    }

    func send(_ message: URLSessionWebSocketTask.Message) async throws {
        try await task.send(message)
    }

    func receive() async throws -> URLSessionWebSocketTask.Message {
        try await task.receive()
    }

    func cancel(with closeCode: URLSessionWebSocketTask.CloseCode, reason: Data?) {
        task.cancel(with: closeCode, reason: reason)
    }
}

/// WebSocket manager for real-time audio streaming
public actor WebSocketManager {
    private typealias WebSocketFactory = @Sendable (URLRequest) -> any WebSocketTasking

    private enum ReadyHandshakeState {
        case idle
        case waiting(CheckedContinuation<Void, Error>)
        case ready
        case failed(Error)
    }

    private enum MessageHandlingResult {
        case continueListening
        case stopListening
    }

    private let baseURL: URL
    private let webSocketFactory: WebSocketFactory
    private let readyTimeout: Duration
    private var webSocket: (any WebSocketTasking)?
    private var accessToken: String?

    private var eventContinuation: AsyncStream<WebSocketEvent>.Continuation?
    private var receiveTask: Task<Void, Never>?
    private var connectionId: UInt64 = 0
    private var readyHandshakeState: ReadyHandshakeState = .idle
    private var hasEmittedConnected = false
    private var sendCount = 0

    private let encoder = JSONEncoder()
    private let decoder = JSONDecoder()

    /// Stream of WebSocket events - must be accessed from async context.
    /// Returns a FRESH stream for the current connection.
    /// Call this BEFORE connect() to ensure no events are missed.
    public var events: AsyncStream<WebSocketEvent> {
        let (stream, continuation) = AsyncStream.makeStream(of: WebSocketEvent.self)
        eventContinuation?.finish()
        eventContinuation = continuation
        return stream
    }

    public init(baseURL: URL, accessToken: String? = nil) {
        self.baseURL = baseURL
        self.accessToken = accessToken
        self.readyTimeout = .seconds(10)

        let session = URLSession(configuration: .default)
        self.webSocketFactory = { request in
            URLSessionWebSocketTransport(task: session.webSocketTask(with: request))
        }
    }

    private init(
        baseURL: URL,
        accessToken: String? = nil,
        readyTimeout: Duration,
        webSocketFactory: @escaping WebSocketFactory
    ) {
        self.baseURL = baseURL
        self.accessToken = accessToken
        self.readyTimeout = readyTimeout
        self.webSocketFactory = webSocketFactory
    }

    /// Set access token
    public func setAccessToken(_ token: String?) {
        self.accessToken = token
    }

    /// Connect to WebSocket for a recording.
    /// Disconnects any existing connection first to prevent event leakage.
    public func connect(recordingId: String) async throws {
        guard let token = accessToken else {
            throw APIError.unauthorized
        }

        if webSocket != nil || receiveTask != nil {
            print("[WS] Disconnecting previous connection before new one")
            closeConnection(
                forConnection: connectionId,
                error: WebSocketConnectionError.superseded,
                emitDisconnected: true
            )
        }

        if eventContinuation == nil {
            let (stream, continuation) = AsyncStream.makeStream(of: WebSocketEvent.self)
            eventContinuation = continuation
            _ = stream
        }

        connectionId &+= 1
        let thisConnection = connectionId
        readyHandshakeState = .idle
        hasEmittedConnected = false
        sendCount = 0

        let wsURL = try makeWebSocketURL(token: token, recordingId: recordingId)
        print("[WS] Connecting to: \(wsURL.host ?? "?")\(wsURL.path)")

        var request = URLRequest(url: wsURL)
        request.timeoutInterval = 300

        let socket = webSocketFactory(request)
        webSocket = socket
        socket.resume()

        receiveTask = Task { [weak self] in
            await self?.receiveMessages(forConnection: thisConnection)
        }

        do {
            try await waitForReady(forConnection: thisConnection)
        } catch {
            closeConnection(forConnection: thisConnection, error: error, emitDisconnected: true)
            throw error
        }
    }

    /// Send audio data
    public func sendAudio(data: Data) async throws {
        guard let webSocket = webSocket else {
            print("[WS] sendAudio: no webSocket task")
            throw APIError.networkError(URLError(.notConnectedToInternet))
        }

        let base64 = data.base64EncodedString()
        let message = AudioMessage(
            data: base64,
            timestamp: Int64(Date().timeIntervalSince1970 * 1000)
        )

        let jsonData = try encoder.encode(message)
        guard let jsonString = String(data: jsonData, encoding: .utf8) else {
            throw APIError.noData
        }

        sendCount += 1
        if sendCount <= 3 || sendCount % 50 == 0 {
            print("[WS] sendAudio #\(sendCount): \(data.count) bytes raw, \(jsonString.count) chars JSON")
        }

        try await webSocket.send(.string(jsonString))
    }

    /// Send end signal
    public func sendEnd() async throws {
        guard let webSocket = webSocket else { return }

        let message = ["type": "end"]
        let jsonData = try encoder.encode(message)
        guard let jsonString = String(data: jsonData, encoding: .utf8) else { return }

        try await webSocket.send(.string(jsonString))
    }

    /// Disconnect the active socket and finish the current event stream.
    public func disconnect() {
        closeConnection(forConnection: connectionId, error: nil, emitDisconnected: true)
    }

    private func receiveMessages(forConnection expectedId: UInt64) async {
        guard let webSocket = webSocket else {
            print("[WS] receiveMessages: no webSocket task")
            return
        }

        print("[WS] receiveMessages: started listening (connection \(expectedId))")
        do {
            while true {
                guard connectionId == expectedId else {
                    print("[WS] receiveMessages: connection \(expectedId) superseded, stopping")
                    return
                }

                let message = try await webSocket.receive()

                switch message {
                case .string(let text):
                    print("[WS] Received: \(String(text.prefix(120)))")
                    if handleMessage(text, forConnection: expectedId) == .stopListening {
                        return
                    }
                case .data(let data):
                    print("[WS] Received binary: \(data.count) bytes")
                    if let text = String(data: data, encoding: .utf8),
                       handleMessage(text, forConnection: expectedId) == .stopListening {
                        return
                    }
                @unknown default:
                    break
                }
            }
        } catch {
            if connectionId == expectedId {
                print("[WS] receiveMessages error: \(error)")
                closeConnection(
                    forConnection: expectedId,
                    error: WebSocketConnectionError.disconnected(error),
                    emitDisconnected: true
                )
            } else {
                print("[WS] receiveMessages: old connection \(expectedId) closed (expected)")
            }
        }
    }

    private func handleMessage(_ text: String, forConnection expectedId: UInt64) -> MessageHandlingResult {
        guard let data = text.data(using: .utf8) else {
            return .continueListening
        }

        if let status = try? decoder.decode(StatusMessage.self, from: data), status.type == "status" {
            if status.status == "ready" {
                emitConnectedIfNeeded()
                eventContinuation?.yield(.status(status))
                markReady()
                return .continueListening
            }

            eventContinuation?.yield(.status(status))

            if status.status == "error", !isReady {
                closeConnection(
                    forConnection: expectedId,
                    error: WebSocketConnectionError.serverError(status.message),
                    emitDisconnected: true
                )
                return .stopListening
            }

            return .continueListening
        }

        if let transcript = try? decoder.decode(TranscriptMessage.self, from: data),
           transcript.type == "transcript" {
            eventContinuation?.yield(.transcript(transcript))
        }

        return .continueListening
    }

    private var isReady: Bool {
        if case .ready = readyHandshakeState {
            return true
        }
        return false
    }

    private func emitConnectedIfNeeded() {
        guard !hasEmittedConnected else { return }
        hasEmittedConnected = true
        eventContinuation?.yield(.connected)
    }

    private func markReady() {
        switch readyHandshakeState {
        case .waiting(let continuation):
            readyHandshakeState = .ready
            continuation.resume()
        case .idle, .failed:
            readyHandshakeState = .ready
        case .ready:
            break
        }
    }

    private func failReadyHandshake(with error: Error) {
        switch readyHandshakeState {
        case .waiting(let continuation):
            readyHandshakeState = .failed(error)
            continuation.resume(throwing: error)
        case .idle:
            readyHandshakeState = .failed(error)
        case .ready, .failed:
            break
        }
    }

    private func resetConnectionState() {
        webSocket = nil
        receiveTask?.cancel()
        receiveTask = nil
        readyHandshakeState = .idle
        hasEmittedConnected = false
        sendCount = 0
    }

    private func waitForReady(forConnection expectedId: UInt64) async throws {
        if case .ready = readyHandshakeState {
            return
        }

        if case .failed(let error) = readyHandshakeState {
            throw error
        }

        let timeout = readyTimeout
        try await withThrowingTaskGroup(of: Void.self) { group in
            group.addTask { [self] in
                try await waitForReadyContinuation(forConnection: expectedId)
            }

            group.addTask {
                try await Task.sleep(for: timeout)
                throw WebSocketConnectionError.readyTimeout
            }

            do {
                _ = try await group.next()
                group.cancelAll()
            } catch {
                group.cancelAll()
                throw error
            }
        }
    }

    private func waitForReadyContinuation(forConnection expectedId: UInt64) async throws {
        try await withCheckedThrowingContinuation { continuation in
            storeReadyContinuation(continuation, forConnection: expectedId)
        }
    }

    private func storeReadyContinuation(
        _ continuation: CheckedContinuation<Void, Error>,
        forConnection expectedId: UInt64
    ) {
        guard connectionId == expectedId else {
            continuation.resume(throwing: WebSocketConnectionError.superseded)
            return
        }

        switch readyHandshakeState {
        case .ready:
            continuation.resume()
        case .failed(let error):
            continuation.resume(throwing: error)
        case .waiting:
            continuation.resume(throwing: WebSocketConnectionError.superseded)
        case .idle:
            readyHandshakeState = .waiting(continuation)
        }
    }

    private func closeConnection(
        forConnection expectedId: UInt64,
        error: Error?,
        emitDisconnected: Bool
    ) {
        guard connectionId == expectedId else { return }
        guard webSocket != nil || receiveTask != nil || eventContinuation != nil else {
            resetConnectionState()
            return
        }

        if let error {
            failReadyHandshake(with: error)
        } else if !isReady {
            failReadyHandshake(with: WebSocketConnectionError.disconnected(nil))
        }

        webSocket?.cancel(with: .goingAway, reason: nil)

        if emitDisconnected {
            eventContinuation?.yield(.disconnected(error))
        }
        eventContinuation?.finish()
        eventContinuation = nil
        resetConnectionState()
    }

    private func makeWebSocketURL(token: String, recordingId: String) throws -> URL {
        guard var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: true) else {
            throw APIError.invalidURL
        }

        switch components.scheme?.lowercased() {
        case "http":
            components.scheme = "ws"
        case "https":
            components.scheme = "wss"
        case "ws", "wss":
            break
        default:
            throw APIError.invalidURL
        }

        let trimmedPath = components.path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        let prefix = trimmedPath.isEmpty ? "" : "/\(trimmedPath)"
        components.path = "\(prefix)/api/ws/audio"

        var queryItems = components.queryItems ?? []
        queryItems.append(URLQueryItem(name: "token", value: token))
        queryItems.append(URLQueryItem(name: "recording_id", value: recordingId))
        components.queryItems = queryItems

        guard let url = components.url else {
            throw APIError.invalidURL
        }

        return url
    }
}
