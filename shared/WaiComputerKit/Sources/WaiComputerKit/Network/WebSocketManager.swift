import Foundation

/// Deepgram token response from backend
public struct DeepgramTokenResponse: Codable, Sendable {
    public let accessToken: String

    private enum CodingKeys: String, CodingKey {
        case accessToken = "access_token"
    }
}

/// Transcript segment collected during a live recording session
public struct LiveTranscriptSegment: Codable, Sendable {
    public let text: String
    public let speaker: String?
    public let isFinal: Bool
    public let startMs: Int
    public let endMs: Int
    public let confidence: Double

    public init(text: String, speaker: String?, isFinal: Bool, startMs: Int, endMs: Int, confidence: Double) {
        self.text = text
        self.speaker = speaker
        self.isFinal = isFinal
        self.startMs = startMs
        self.endMs = endMs
        self.confidence = confidence
    }

    private enum CodingKeys: String, CodingKey {
        case text, speaker
        case isFinal = "is_final"
        case startMs = "start_ms"
        case endMs = "end_ms"
        case confidence
    }
}

public enum WebSocketConnectionError: Error, LocalizedError, Sendable {
    case disconnected(Error?)
    case tokenFetchFailed(String)
    case serverError(String?)
    case superseded
    case invalidURL

    public var errorDescription: String? {
        switch self {
        case .disconnected(let error):
            return error?.localizedDescription ?? "The WebSocket disconnected."
        case .tokenFetchFailed(let message):
            return "Failed to get transcription token: \(message)"
        case .serverError(let message):
            return message ?? "Transcription service error."
        case .superseded:
            return "The WebSocket connection was replaced by a newer connection attempt."
        case .invalidURL:
            return "Failed to construct a valid Deepgram WebSocket URL."
        }
    }
}

/// WebSocket event
public enum WebSocketEvent: Sendable {
    case connected
    case transcript(LiveTranscriptSegment)
    case disconnected(Error?)
}

