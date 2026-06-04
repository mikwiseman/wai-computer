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

/// WebSocket manager for Deepgram realtime speech-to-text streaming.
///
/// The manager asks the backend for a short-lived WaiComputer realtime token,
/// then streams provider-configured LINEAR16 PCM audio through the backend
/// Deepgram proxy.
public actor WebSocketManager {
    private let wsLog = Logger(subsystem: "is.waiwai.computer.kit", category: "websocket")
    private let apiClient: APIClient
    private let language: String
    private let channels: Int
    private let purpose: RealtimeTranscriptionPurpose

    private var webSocket: URLSessionWebSocketTask?
    private var eventContinuation: AsyncStream<WebSocketEvent>.Continuation?
    private var receiveTask: Task<Void, Never>?
    private var keepAliveTask: Task<Void, Never>?
    private var connectionId: UInt64 = 0
    private var sendCount = 0
    private var transcriptionSession: RealtimeTranscriptionSessionConfig?
    private let reconnectClock = ContinuousClock()
    private var lastTranscriptReceivedAt: ContinuousClock.Instant?
    private var pendingAudio = Data()
    private var uncommittedAudioBytes = 0
    private var pendingCommitCount = 0
    private var hasSentAudioSinceLastFinalize = false

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
    private var endOfStreamRequested = false
    private var endOfStreamSent = false
    private var providerFinalizationReceived = false

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

    /// Per-session biasing terms (vocabulary words to nudge the recognizer
    /// toward names, jargon, and custom spellings).
    private let keyTerms: [String]

    public init(
        apiClient: APIClient,
        language: String = "multi",
        channels: Int = 1,
        purpose: RealtimeTranscriptionPurpose = .recording,
        keyTerms: [String] = []
    ) {
        self.apiClient = apiClient
        self.language = language
        self.channels = channels
        self.purpose = purpose
        self.keyTerms = keyTerms
    }

    /// Connect to the configured transcription provider using a backend-issued session token.
    public func connect(using providedSessionConfig: RealtimeTranscriptionSessionConfig? = nil) async throws {
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
        pendingAudio = Data()
        uncommittedAudioBytes = 0
        pendingCommitCount = 0
        hasSentAudioSinceLastFinalize = false
        reconnectAttempt = 0
        audioBuffer = []
        isReconnecting = false
        reconnectTask?.cancel()
        reconnectTask = nil
        endOfStreamRequested = false
        endOfStreamSent = false
        providerFinalizationReceived = false

        let sessionConfig = if let providedSessionConfig {
            providedSessionConfig
        } else {
            try await apiClient.createRealtimeTranscriptionSession(
                language: language,
                channels: channels,
                purpose: purpose
            )
        }
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
        startKeepAlive(forConnection: thisConnection, intervalSeconds: sessionConfig.keepAliveIntervalSeconds)

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
                startReconnection(afterError: error)
                return
            }
            throw error
        }
    }

    /// Signal end of audio stream and wait briefly for the final transcript.
    public func sendEnd() async throws {
        endOfStreamRequested = true

        if isReconnecting || webSocket == nil {
            wsLog.debug("Deferring commit chunk until reconnection settles")
            return
        }

        try await sendCommitChunkIfNeeded()
    }

    /// Ask the provider to finalize the stream.
    @discardableResult
    public func finishStreaming(timeout: Duration = .seconds(5)) async throws -> Bool {
        try await sendEnd()
        let startedAt = reconnectClock.now
        let deadline = reconnectClock.now + timeout

        while reconnectClock.now < deadline {
            if endOfStreamRequested && !endOfStreamSent {
                if isReconnecting {
                    try? await Task.sleep(for: .milliseconds(100))
                    continue
                }

                guard webSocket != nil else {
                    break
                }

                try await sendCommitChunkIfNeeded()
                try? await Task.sleep(for: .milliseconds(100))
                continue
            }

            let now = reconnectClock.now
            if !RealtimeCloseDrainPolicy.shouldKeepWaiting(
                now: now,
                deadline: deadline,
                startedAt: startedAt,
                lastTranscriptEventAt: lastTranscriptReceivedAt,
                finalizationMarkerReceived: providerFinalizationReceived
            ) {
                break
            }

            try? await Task.sleep(for: .milliseconds(100))
        }

        let didFinalize = endOfStreamSent && providerFinalizationReceived
        await sendDeepgramCloseStreamIfNeeded()
        disconnect()
        return didFinalize
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

    /// Permanently stop the realtime provider stream for a recording that is
    /// still capturing local audio. This keeps the event stream open for the
    /// caller's eventual `finishStreaming`/`disconnect` cleanup, but makes all
    /// future `sendAudio` calls fail fast so the caller can continue local-only.
    public func stopRealtimeStreamingForLocalRecording(reason: String) {
        reconnectEnabled = false
        cancelReconnection(clearBufferedAudio: true)
        closeConnection(
            forConnection: connectionId,
            error: nil,
            emitDisconnected: false,
            finishEventStream: false
        )
        SentryHelper.addBreadcrumb(
            category: "websocket",
            message: "realtime streaming stopped while local recording continues",
            level: .warning,
            data: ["reason": reason]
        )
    }

    // MARK: - Private

    private func requestForRealtimeSession(
        _ sessionConfig: RealtimeTranscriptionSessionConfig
    ) throws -> URLRequest {
        guard sessionConfig.provider == "deepgram" else {
            throw WebSocketConnectionError.tokenFetchFailed(
                "Unsupported transcription provider: \(sessionConfig.provider)"
            )
        }

        guard let urlString = sessionConfig.websocketURL,
              let url = URL(string: urlString) else {
            throw WebSocketConnectionError.invalidURL
        }
        guard sessionConfig.token.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty == false else {
            throw WebSocketConnectionError.tokenFetchFailed("Deepgram realtime session is missing server-minted token")
        }
        guard sessionConfig.authScheme == "bearer" else {
            throw WebSocketConnectionError.tokenFetchFailed(
                "Unsupported auth scheme for deepgram: \(sessionConfig.authScheme ?? "nil")"
            )
        }
        var request = URLRequest(url: url)
        request.timeoutInterval = 300
        request.setValue("Bearer \(sessionConfig.token)", forHTTPHeaderField: "Authorization")
        return request
    }

    private func sendAudioChunk(_ data: Data) async throws {
        guard webSocket != nil else {
            throw APIError.networkError(URLError(.notConnectedToInternet))
        }

        guard transcriptionSession?.provider == "deepgram" else {
            throw WebSocketConnectionError.tokenFetchFailed(
                "Unsupported transcription provider: \(transcriptionSession?.provider ?? "nil")"
            )
        }
        try await sendDeepgramAudio(data, forceFlush: false)
    }

    /// Serialize a websocket payload to a JSON string.
    ///
    /// These payloads are constructed from statically-typed primitives that are
    /// always JSON-encodable, so failure here would represent a programmer
    /// error introducing a non-encodable type. We force-unwrap to surface that
    /// crash (and the resulting Sentry breadcrumb) instead of silently sending
    /// `"{}"` and corrupting the wire protocol.
    private static func encodeJSONPayload(_ payload: [String: Any]) -> String {
        let jsonData = try! JSONSerialization.data(withJSONObject: payload, options: [])
        return String(data: jsonData, encoding: .utf8)!
    }

    func testingDeepgramFinalizeMessage() -> String {
        Self.encodeJSONPayload(["type": "Finalize"])
    }

    func testingSetSessionConfig(_ sessionConfig: RealtimeTranscriptionSessionConfig) {
        transcriptionSession = sessionConfig
    }

    func testingRequestForRealtimeSession(_ sessionConfig: RealtimeTranscriptionSessionConfig) throws -> URLRequest {
        try requestForRealtimeSession(sessionConfig)
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
                wsLog.error("receiveMessages error for connection \(expectedId)")
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
        handleDeepgramMessage(text)
    }

    private func handleDeepgramMessage(_ text: String) {
        guard let data = text.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return }

        switch json["type"] as? String {
        case "Results":
            handleDeepgramResults(json)
        case "UtteranceEnd":
            lastTranscriptReceivedAt = reconnectClock.now
        case "Metadata":
            if endOfStreamRequested && endOfStreamSent {
                lastTranscriptReceivedAt = reconnectClock.now
                providerFinalizationReceived = true
            }
        case "Error", "error":
            let message = Self.deepgramProviderErrorMessage(json)
            let serverError = WebSocketConnectionError.serverError(message)
            if reconnectEnabled {
                startReconnection(afterError: serverError)
            } else {
                closeConnection(
                    forConnection: connectionId,
                    error: serverError,
                    emitDisconnected: true,
                    finishEventStream: false
                )
            }
        default:
            break
        }
    }

    private func handleDeepgramResults(_ payload: [String: Any]) {
        guard let channel = payload["channel"] as? [String: Any],
              let alternatives = channel["alternatives"] as? [[String: Any]],
              let alternative = alternatives.first
        else { return }
        let isFinal = payload["is_final"] as? Bool ?? false
        let fromFinalize = payload["from_finalize"] as? Bool ?? false
        if fromFinalize || (endOfStreamRequested && endOfStreamSent && isFinal) {
            lastTranscriptReceivedAt = reconnectClock.now
            providerFinalizationReceived = true
        }

        let transcript = (alternative["transcript"] as? String ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard !transcript.isEmpty else { return }

        let startMs = Self.secondsToMilliseconds(payload["start"] as? Double)
        let durationMs = Self.secondsToMilliseconds(payload["duration"] as? Double)
        let confidence = alternative["confidence"] as? Double ?? 0
        lastTranscriptReceivedAt = reconnectClock.now

        let segment = LiveTranscriptSegment(
            text: transcript,
            speaker: DeepgramSpeakerLabel.dominant(in: alternative),
            isFinal: isFinal,
            startMs: startMs,
            endMs: startMs + durationMs,
            confidence: confidence
        )
        if isFinal, let emittedSegment = collectCommittedSegment(segment) {
            eventContinuation?.yield(.transcript(emittedSegment))
        } else if !isFinal {
            eventContinuation?.yield(.transcript(segment))
        }
    }

    private static func secondsToMilliseconds(_ seconds: Double?) -> Int {
        guard let seconds else { return 0 }
        return Int((seconds * 1_000).rounded())
    }

    private static func deepgramProviderErrorMessage(_ payload: [String: Any]) -> String {
        if let message = payload["message"] as? String {
            return message
        }
        if let error = payload["error"] as? String {
            return error
        }
        if let error = payload["error"] as? [String: Any] {
            return error["message"] as? String
                ?? error["description"] as? String
                ?? error["reason"] as? String
                ?? "Deepgram realtime transcription error"
        }
        return payload["description"] as? String
            ?? payload["reason"] as? String
            ?? "Deepgram realtime transcription error"
    }

    private func collectCommittedSegment(_ segment: LiveTranscriptSegment) -> LiveTranscriptSegment? {
        if let last = collectedSegments.last,
           normalizedTranscriptText(last.text) == normalizedTranscriptText(segment.text) {
            return nil
        }

        collectedSegments.append(segment)
        return segment
    }

    private func normalizedTranscriptText(_ text: String) -> String {
        text
            .split(whereSeparator: \.isWhitespace)
            .joined(separator: " ")
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    // MARK: - Reconnection

    private func startReconnection(afterError: Error) {
        guard reconnectEnabled, !isReconnecting else { return }

        isReconnecting = true

        // Clean up current socket without finishing the event continuation
        keepAliveTask?.cancel()
        keepAliveTask = nil
        webSocket?.cancel(with: .goingAway, reason: nil)
        webSocket = nil
        receiveTask?.cancel()
        receiveTask = nil

        wsLog.info("Starting reconnection after stream error \(type(of: afterError), privacy: .public)")
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
                    channels: channels,
                    purpose: purpose
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
                startKeepAlive(
                    forConnection: thisConnection,
                    intervalSeconds: sessionConfig.keepAliveIntervalSeconds
                )

                // Replay buffered audio
                let bufferedChunks = audioBuffer
                audioBuffer = []
                isReconnecting = false

                wsLog.info(
                    "Reconnected after \(self.reconnectAttempt) attempt(s), replaying \(bufferedChunks.count) audio chunks"
                )

                for chunk in bufferedChunks {
                    do {
                        try await sendAudioChunk(chunk)
                    } catch {
                        wsLog.error("Failed to replay buffered audio chunk")
                        // New connection is also broken — receiveMessages will trigger another reconnection
                        break
                    }
                }

                try await sendCommitChunkIfNeeded()

                eventContinuation?.yield(.reconnected)
                return // Success

            } catch {
                wsLog.error("Reconnect attempt \(self.reconnectAttempt) failed")
                // Clean up failed connection attempt
                keepAliveTask?.cancel()
                keepAliveTask = nil
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

    private func sendCommitChunkIfNeeded() async throws {
        guard endOfStreamRequested, !endOfStreamSent else { return }
        guard let webSocket else { return }
        guard transcriptionSession?.provider == "deepgram" else {
            throw WebSocketConnectionError.tokenFetchFailed(
                "Unsupported transcription provider: \(transcriptionSession?.provider ?? "nil")"
            )
        }

        try await flushDeepgramPendingAudio()
        if hasSentAudioSinceLastFinalize {
            try await sendDeepgramFinalize(to: webSocket)
        } else {
            providerFinalizationReceived = true
        }
        endOfStreamSent = true
        reconnectEnabled = false
        cancelReconnection(clearBufferedAudio: false)
        wsLog.debug("Sent Deepgram Finalize")
    }

    private func cancelReconnection(clearBufferedAudio: Bool = true) {
        isReconnecting = false
        reconnectTask?.cancel()
        reconnectTask = nil
        if clearBufferedAudio {
            audioBuffer = []
            pendingAudio = Data()
            uncommittedAudioBytes = 0
            hasSentAudioSinceLastFinalize = false
        }
    }

    private func sendDeepgramAudio(_ data: Data, forceFlush: Bool) async throws {
        guard let webSocket else {
            throw APIError.networkError(URLError(.notConnectedToInternet))
        }
        let config = transcriptionSession
        for chunk in Self.pcmAudioChunks(
            pending: &pendingAudio,
            appending: data,
            forceFlush: forceFlush,
            sampleRate: config?.sampleRate ?? 16_000,
            channels: config?.channels ?? 1
        ) where !chunk.isEmpty {
            try await webSocket.send(.data(chunk))
            uncommittedAudioBytes += chunk.count
            hasSentAudioSinceLastFinalize = true
        }
    }

    private func flushDeepgramPendingAudio() async throws {
        guard !pendingAudio.isEmpty else { return }
        try await sendDeepgramAudio(Data(), forceFlush: true)
    }

    private func sendDeepgramFinalize(to webSocket: URLSessionWebSocketTask) async throws {
        try await webSocket.send(.string(Self.encodeJSONPayload(["type": "Finalize"])))
    }

    private func sendDeepgramCloseStreamIfNeeded() async {
        guard let webSocket else { return }
        try? await webSocket.send(.string(Self.encodeJSONPayload(["type": "CloseStream"])))
    }

    private func startKeepAlive(forConnection expectedId: UInt64, intervalSeconds: Int?) {
        keepAliveTask?.cancel()
        guard let intervalSeconds, intervalSeconds > 0 else { return }
        keepAliveTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(intervalSeconds))
                guard !Task.isCancelled else { return }
                await self?.sendKeepAliveIfCurrentConnection(expectedId)
            }
        }
    }

    private func sendKeepAliveIfCurrentConnection(_ expectedId: UInt64) async {
        guard connectionId == expectedId, let webSocket else { return }
        try? await webSocket.send(.string(Self.encodeJSONPayload(["type": "KeepAlive"])))
    }

    static func pcmAudioChunks(
        pending: inout Data,
        appending data: Data,
        forceFlush: Bool,
        sampleRate: Int,
        channels: Int
    ) -> [Data] {
        if !data.isEmpty {
            pending.append(data)
        }

        let bytesPerSecond = max(1, sampleRate) * max(1, channels) * 2
        let minChunkBytes = max(1, bytesPerSecond * 20 / 1_000)
        let maxChunkBytes = bytesPerSecond

        var chunks: [Data] = []
        while pending.count >= maxChunkBytes {
            chunks.append(Data(pending.prefix(maxChunkBytes)))
            pending.removeFirst(maxChunkBytes)
        }

        if forceFlush {
            guard !pending.isEmpty else { return chunks }
            var chunk = pending
            pending.removeAll(keepingCapacity: true)
            if chunk.count < minChunkBytes {
                chunk.append(Data(repeating: 0, count: minChunkBytes - chunk.count))
            }
            chunks.append(chunk)
        } else if pending.count >= minChunkBytes {
            chunks.append(pending)
            pending = Data()
        }

        return chunks
    }

    private func ensureEventStream() {
        if _eventStream != nil, eventContinuation != nil {
            return
        }
        let (stream, continuation) = AsyncStream.makeStream(
            of: WebSocketEvent.self,
            bufferingPolicy: .bufferingNewest(256)
        )
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

    func testingSetReconnectState(enabled: Bool, reconnecting: Bool) {
        reconnectEnabled = enabled
        isReconnecting = reconnecting
    }

    func testingSetEndOfStreamState(requested: Bool, sent: Bool) {
        endOfStreamRequested = requested
        endOfStreamSent = sent
    }

    func testingEndOfStreamRequested() -> Bool {
        endOfStreamRequested
    }

    func testingHandleDeepgramMessage(_ text: String) {
        handleDeepgramMessage(text)
    }

    func testingProviderFinalizationReceived() -> Bool {
        providerFinalizationReceived
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

        keepAliveTask?.cancel()
        keepAliveTask = nil
        receiveTask?.cancel()
        receiveTask = nil
        transcriptionSession = nil
        pendingAudio = Data()
        uncommittedAudioBytes = 0
        pendingCommitCount = 0
        hasSentAudioSinceLastFinalize = false

        if emitDisconnected {
            eventContinuation?.yield(.disconnected(error))
        }
        if finishEventStream {
            eventContinuation?.finish()
            eventContinuation = nil
            _eventStream = nil
        }

        sendCount = 0
        endOfStreamRequested = false
        endOfStreamSent = false
        providerFinalizationReceived = false
    }

    func testingYieldEvent(_ event: WebSocketEvent) {
        ensureEventStream()
        eventContinuation?.yield(event)
    }

    func testingPCMAudioChunks(
        pending: inout Data,
        appending data: Data,
        forceFlush: Bool,
        sampleRate: Int = 16_000,
        channels: Int = 1
    ) -> [Data] {
        Self.pcmAudioChunks(
            pending: &pending,
            appending: data,
            forceFlush: forceFlush,
            sampleRate: sampleRate,
            channels: channels
        )
    }
}
