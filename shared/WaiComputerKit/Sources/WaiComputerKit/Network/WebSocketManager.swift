import Foundation
import os
import Sentry

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
    case reconnectionExhausted(Int)

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
        case .reconnectionExhausted(let attempts):
            return "Failed to reconnect after \(attempts) attempts."
        }
    }
}

/// WebSocket event
public enum WebSocketEvent: Sendable {
    case connected
    case transcript(LiveTranscriptSegment)
    case disconnected(Error?)
    case reconnecting(attempt: Int, maxAttempts: Int)
    case reconnected
    case reconnectionFailed(Error?)
}

/// WebSocket manager for direct Deepgram streaming.
///
/// Connects directly to `wss://api.deepgram.com/v1/listen` using a short-lived
/// JWT obtained from the backend's `/api/deepgram-token` endpoint.
///
/// Automatically reconnects with exponential backoff when the connection drops
/// during an active recording session. Audio is buffered locally during
/// reconnection and replayed once the connection is restored.
public actor WebSocketManager {
    private let wsLog = Logger(subsystem: "com.waicomputer.kit", category: "websocket")
    private let apiClient: APIClient
    private let language: String
    private let channels: Int

    private var webSocket: URLSessionWebSocketTask?
    private var eventContinuation: AsyncStream<WebSocketEvent>.Continuation?
    private var receiveTask: Task<Void, Never>?
    private var keepAliveTask: Task<Void, Never>?
    private var connectionId: UInt64 = 0
    private var sendCount = 0

    // MARK: - Reconnection state

    private var reconnectEnabled = false
    private var isReconnecting = false
    private var reconnectAttempt = 0
    private var reconnectTask: Task<Void, Never>?
    private let maxReconnectAttempts = 10
    private let baseReconnectDelayMs: UInt64 = 500
    private let maxReconnectDelayMs: UInt64 = 30_000

    // MARK: - Audio buffer for replay after reconnection

    private var audioBuffer: [Data] = []
    private let maxBufferChunks = 300 // ~30s of audio at ~100ms/chunk

    /// All final transcript segments collected during this session.
    /// Preserved across reconnections so no transcript data is lost.
    public private(set) var collectedSegments: [LiveTranscriptSegment] = []

    /// Stream of WebSocket events. Call BEFORE connect() to not miss events.
    ///
    /// Returns the same stream instance on each access. The stream is created
    /// once and reused — no more race conditions from replacing continuations.
    private var _eventStream: AsyncStream<WebSocketEvent>?
    public var events: AsyncStream<WebSocketEvent> {
        if let existing = _eventStream {
            return existing
        }
        let (stream, continuation) = AsyncStream.makeStream(of: WebSocketEvent.self)
        eventContinuation = continuation
        _eventStream = stream
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
            wsLog.debug("Disconnecting previous connection before new one")
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
        reconnectAttempt = 0
        audioBuffer = []
        isReconnecting = false
        reconnectTask?.cancel()
        reconnectTask = nil

        // Fetch temporary Deepgram JWT from backend
        let tokenResponse: DeepgramTokenResponse = try await apiClient.request(
            .GET, path: "/api/deepgram-token"
        )
        let dgToken = tokenResponse.accessToken

        // Build Deepgram WebSocket URL with token as query param
        // (more reliable than header for WebSocket upgrade handshake)
        let url = try buildDeepgramURL(token: dgToken)
        wsLog.debug("Connecting to Deepgram: \(url.host ?? "", privacy: .public)\(url.path, privacy: .public)")

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

        // Enable auto-reconnection after successful initial setup
        reconnectEnabled = true
        SentryHelper.addBreadcrumb(category: "websocket", message: "connected to Deepgram")
    }

    /// Send raw PCM audio data directly to Deepgram.
    ///
    /// During reconnection, audio is buffered locally (up to ~30s) and replayed
    /// once the connection is restored. This method does NOT throw during
    /// reconnection — the recording continues uninterrupted.
    public func sendAudio(data: Data) async throws {
        if isReconnecting || webSocket == nil {
            if reconnectEnabled {
                bufferAudioChunk(data)
                return
            }
            throw APIError.networkError(URLError(.notConnectedToInternet))
        }

        sendCount += 1
        if sendCount <= 3 || sendCount % 50 == 0 {
            wsLog.debug("sendAudio #\(self.sendCount): \(data.count) bytes")
        }

        do {
            try await webSocket?.send(.data(data))
        } catch {
            if reconnectEnabled {
                bufferAudioChunk(data)
                // receiveMessages will detect the disconnect and start reconnection
                return
            }
            throw error
        }
    }

    /// Signal end of audio stream. Deepgram will send final results then close.
    /// Disables auto-reconnection since this is an intentional close.
    public func sendEnd() async throws {
        reconnectEnabled = false
        cancelReconnection()

        guard let webSocket else { return }

        let closeMessage = "{\"type\":\"CloseStream\"}"
        try await webSocket.send(.string(closeMessage))
        wsLog.debug("Sent CloseStream to Deepgram")
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

        while connectionId == expectedConnection
            && (webSocket != nil || receiveTask != nil || isReconnecting) {
            if clock.now >= deadline {
                return false
            }
            try? await Task.sleep(for: .milliseconds(100))
        }
        return true
    }

    /// Disconnect and clean up. Cancels any in-progress reconnection.
    public func disconnect() {
        reconnectEnabled = false
        cancelReconnection()
        closeConnection(forConnection: connectionId, error: nil, emitDisconnected: true)
        SentryHelper.addBreadcrumb(category: "websocket", message: "disconnected")
    }

    // MARK: - Private

    func buildDeepgramURL(token: String) throws -> URL {
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

        wsLog.debug("receiveMessages: started listening (connection \(expectedId))")
        eventContinuation?.yield(.connected)
        do {
            while true {
                guard connectionId == expectedId else {
                    wsLog.debug("receiveMessages: connection \(expectedId) superseded")
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
                wsLog.error("receiveMessages error: \(error.localizedDescription, privacy: .public)")
                if reconnectEnabled {
                    startReconnection(afterError: error)
                } else {
                    closeConnection(
                        forConnection: expectedId,
                        error: WebSocketConnectionError.disconnected(error),
                        emitDisconnected: true
                    )
                }
            }
        }
    }

    private func handleDeepgramMessage(_ text: String) {
        guard let data = text.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return }

        let msgType = json["type"] as? String ?? ""

        guard msgType == "Results" else { return }

        // Reset reconnect counter on successful data receipt — connection is healthy
        if reconnectAttempt > 0 {
            reconnectAttempt = 0
        }

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

    // MARK: - Reconnection

    private func startReconnection(afterError: Error) {
        guard reconnectEnabled, !isReconnecting else { return }

        isReconnecting = true

        // Clean up current socket without finishing the event continuation
        webSocket?.cancel(with: .goingAway, reason: nil)
        webSocket = nil
        receiveTask?.cancel()
        receiveTask = nil
        keepAliveTask?.cancel()
        keepAliveTask = nil

        wsLog.info("Starting reconnection (error: \(afterError.localizedDescription, privacy: .public))")
        SentryHelper.addBreadcrumb(
            category: "websocket",
            message: "reconnect started",
            level: .warning,
            data: ["bufferedChunks": audioBuffer.count, "reason": afterError.localizedDescription]
        )

        reconnectTask = Task { [weak self] in
            await self?.reconnectLoop()
        }
    }

    private func reconnectLoop() async {
        defer {
            reconnectTask = nil
        }

        while reconnectAttempt < maxReconnectAttempts {
            guard !Task.isCancelled else {
                isReconnecting = false
                return
            }

            reconnectAttempt += 1
            SentryHelper.addBreadcrumb(
                category: "websocket",
                message: "reconnecting",
                level: .warning,
                data: ["attempt": reconnectAttempt, "maxAttempts": maxReconnectAttempts]
            )
            eventContinuation?.yield(.reconnecting(
                attempt: reconnectAttempt,
                maxAttempts: maxReconnectAttempts
            ))

            // Exponential backoff with jitter
            let baseDelay = min(
                baseReconnectDelayMs * (1 << UInt64(reconnectAttempt - 1)),
                maxReconnectDelayMs
            )
            let jitter = UInt64.random(in: 0...(baseDelay / 2))
            let delayMs = baseDelay + jitter

            wsLog.info("Reconnect attempt \(self.reconnectAttempt)/\(self.maxReconnectAttempts) in \(delayMs)ms")

            do {
                try await Task.sleep(for: .milliseconds(delayMs))
            } catch {
                isReconnecting = false
                return
            }

            guard !Task.isCancelled else {
                isReconnecting = false
                return
            }

            do {
                // Fetch new token
                let tokenResponse: DeepgramTokenResponse = try await apiClient.request(
                    .GET, path: "/api/deepgram-token"
                )
                let url = try buildDeepgramURL(token: tokenResponse.accessToken)

                var request = URLRequest(url: url)
                request.timeoutInterval = 300
                request.setValue(
                    "Bearer \(tokenResponse.accessToken)",
                    forHTTPHeaderField: "Authorization"
                )

                let session = URLSession(configuration: .default)
                let socket = session.webSocketTask(with: request)
                webSocket = socket

                connectionId &+= 1
                let thisConnection = connectionId
                sendCount = 0
                // NOTE: collectedSegments are preserved across reconnections

                socket.resume()

                receiveTask = Task { [weak self] in
                    await self?.receiveMessages(forConnection: thisConnection)
                }

                keepAliveTask = Task { [weak self] in
                    while !Task.isCancelled {
                        try? await Task.sleep(for: .seconds(5))
                        guard !Task.isCancelled else { break }
                        try? await self?.webSocket?.send(.string("{\"type\":\"KeepAlive\"}"))
                    }
                }

                // Replay buffered audio
                let bufferedChunks = audioBuffer
                audioBuffer = []
                isReconnecting = false

                wsLog.info(
                    "Reconnected after \(self.reconnectAttempt) attempt(s), replaying \(bufferedChunks.count) audio chunks"
                )

                for chunk in bufferedChunks {
                    do {
                        try await socket.send(.data(chunk))
                    } catch {
                        wsLog.error("Failed to replay buffered audio: \(error.localizedDescription, privacy: .public)")
                        // New connection is also broken — receiveMessages will trigger another reconnection
                        break
                    }
                }

                eventContinuation?.yield(.reconnected)
                return // Success

            } catch {
                wsLog.error(
                    "Reconnect attempt \(self.reconnectAttempt) failed: \(error.localizedDescription, privacy: .public)"
                )
                // Clean up failed connection attempt
                webSocket?.cancel(with: .goingAway, reason: nil)
                webSocket = nil
                receiveTask?.cancel()
                receiveTask = nil
                keepAliveTask?.cancel()
                keepAliveTask = nil
            }
        }

        // Max attempts reached
        isReconnecting = false
        wsLog.error("Reconnection failed after \(self.maxReconnectAttempts) attempts")

        let exhaustedError = WebSocketConnectionError.reconnectionExhausted(maxReconnectAttempts)
        SentryHelper.captureError(exhaustedError, extras: ["attempts": maxReconnectAttempts])
        eventContinuation?.yield(.reconnectionFailed(exhaustedError))
    }

    private func cancelReconnection() {
        isReconnecting = false
        reconnectTask?.cancel()
        reconnectTask = nil
        audioBuffer = []
    }

    private func bufferAudioChunk(_ data: Data) {
        audioBuffer.append(data)
        if audioBuffer.count > maxBufferChunks {
            audioBuffer.removeFirst()
        }
    }

    func testingBufferAudioChunk(_ data: Data) {
        bufferAudioChunk(data)
    }

    func testingBufferedAudioCount() -> Int {
        audioBuffer.count
    }

    func testingMarkReconnecting() {
        isReconnecting = true
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