/// WebSocket manager for direct Deepgram streaming.
///
/// Connects directly to `wss://api.deepgram.com/v1/listen` using a short-lived
/// JWT obtained from the backend's `/api/deepgram-token` endpoint.
public actor WebSocketManager {
    private let apiClient: APIClient
    private let language: String
    private let channels: Int

    private var webSocket: URLSessionWebSocketTask?
    private var eventContinuation: AsyncStream<WebSocketEvent>.Continuation?
    private var receiveTask: Task<Void, Never>?
    private var keepAliveTask: Task<Void, Never>?
    private var connectionId: UInt64 = 0
    private var sendCount = 0

    /// All final transcript segments collected during this session.
    public private(set) var collectedSegments: [LiveTranscriptSegment] = []

    /// Stream of WebSocket events. Call BEFORE connect() to not miss events.
    ///
    /// If a continuation already exists (previous caller is still iterating),
    /// replaces it and logs a warning — the previous stream will end.
    public var events: AsyncStream<WebSocketEvent> {
        if eventContinuation != nil {
            print("[WS] Warning: replacing active event stream — previous iterator will be terminated")
        }
        let (stream, continuation) = AsyncStream.makeStream(of: WebSocketEvent.self)
        eventContinuation?.finish()
        eventContinuation = continuation
        return stream
    }

    public init(apiClient: APIClient, language: String = "multi", channels: Int = 1) {
        self.apiClient = apiClient
        self.language = language
        self.channels = channels
    }

    /// Connect to Deepgram directly using a temporary token from the backend.
    public func connect() async throws {
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
        sendCount = 0
        collectedSegments = []

        // Fetch temporary Deepgram JWT from backend
        let tokenResponse: DeepgramTokenResponse = try await apiClient.request(
            .GET, path: "/api/deepgram-token"
        )
        let dgToken = tokenResponse.accessToken

        // Build Deepgram WebSocket URL with token as query param
        // (more reliable than header for WebSocket upgrade handshake)
        let url = try buildDeepgramURL(token: dgToken)
        print("[WS] Connecting to Deepgram: \(url.host ?? "")\(url.path)")

        var request = URLRequest(url: url)
        request.timeoutInterval = 300
        request.setValue("Bearer \(dgToken)", forHTTPHeaderField: "Authorization")

        let session = URLSession(configuration: .default)
        let socket = session.webSocketTask(with: request)
        webSocket = socket
        socket.resume()

        receiveTask = Task { [weak self] in
            await self?.receiveMessages(forConnection: thisConnection)
        }

        // Send KeepAlive every 5s to prevent Deepgram's 10s silence timeout
        keepAliveTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(5))
                guard !Task.isCancelled else { break }
                try? await self?.webSocket?.send(.string("{\"type\":\"KeepAlive\"}"))
            }
        }
    }

    /// Send raw PCM audio data directly to Deepgram.
    public func sendAudio(data: Data) async throws {
        guard let webSocket else {
            throw APIError.networkError(URLError(.notConnectedToInternet))
        }

        sendCount += 1
        if sendCount <= 3 || sendCount % 50 == 0 {
            print("[WS] sendAudio #\(sendCount): \(data.count) bytes")
        }

        try await webSocket.send(.data(data))
    }

    /// Signal end of audio stream. Deepgram will send final results then close.
    public func sendEnd() async throws {
        guard let webSocket else { return }

        let closeMessage = "{\"type\":\"CloseStream\"}"
        try await webSocket.send(.string(closeMessage))
        print("[WS] Sent CloseStream to Deepgram")
    }

    /// Ask Deepgram to finalize the stream and wait for the socket to close.
    @discardableResult
    public func finishStreaming(timeout: Duration = .seconds(5)) async throws -> Bool {
        try await sendEnd()
        return await waitForDisconnect(timeout: timeout)
    }

    @discardableResult
    public func waitForDisconnect(timeout: Duration = .seconds(5)) async -> Bool {
        let expectedConnection = connectionId
        let clock = ContinuousClock()
        let deadline = clock.now + timeout

        while connectionId == expectedConnection && (webSocket != nil || receiveTask != nil) {
            if clock.now >= deadline {
                return false
            }
            try? await Task.sleep(for: .milliseconds(100))
        }
        return true
    }

    /// Disconnect and clean up.
    public func disconnect() {
        closeConnection(forConnection: connectionId, error: nil, emitDisconnected: true)
    }

    // MARK: - Private

    private func buildDeepgramURL(token: String) throws -> URL {
        var params = [
            "model=nova-3",
            "language=\(language)",
            "punctuate=true",
            "diarize=true",
            "interim_results=true",
            "utterance_end_ms=1000",
            "vad_events=true",
            "encoding=linear16",
            "sample_rate=16000",
            "token=\(token)",
        ]
        if channels > 1 {
            params.append("channels=\(channels)")
            params.append("multichannel=true")
        }
        if language == "multi" {
            params.append("endpointing=100")
        }
        let queryString = params.joined(separator: "&")
        guard let url = URL(string: "wss://api.deepgram.com/v1/listen?\(queryString)") else {
            throw WebSocketConnectionError.invalidURL
        }
        return url
    }

    private func receiveMessages(forConnection expectedId: UInt64) async {
        guard let webSocket else { return }

        print("[WS] receiveMessages: started listening (connection \(expectedId))")
        eventContinuation?.yield(.connected)
        do {
            while true {
                guard connectionId == expectedId else {
                    print("[WS] receiveMessages: connection \(expectedId) superseded")
                    return
                }

                let message = try await webSocket.receive()

                switch message {
                case .string(let text):
                    if connectionId == expectedId {
                        handleDeepgramMessage(text)
                    }
                case .data(let data):
                    if let text = String(data: data, encoding: .utf8),
                       connectionId == expectedId {
                        handleDeepgramMessage(text)
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
            }
        }
    }

    private func handleDeepgramMessage(_ text: String) {
        guard let data = text.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return }

        let msgType = json["type"] as? String ?? ""

        guard msgType == "Results" else { return }

        let isFinal = json["is_final"] as? Bool ?? false

        // Multichannel: Deepgram returns channel_index for each result
        let channelIndex = (json["channel_index"] as? [Int])?.first ?? 0

        guard let channel = json["channel"] as? [String: Any],
              let alternatives = channel["alternatives"] as? [[String: Any]],
              let alt = alternatives.first,
              let transcript = alt["transcript"] as? String,
              !transcript.isEmpty
        else { return }

        let words = alt["words"] as? [[String: Any]] ?? []
        var speaker: String? = nil
        var startMs = 0
        var endMs = 0

        if let firstWord = words.first {
            if channels > 1 {
                // In multichannel mode, use channel index for speaker label
                // ch0 = mic (user), ch1 = system audio (others)
                speaker = channelIndex == 0 ? "You" : "Speaker \(channelIndex)"
            } else {
                let speakerIdx = firstWord["speaker"] as? Int ?? 0
                speaker = "Speaker \(speakerIdx)"
            }
            startMs = Int((firstWord["start"] as? Double ?? 0) * 1000)
        }
        if let lastWord = words.last {
            endMs = Int((lastWord["end"] as? Double ?? 0) * 1000)
        }

        let confidence = alt["confidence"] as? Double ?? 0.0

        let segment = LiveTranscriptSegment(
            text: transcript,
            speaker: speaker,
            isFinal: isFinal,
            startMs: startMs,
            endMs: endMs,
            confidence: confidence
        )

        if isFinal {
            collectedSegments.append(segment)
        }

        eventContinuation?.yield(.transcript(segment))
    }

    private func closeConnection(
        forConnection expectedId: UInt64,
        error: Error?,
        emitDisconnected: Bool
    ) {
        guard connectionId == expectedId else { return }

        webSocket?.cancel(with: .goingAway, reason: nil)
        webSocket = nil

        receiveTask?.cancel()
        receiveTask = nil
        keepAliveTask?.cancel()
        keepAliveTask = nil

        if emitDisconnected {
            eventContinuation?.yield(.disconnected(error))
        }
        eventContinuation?.finish()
        eventContinuation = nil

        sendCount = 0
    }
}
