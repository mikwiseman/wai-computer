import Foundation
import os

private let providerRealtimeLog = Logger(subsystem: "is.waiwai.computer.kit", category: "providerRealtime")

public actor ProviderBackedRealtimeSession: ProviderSession {
    public nonisolated let events: AsyncStream<TranscriptionEvent>

    private let eventContinuation: AsyncStream<TranscriptionEvent>.Continuation
    private let config: RealtimeTranscriptionSessionConfig
    private let urlSession: URLSession
    /// `nil` only when the caller supplied a pre-made URLSession (legacy path
    /// / tests). When we own the session ourselves we keep the delegate so
    /// `open()` can `await` a real handshake-complete signal instead of
    /// returning optimistically right after `task.resume()`.
    private let handshakeCoordinator: WebSocketHandshakeCoordinator?
    private let ownsURLSession: Bool

    private var webSocket: URLSessionWebSocketTask?
    private var receiveTask: Task<Void, Never>?
    private var keepAliveTask: Task<Void, Never>?
    private var collectedSegments: [LiveTranscriptSegment] = []
    private var pendingAudio = Data()
    private var hasSentAudioSinceLastFinalize = false
    private var isClosing = false
    private var didSendEndTurn = false
    private var lastTranscriptEventAt: ContinuousClock.Instant?
    private var finalizationMarkerReceived = false
    /// How long `open()` will wait for the handshake before throwing.
    /// Long enough to absorb cold proxy boot + TLS + WS upgrade, short
    /// enough that a wedged proxy doesn't freeze the dictation overlay.
    private static let handshakeTimeout: Duration = .seconds(10)

    public init(
        config: RealtimeTranscriptionSessionConfig,
        keyTerms: [String] = []
    ) {
        self.config = config
        let coordinator = WebSocketHandshakeCoordinator()
        let sessionConfig = URLSessionConfiguration.ephemeral
        sessionConfig.waitsForConnectivity = false
        sessionConfig.timeoutIntervalForRequest = 30
        sessionConfig.timeoutIntervalForResource = 3600
        // Dedicated session — isolates the realtime WS from Sparkle's
        // appcast pollers, downloaders, and anything else that uses
        // `URLSession.shared`, all of which can intermittently stall the
        // handshake under load.
        self.urlSession = URLSession(
            configuration: sessionConfig,
            delegate: coordinator,
            delegateQueue: nil
        )
        self.handshakeCoordinator = coordinator
        self.ownsURLSession = true
        let (stream, continuation) = AsyncStream.makeStream(
            of: TranscriptionEvent.self,
            bufferingPolicy: .bufferingNewest(256)
        )
        self.events = stream
        self.eventContinuation = continuation

        if !keyTerms.isEmpty {
            providerRealtimeLog.info(
                "[Deepgram] key terms require a server-minted URL; ignored count=\(keyTerms.count, privacy: .public)"
            )
        }
    }

    /// Legacy init kept for tests that inject a custom URLSession (e.g.
    /// URLProtocol-mocked sessions). Skips handshake waiting because the
    /// supplied session has no delegate hook.
    public init(
        config: RealtimeTranscriptionSessionConfig,
        keyTerms: [String],
        urlSession: URLSession
    ) {
        self.config = config
        self.urlSession = urlSession
        self.handshakeCoordinator = nil
        self.ownsURLSession = false
        let (stream, continuation) = AsyncStream.makeStream(
            of: TranscriptionEvent.self,
            bufferingPolicy: .bufferingNewest(256)
        )
        self.events = stream
        self.eventContinuation = continuation

        if !keyTerms.isEmpty {
            providerRealtimeLog.info(
                "[Deepgram] key terms require a server-minted URL; ignored count=\(keyTerms.count, privacy: .public)"
            )
        }
    }

    public func open() async throws {
        guard webSocket == nil else { return }
        let request = try makeRequest()
        let task = urlSession.webSocketTask(with: request)
        webSocket = task
        task.resume()

        // Wait for the WS upgrade to actually complete. Without this, open()
        // returns immediately and any close that arrives during the
        // handshake window (proxy 1008/1011 on bad token, network hiccup,
        // upstream failure) gets dropped by call-site guards that only act
        // when state is already .listening — that was the dominant cause
        // of the "dictation starts then immediately stops" symptom.
        if let coordinator = handshakeCoordinator {
            do {
                try await Self.awaitHandshake(
                    coordinator: coordinator,
                    task: task,
                    timeout: Self.handshakeTimeout
                )
            } catch {
                task.cancel(with: .goingAway, reason: nil)
                webSocket = nil
                throw error
            }
        }

        startReceiveLoop(for: task)
        startKeepAlive(intervalSeconds: config.keepAliveIntervalSeconds)
        eventContinuation.yield(.opened(sessionId: "deepgram"))
    }

    private static func awaitHandshake(
        coordinator: WebSocketHandshakeCoordinator,
        task: URLSessionWebSocketTask,
        timeout: Duration
    ) async throws {
        try await withThrowingTaskGroup(of: Void.self) { group in
            group.addTask {
                try await coordinator.waitForOpen(task: task)
            }
            group.addTask {
                try await Task.sleep(for: timeout)
                throw WebSocketHandshakeCoordinator.HandshakeError.timedOut
            }
            do {
                try await group.next()
                group.cancelAll()
                // Drop the second awaiter so the coordinator isn't left
                // holding a leaked continuation reference.
                coordinator.cancelPending(for: task)
            } catch {
                group.cancelAll()
                coordinator.cancelPending(for: task)
                throw error
            }
        }
    }

    public func send(pcm16: Data) async throws {
        guard let webSocket else {
            throw ProviderError.transcriberInternal(message: "Deepgram realtime socket is not open")
        }
        for chunk in Self.pcmAudioChunks(
            pending: &pendingAudio,
            appending: pcm16,
            forceFlush: false,
            sampleRate: config.sampleRate,
            channels: config.channels
        ) where !chunk.isEmpty {
            try await webSocket.send(.data(chunk))
            hasSentAudioSinceLastFinalize = true
        }
    }

    public func endTurn() async throws {
        guard !didSendEndTurn, let webSocket else { return }
        didSendEndTurn = true
        try await flushPendingAudio()
        if hasSentAudioSinceLastFinalize {
            try await webSocket.send(.string(Self.encodeJSON(["type": "Finalize"])))
        } else {
            finalizationMarkerReceived = true
        }
    }

    public func close(timeout: Duration = .seconds(5)) async throws -> [LiveTranscriptSegment] {
        guard !isClosing else { return collectedSegments }
        isClosing = true
        guard let webSocket else {
            eventContinuation.finish()
            invalidateOwnedURLSession()
            return collectedSegments
        }
        try? await endTurn()

        let clock = ContinuousClock()
        let startedAt = clock.now
        let deadline = startedAt + timeout
        while RealtimeCloseDrainPolicy.shouldKeepWaiting(
            now: clock.now,
            deadline: deadline,
            startedAt: startedAt,
            lastTranscriptEventAt: lastTranscriptEventAt,
            finalizationMarkerReceived: finalizationMarkerReceived
        ) {
            try? await Task.sleep(for: .milliseconds(50))
        }

        try? await webSocket.send(.string(Self.encodeJSON(["type": "CloseStream"])))
        keepAliveTask?.cancel()
        webSocket.cancel(with: .normalClosure, reason: nil)
        receiveTask?.cancel()
        eventContinuation.yield(.closed(reason: .clientRequested))
        eventContinuation.finish()
        invalidateOwnedURLSession()
        return collectedSegments
    }

    public func cancel() async {
        guard !isClosing else { return }
        isClosing = true
        pendingAudio = Data()
        hasSentAudioSinceLastFinalize = false
        keepAliveTask?.cancel()
        webSocket?.cancel(with: .goingAway, reason: nil)
        receiveTask?.cancel()
        eventContinuation.yield(.closed(reason: .clientRequested))
        eventContinuation.finish()
        invalidateOwnedURLSession()
    }

    /// Break the retain cycle that URLSession holds on its delegate. Only
    /// invalidate sessions we own — the legacy init lets callers manage
    /// session lifecycle themselves.
    private func invalidateOwnedURLSession() {
        guard ownsURLSession else { return }
        urlSession.invalidateAndCancel()
    }

    private func makeRequest() throws -> URLRequest {
        try validateServerMintedRouting()

        guard let urlString = config.websocketURL,
              let url = URL(string: urlString) else {
            throw WebSocketConnectionError.invalidURL
        }

        var request = URLRequest(url: url)
        request.timeoutInterval = 30
        request.setValue("Bearer \(config.token)", forHTTPHeaderField: "Authorization")
        return request
    }

    private func validateServerMintedRouting() throws {
        let token = config.token.trimmingCharacters(in: .whitespacesAndNewlines)
        let websocketURL = config.websocketURL?.trimmingCharacters(in: .whitespacesAndNewlines)

        guard config.provider == "deepgram" else {
            throw ProviderError.unsupportedModel(config.provider)
        }
        guard websocketURL?.isEmpty == false else {
            throw ProviderError.transcriberInternal(message: "Deepgram realtime session is missing server-minted websocket URL")
        }
        guard !token.isEmpty else {
            throw ProviderError.transcriberInternal(message: "Deepgram realtime session is missing server-minted token")
        }
        guard config.authScheme == "bearer" else {
            throw ProviderError.transcriberInternal(message: "Deepgram realtime session has unsupported auth scheme: \(config.authScheme ?? "nil")")
        }
    }

    private func flushPendingAudio() async throws {
        guard !pendingAudio.isEmpty, let webSocket else { return }
        for chunk in Self.pcmAudioChunks(
            pending: &pendingAudio,
            appending: Data(),
            forceFlush: true,
            sampleRate: config.sampleRate,
            channels: config.channels
        ) where !chunk.isEmpty {
            try await webSocket.send(.data(chunk))
            hasSentAudioSinceLastFinalize = true
        }
    }

    private func startKeepAlive(intervalSeconds: Int?) {
        keepAliveTask?.cancel()
        guard let intervalSeconds, intervalSeconds > 0 else { return }
        keepAliveTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(intervalSeconds))
                guard !Task.isCancelled else { return }
                await self?.sendKeepAlive()
            }
        }
    }

    private func sendKeepAlive() async {
        guard let webSocket else { return }
        try? await webSocket.send(.string(Self.encodeJSON(["type": "KeepAlive"])))
    }

    private func startReceiveLoop(for task: URLSessionWebSocketTask) {
        receiveTask = Task { [weak self] in
            guard let self else { return }
            while !Task.isCancelled {
                do {
                    let message = try await task.receive()
                    if Task.isCancelled { break }
                    await self.handle(message)
                } catch {
                    if Task.isCancelled { break }
                    await self.handleSocketError(error)
                    break
                }
            }
        }
    }

    private func handle(_ message: URLSessionWebSocketTask.Message) {
        switch message {
        case .string(let text):
            handleText(text)
        case .data(let data):
            if let text = String(data: data, encoding: .utf8) {
                handleText(text)
            }
        @unknown default:
            break
        }
    }

    private func handleText(_ text: String) {
        guard let data = text.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return }

        handleDeepgram(json)
    }

    private func handleDeepgram(_ json: [String: Any]) {
        switch json["type"] as? String {
        case "Results":
            handleDeepgramResults(json)
        case "UtteranceEnd":
            markTranscriptEvent()
        case "Metadata":
            // Deepgram emits a Metadata frame at connection start (model
            // echo, sample_rate echo) and another after the finalize round
            // trip. The connect-time Metadata is NOT a finalization marker —
            // treating it as one short-circuits the close-drain loop and
            // can drop the real final Results frame. Only mark as
            // finalization after we've actually sent end-turn.
            markTranscriptEvent(finalizationMarker: didSendEndTurn)
        case "Error", "error":
            eventContinuation.yield(.providerWarning(Self.deepgramProviderError(json)))
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
        if fromFinalize || (didSendEndTurn && isFinal) {
            markTranscriptEvent(finalizationMarker: true)
        }

        let transcript = (alternative["transcript"] as? String ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard !transcript.isEmpty else { return }

        let startMs = Self.secondsToMilliseconds(payload["start"] as? Double)
        let durationMs = Self.secondsToMilliseconds(payload["duration"] as? Double)
        let confidence = alternative["confidence"] as? Double ?? 0
        if !fromFinalize && !(didSendEndTurn && isFinal) {
            markTranscriptEvent()
        }

        if isFinal {
            appendFinal(
                text: transcript,
                speaker: DeepgramSpeakerLabel.dominant(in: alternative),
                startMs: startMs,
                endMs: startMs + durationMs,
                confidence: confidence
            )
        } else {
            eventContinuation.yield(.interim(text: transcript, language: config.language))
        }
    }

    // Legacy entry-point kept so existing tests in
    // ProviderBackedRealtimeSessionTests still compile. Forwards to the shared
    // DeepgramSpeakerLabel helper used by WebSocketManager as well.
    static func dominantSpeakerLabel(in alternative: [String: Any]) -> String? {
        DeepgramSpeakerLabel.dominant(in: alternative)
    }

    private func appendFinal(
        text: String,
        speaker: String?,
        startMs: Int?,
        endMs: Int?,
        confidence: Double
    ) {
        let transcript = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !transcript.isEmpty else { return }
        if let last = collectedSegments.last,
           Self.normalizedTranscriptText(last.text) == Self.normalizedTranscriptText(transcript) {
            return
        }
        let fallbackStart = collectedSegments.last?.endMs ?? 0
        let segment = LiveTranscriptSegment(
            text: transcript,
            speaker: speaker,
            isFinal: true,
            startMs: startMs ?? fallbackStart,
            endMs: endMs ?? startMs ?? fallbackStart,
            confidence: confidence
        )
        collectedSegments.append(segment)
        eventContinuation.yield(.committed(segment))
    }

    private func markTranscriptEvent(finalizationMarker: Bool = false) {
        lastTranscriptEventAt = ContinuousClock().now
        if finalizationMarker {
            finalizationMarkerReceived = true
        }
    }

    private func handleSocketError(_ error: Error) {
        providerRealtimeLog.error("[\(self.config.provider, privacy: .public)] WebSocket error: \(error.localizedDescription, privacy: .public)")
        eventContinuation.yield(.closed(reason: .networkLost))
        eventContinuation.finish()
    }

    private static func deepgramProviderError(_ payload: [String: Any]) -> ProviderError {
        let code = (payload["error"] as? String)?.lowercased()
            ?? (payload["err_code"] as? String)?.lowercased()
            ?? (payload["type"] as? String)?.lowercased()
            ?? "unknown"
        let message = payload["message"] as? String
            ?? payload["description"] as? String
            ?? payload["reason"] as? String
        switch code {
        case "invalid_api_key", "authentication_error", "unauthorized", "forbidden":
            return .authError(server: message)
        case "insufficient_quota", "billing_hard_limit_reached":
            return .quotaExceeded
        case "rate_limit_exceeded", "too_many_requests":
            return .rateLimited(retryAfterMs: nil)
        case "unsupported_model":
            return .unsupportedModel(message ?? "")
        default:
            return .transcriberInternal(message: message ?? code)
        }
    }

    private static func secondsToMilliseconds(_ seconds: Double?) -> Int {
        guard let seconds else { return 0 }
        return Int((seconds * 1_000).rounded())
    }

    private static func normalizedTranscriptText(_ text: String) -> String {
        text
            .split(whereSeparator: \.isWhitespace)
            .joined(separator: " ")
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    static func encodeJSON(_ payload: [String: Any]) -> String {
        let data = try! JSONSerialization.data(withJSONObject: payload, options: [])
        return String(data: data, encoding: .utf8)!
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

    func testingHandleDeepgramMessage(_ text: String) {
        guard let data = text.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return }
        handleDeepgram(json)
    }

    func testingCollectedSegments() -> [LiveTranscriptSegment] {
        collectedSegments
    }

    func testingHasTranscriptActivity() -> Bool {
        lastTranscriptEventAt != nil
    }

    func testingHasFinalizationMarker() -> Bool {
        finalizationMarkerReceived
    }

    func testingSetDidSendEndTurn(_ value: Bool) {
        didSendEndTurn = value
    }

    func testingDeepgramFinalizePayload() -> [String: Any] {
        ["type": "Finalize"]
    }

    func testingRequest() throws -> URLRequest {
        try makeRequest()
    }
}
