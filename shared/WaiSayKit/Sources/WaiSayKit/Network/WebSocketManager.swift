import Foundation
import os
import Sentry

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
            return "Failed to construct a valid transcription WebSocket URL."
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

/// WebSocket manager for provider-backed realtime speech-to-text streaming.
///
/// The manager asks the backend for a provider-specific realtime transcription
/// session, then streams PCM audio directly to the selected provider.
public actor WebSocketManager {
    private static let documentedRealtimeErrorTypes: Set<String> = [
        "error",
        "auth_error",
        "quota_exceeded",
        "commit_throttled",
        "unaccepted_terms",
        "rate_limited",
        "queue_overflow",
        "resource_exhausted",
        "session_time_limit_exceeded",
        "input_error",
        "chunk_size_exceeded",
        "insufficient_audio_activity",
        "transcriber_error",
    ]

    private let wsLog = Logger(subsystem: "com.waisay.kit", category: "websocket")
    private let apiClient: APIClient
    private let language: String
    private let channels: Int

    private var webSocket: URLSessionWebSocketTask?
    private var eventContinuation: AsyncStream<WebSocketEvent>.Continuation?
    private var receiveTask: Task<Void, Never>?
    private var connectionId: UInt64 = 0
    private var sendCount = 0
    private var transcriptionSession: RealtimeTranscriptionSessionConfig?
    private let reconnectClock = ContinuousClock()
    private var lastTranscriptReceivedAt: ContinuousClock.Instant?

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
        ensureEventStream()
        return _eventStream!
    }

    public init(apiClient: APIClient, language: String = "multi", channels: Int = 1) {
        self.apiClient = apiClient
        self.language = language
        self.channels = channels
    }

    /// Connect to the configured transcription provider using a backend-issued session token.
    public func connect() async throws {
        if webSocket != nil || receiveTask != nil {
            wsLog.debug("Disconnecting previous connection before new one")
            closeConnection(
                forConnection: connectionId,
                error: WebSocketConnectionError.superseded,
                emitDisconnected: true,
                finishEventStream: false
            )
        }

        ensureEventStream()

        connectionId &+= 1
        let thisConnection = connectionId
        sendCount = 0
        collectedSegments = []
        lastTranscriptReceivedAt = nil
        reconnectAttempt = 0
        audioBuffer = []
        isReconnecting = false
        reconnectTask?.cancel()
        reconnectTask = nil

        let sessionConfig = try await apiClient.createRealtimeTranscriptionSession(
            language: language,
            channels: channels
        )
        transcriptionSession = sessionConfig
        let request = try requestForRealtimeSession(sessionConfig)

        wsLog.debug(
            "Connecting to realtime transcription provider=\(sessionConfig.provider, privacy: .public)"
        )

        let session = URLSession(configuration: .default)
        let socket = session.webSocketTask(with: request)
        webSocket = socket
        socket.resume()

        receiveTask = Task { [weak self] in
            await self?.receiveMessages(forConnection: thisConnection)
        }

        // Enable auto-reconnection after successful initial setup
        reconnectEnabled = true
        SentryHelper.addBreadcrumb(
            category: "websocket",
            message: "connected to transcription provider",
            data: ["provider": sessionConfig.provider]
        )
    }

    /// Send raw PCM audio data directly to the configured provider.
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
            try await sendAudioChunk(data)
        } catch {
            if reconnectEnabled {
                bufferAudioChunk(data)
                return
            }
            throw error
        }
    }

    /// Signal end of audio stream and wait briefly for the final transcript.
    public func sendEnd() async throws {
        reconnectEnabled = false
        cancelReconnection()

        guard let webSocket else { return }
        try await webSocket.send(.string(makeElevenLabsAudioChunkMessage(
            data: Data(repeating: 0, count: 640),
            previousText: nil,
            commit: true
        )))
        wsLog.debug("Sent commit chunk to ElevenLabs")
    }

    /// Ask the provider to finalize the stream.
    @discardableResult
    public func finishStreaming(timeout: Duration = .seconds(5)) async throws -> Bool {
        try await sendEnd()
        let minimumWaitUntil = reconnectClock.now + .milliseconds(350)
        let quietWindow: Duration = .milliseconds(750)
        let deadline = reconnectClock.now + timeout

        while reconnectClock.now < deadline {
            let now = reconnectClock.now
            let isSettled: Bool
            if let lastTranscriptReceivedAt {
                isSettled = now >= minimumWaitUntil && now - lastTranscriptReceivedAt >= quietWindow
            } else {
                isSettled = now >= minimumWaitUntil
            }

            if isSettled {
                break
            }

            try? await Task.sleep(for: .milliseconds(100))
        }

        disconnect()
        return true
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
        closeConnection(
            forConnection: connectionId,
            error: nil,
            emitDisconnected: true,
            finishEventStream: false
        )
        SentryHelper.addBreadcrumb(category: "websocket", message: "disconnected")
    }

    // MARK: - URL builders

    func buildElevenLabsURL(
        token: String,
        model: String,
        commitStrategy: String?
    ) throws -> URL {
        var components = URLComponents(string: "wss://api.elevenlabs.io/v1/speech-to-text/realtime")
        var queryItems = [
            URLQueryItem(name: "model_id", value: model),
            URLQueryItem(name: "token", value: token),
            URLQueryItem(name: "include_timestamps", value: "true"),
            URLQueryItem(name: "audio_format", value: "pcm_16000"),
        ]
        if language == "multi" {
            queryItems.append(URLQueryItem(name: "include_language_detection", value: "true"))
        } else {
            queryItems.append(URLQueryItem(name: "language_code", value: language))
        }
        if let commitStrategy, !commitStrategy.isEmpty {
            queryItems.append(URLQueryItem(name: "commit_strategy", value: commitStrategy))
        }
        components?.queryItems = queryItems
        guard let url = components?.url else {
            throw WebSocketConnectionError.invalidURL
        }
        return url
    }

    // MARK: - Private

    private func requestForRealtimeSession(
        _ sessionConfig: RealtimeTranscriptionSessionConfig
    ) throws -> URLRequest {
        guard sessionConfig.provider == "elevenlabs" else {
            throw WebSocketConnectionError.tokenFetchFailed(
                "Unsupported transcription provider: \(sessionConfig.provider)"
            )
        }

        let url = try buildElevenLabsURL(
            token: sessionConfig.token,
            model: sessionConfig.model,
            commitStrategy: sessionConfig.commitStrategy
        )

        var request = URLRequest(url: url)
        request.timeoutInterval = 300
        return request
    }

    private func sendAudioChunk(
        _ data: Data,
        previousText: String? = nil,
        commit: Bool = false
    ) async throws {
        guard let webSocket else {
            throw APIError.networkError(URLError(.notConnectedToInternet))
        }

        try await webSocket.send(.string(makeElevenLabsAudioChunkMessage(
            data: data,
            previousText: previousText,
            commit: commit
        )))
    }

    private func makeElevenLabsAudioChunkMessage(
        data: Data,
        previousText: String?,
        commit: Bool
    ) -> String {
        var payload: [String: Any] = [
            "message_type": "input_audio_chunk",
            "audio_base_64": data.base64EncodedString(),
            "sample_rate": 16_000,
            "commit": commit,
        ]
        if let previousText, !previousText.isEmpty {
            payload["previous_text"] = previousText
        }

        let jsonData = try? JSONSerialization.data(withJSONObject: payload, options: [])
        return String(data: jsonData ?? Data("{}".utf8), encoding: .utf8) ?? "{}"
    }

    func testingMakeElevenLabsAudioChunkMessage(
        data: Data,
        previousText: String? = nil,
        commit: Bool = false
    ) -> String {
        makeElevenLabsAudioChunkMessage(
            data: data,
            previousText: previousText,
            commit: commit
        )
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
                        handleIncomingMessage(text)
                    }
                case .data(let data):
                    if let text = String(data: data, encoding: .utf8),
                       connectionId == expectedId {
                        handleIncomingMessage(text)
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
                        emitDisconnected: true,
                        finishEventStream: false
                    )
                }
            }
        }
    }

    private func handleIncomingMessage(_ text: String) {
        handleElevenLabsMessage(text)
    }

    private func handleElevenLabsMessage(_ text: String) {
        guard let data = text.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return }

        let messageType = (json["message_type"] as? String) ?? (json["type"] as? String) ?? ""

        switch messageType {
        case "session_started":
            if reconnectAttempt > 0 {
                reconnectAttempt = 0
            }

        case "partial_transcript":
            guard let transcript = json["text"] as? String,
                  !transcript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                return
            }
            lastTranscriptReceivedAt = reconnectClock.now
            let lastEndMs = collectedSegments.last?.endMs ?? 0
            eventContinuation?.yield(.transcript(LiveTranscriptSegment(
                text: transcript,
                speaker: nil,
                isFinal: false,
                startMs: lastEndMs,
                endMs: lastEndMs,
                confidence: 0.0
            )))

        case "committed_transcript_with_timestamps":
            guard let segment = committedElevenLabsSegment(from: json, textOverride: nil) else { return }
            lastTranscriptReceivedAt = reconnectClock.now
            collectedSegments.append(segment)
            eventContinuation?.yield(.transcript(segment))

        case "committed_transcript":
            guard let segment = committedElevenLabsSegment(
                from: json,
                textOverride: json["text"] as? String
            ) else { return }
            lastTranscriptReceivedAt = reconnectClock.now
            collectedSegments.append(segment)
            eventContinuation?.yield(.transcript(segment))

        default:
            if Self.documentedRealtimeErrorTypes.contains(messageType)
                || messageType.hasSuffix("error")
                || messageType.contains("_error") {
                let message = (json["message"] as? String)
                    ?? (json["error"] as? String)
                    ?? messageType.replacingOccurrences(of: "_", with: " ").capitalized
                let error = WebSocketConnectionError.serverError(message)
                if reconnectEnabled {
                    startReconnection(afterError: error)
                } else {
                    closeConnection(
                        forConnection: connectionId,
                        error: error,
                        emitDisconnected: true,
                        finishEventStream: false
                    )
                }
            }
        }
    }

    private func committedElevenLabsSegment(
        from json: [String: Any],
        textOverride: String?
    ) -> LiveTranscriptSegment? {
        let transcript = (textOverride ?? (json["text"] as? String) ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard !transcript.isEmpty else { return nil }

        let words = (json["words"] as? [[String: Any]] ?? []).filter { word in
            (word["type"] as? String) != "spacing"
        }
        let startMs = Int(((words.first?["start"] as? Double) ?? 0) * 1000)
        let endMs = Int(((words.last?["end"] as? Double) ?? 0) * 1000)
        let confidence = confidenceFromElevenLabsWords(words)

        return LiveTranscriptSegment(
            text: transcript,
            speaker: nil,
            isFinal: true,
            startMs: startMs,
            endMs: endMs,
            confidence: confidence
        )
    }

    private func confidenceFromElevenLabsWords(_ words: [[String: Any]]) -> Double {
        let logprobs: [Double] = words.compactMap { word in
            if let value = word["logprob"] as? Double {
                return value
            }
            if let value = word["logprob"] as? NSNumber {
                return value.doubleValue
            }
            return nil
        }
        guard !logprobs.isEmpty else { return 0.0 }
        let average = logprobs.reduce(0, +) / Double(logprobs.count)
        return max(0.0, min(1.0, 1.0 + (average / 10.0)))
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

        wsLog.info("Starting reconnection (error: \(afterError.localizedDescription, privacy: .public))")
        SentryHelper.addBreadcrumb(
            category: "websocket",
            message: "reconnect started",
            level: .warning,
            data: [
                "bufferedChunks": audioBuffer.count,
                "reason": afterError.localizedDescription,
                "provider": transcriptionSession?.provider ?? "unknown",
            ]
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
                let sessionConfig = try await apiClient.createRealtimeTranscriptionSession(
                    language: language,
                    channels: channels
                )
                transcriptionSession = sessionConfig
                let request = try requestForRealtimeSession(sessionConfig)

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

                // Replay buffered audio
                let bufferedChunks = audioBuffer
                audioBuffer = []
                isReconnecting = false

                wsLog.info(
                    "Reconnected after \(self.reconnectAttempt) attempt(s), replaying \(bufferedChunks.count) audio chunks"
                )

                let reconnectContext = reconnectPreviousText()
                var didSendReplayChunk = false
                for chunk in bufferedChunks {
                    do {
                        try await sendAudioChunk(
                            chunk,
                            previousText: didSendReplayChunk ? nil : reconnectContext
                        )
                        didSendReplayChunk = true
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
            }
        }

        // Max attempts reached
        isReconnecting = false
        wsLog.error("Reconnection failed after \(self.maxReconnectAttempts) attempts")

        let exhaustedError = WebSocketConnectionError.reconnectionExhausted(maxReconnectAttempts)
        SentryHelper.captureError(exhaustedError, extras: ["attempts": maxReconnectAttempts])
        eventContinuation?.yield(.reconnectionFailed(exhaustedError))
    }

    private func reconnectPreviousText() -> String? {
        let fullText = collectedSegments
            .map(\.text)
            .joined(separator: " ")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard !fullText.isEmpty else { return nil }

        // ElevenLabs recommends keeping this short. The tail is the most relevant context.
        return String(fullText.suffix(48))
    }

    private func cancelReconnection() {
        isReconnecting = false
        reconnectTask?.cancel()
        reconnectTask = nil
        audioBuffer = []
    }

    private func ensureEventStream() {
        if _eventStream != nil, eventContinuation != nil {
            return
        }
        let (stream, continuation) = AsyncStream.makeStream(of: WebSocketEvent.self)
        _eventStream = stream
        eventContinuation = continuation
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
        emitDisconnected: Bool,
        finishEventStream: Bool
    ) {
        guard connectionId == expectedId else { return }

        webSocket?.cancel(with: .goingAway, reason: nil)
        webSocket = nil

        receiveTask?.cancel()
        receiveTask = nil
        transcriptionSession = nil

        if emitDisconnected {
            eventContinuation?.yield(.disconnected(error))
        }
        if finishEventStream {
            eventContinuation?.finish()
            eventContinuation = nil
            _eventStream = nil
        }

        sendCount = 0
    }

    func testingYieldEvent(_ event: WebSocketEvent) {
        ensureEventStream()
        eventContinuation?.yield(event)
    }
}
