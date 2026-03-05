import Foundation

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

/// WebSocket manager for real-time audio streaming
public actor WebSocketManager {
    private let baseURL: URL
    private var webSocket: URLSessionWebSocketTask?
    private let session: URLSession
    private var accessToken: String?

    private var eventContinuation: AsyncStream<WebSocketEvent>.Continuation?
    private var eventStream: AsyncStream<WebSocketEvent>?
    private var connectionId: UInt64 = 0

    /// Stream of WebSocket events - must be accessed from async context.
    /// Returns a FRESH stream for the current connection.
    /// Call this BEFORE connect() to ensure no events are missed.
    public var events: AsyncStream<WebSocketEvent> {
        // Always create a fresh stream — prevents events leaking between recordings
        let (stream, continuation) = AsyncStream.makeStream(of: WebSocketEvent.self)
        eventContinuation?.finish()  // finish any old stream
        eventContinuation = continuation
        eventStream = stream
        return stream
    }

    private let encoder = JSONEncoder()
    private let decoder = JSONDecoder()

    public init(baseURL: URL, accessToken: String? = nil) {
        self.baseURL = baseURL
        self.accessToken = accessToken
        self.session = URLSession(configuration: .default)
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

        // Disconnect any previous connection cleanly
        if webSocket != nil {
            print("[WS] Disconnecting previous connection before new one")
            disconnect()
        }

        // Ensure event stream exists (caller should have called .events already)
        if eventContinuation == nil {
            let (stream, continuation) = AsyncStream.makeStream(of: WebSocketEvent.self)
            eventContinuation = continuation
            eventStream = stream
        }

        connectionId &+= 1
        let thisConnection = connectionId
        sendCount = 0

        // Build WebSocket URL
        var wsURLString = baseURL.absoluteString
            .replacingOccurrences(of: "http://", with: "ws://")
            .replacingOccurrences(of: "https://", with: "wss://")
        wsURLString += "/api/ws/audio?token=\(token)&recording_id=\(recordingId)"

        guard let wsURL = URL(string: wsURLString) else {
            throw APIError.invalidURL
        }

        print("[WS] Connecting to: \(wsURL.host ?? "?")\(wsURL.path)")

        var request = URLRequest(url: wsURL)
        request.timeoutInterval = 300

        webSocket = session.webSocketTask(with: request)
        webSocket?.resume()

        print("[WS] WebSocket task resumed, state: active")
        eventContinuation?.yield(.connected)

        // Start receiving messages in background — scoped to this connection
        Task { [weak self] in
            await self?.receiveMessages(forConnection: thisConnection)
        }
    }

    private var sendCount = 0

    /// Send audio data
    public func sendAudio(data: Data) async throws {
        guard let webSocket = webSocket else {
            print("[WS] sendAudio: no webSocket task!")
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

    /// Disconnect
    public func disconnect() {
        webSocket?.cancel(with: .goingAway, reason: nil)
        webSocket = nil
        eventContinuation?.yield(.disconnected(nil))
        eventContinuation?.finish()
        eventContinuation = nil
        eventStream = nil
    }

    private func receiveMessages(forConnection expectedId: UInt64) async {
        guard let webSocket = webSocket else {
            print("[WS] receiveMessages: no webSocket task")
            return
        }

        print("[WS] receiveMessages: started listening (connection \(expectedId))")
        do {
            while true {
                // Stop if this connection has been superseded
                guard connectionId == expectedId else {
                    print("[WS] receiveMessages: connection \(expectedId) superseded, stopping")
                    return
                }

                let message = try await webSocket.receive()

                switch message {
                case .string(let text):
                    print("[WS] Received: \(String(text.prefix(120)))")
                    handleMessage(text)
                case .data(let data):
                    print("[WS] Received binary: \(data.count) bytes")
                    if let text = String(data: data, encoding: .utf8) {
                        handleMessage(text)
                    }
                @unknown default:
                    break
                }
            }
        } catch {
            // Only emit disconnected if this is still the active connection
            if connectionId == expectedId {
                print("[WS] receiveMessages error: \(error)")
                eventContinuation?.yield(.disconnected(error))
                eventContinuation?.finish()
            } else {
                print("[WS] receiveMessages: old connection \(expectedId) closed (expected)")
            }
        }
    }

    private func handleMessage(_ text: String) {
        guard let data = text.data(using: .utf8) else { return }

        // Try to decode as status first
        if let status = try? decoder.decode(StatusMessage.self, from: data), status.type == "status" {
            eventContinuation?.yield(.status(status))
            return
        }

        // Try to decode as transcript
        if let transcript = try? decoder.decode(TranscriptMessage.self, from: data), transcript.type == "transcript" {
            eventContinuation?.yield(.transcript(transcript))
            return
        }
    }
}
