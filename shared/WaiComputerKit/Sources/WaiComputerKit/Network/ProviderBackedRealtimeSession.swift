import Foundation
import os

private let providerRealtimeLog = Logger(subsystem: "is.waiwai.computer.kit", category: "providerRealtime")

public actor ProviderBackedRealtimeSession: ProviderSession {
    public nonisolated let events: AsyncStream<TranscriptionEvent>

    private let eventContinuation: AsyncStream<TranscriptionEvent>.Continuation
    private let config: RealtimeTranscriptionSessionConfig
    private let urlSession: URLSession

    private var webSocket: URLSessionWebSocketTask?
    private var receiveTask: Task<Void, Never>?
    private var collectedSegments: [LiveTranscriptSegment] = []
    private var pendingAudio = Data()
    private var uncommittedAudioBytes = 0
    private var pendingCommitCount = 0
    private var transcriptByItemID: [String: String] = [:]
    private var isClosing = false
    private var didSendEndTurn = false
    private var lastTranscriptEventAt: ContinuousClock.Instant?
    private var finalizationMarkerReceived = false

    public init(
        config: RealtimeTranscriptionSessionConfig,
        keyTerms: [String] = [],
        urlSession: URLSession = .shared
    ) {
        self.config = config
        self.urlSession = urlSession
        let (stream, continuation) = AsyncStream.makeStream(
            of: TranscriptionEvent.self,
            bufferingPolicy: .bufferingNewest(256)
        )
        self.events = stream
        self.eventContinuation = continuation

        if !keyTerms.isEmpty {
            providerRealtimeLog.info(
                "[OpenAI] key terms ignored for gpt-realtime-whisper count=\(keyTerms.count, privacy: .public)"
            )
        }
    }

    public func open() async throws {
        guard webSocket == nil else { return }
        let request = try makeRequest()
        let task = urlSession.webSocketTask(with: request)
        webSocket = task
        task.resume()
        startReceiveLoop(for: task)

        try await task.send(.string(Self.encodeJSON(openAISessionUpdatePayload())))
        eventContinuation.yield(.opened(sessionId: "openai"))
    }

    public func send(pcm16: Data) async throws {
        guard let webSocket else {
            throw ProviderError.transcriberInternal(message: "OpenAI realtime socket is not open")
        }
        for chunk in Self.pcmAudioChunks(
            pending: &pendingAudio,
            appending: pcm16,
            forceFlush: false,
            sampleRate: config.sampleRate,
            channels: config.channels
        ) {
            try await webSocket.send(.string(Self.encodeJSON([
                "type": "input_audio_buffer.append",
                "audio": chunk.base64EncodedString(),
            ])))
            uncommittedAudioBytes += chunk.count
            if shouldAutoCommitAudio() {
                try await commitAudioBuffer(to: webSocket)
            }
        }
    }

    public func endTurn() async throws {
        guard !didSendEndTurn, let webSocket else { return }
        didSendEndTurn = true
        try await flushPendingAudio(to: webSocket)
        if uncommittedAudioBytes > 0 {
            try await commitAudioBuffer(to: webSocket)
        } else if pendingCommitCount == 0 {
            finalizationMarkerReceived = true
        }
    }

    public func close(timeout: Duration = .seconds(5)) async throws -> [LiveTranscriptSegment] {
        guard !isClosing else { return collectedSegments }
        isClosing = true
        guard webSocket != nil else {
            eventContinuation.finish()
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

        webSocket?.cancel(with: .normalClosure, reason: nil)
        receiveTask?.cancel()
        eventContinuation.yield(.closed(reason: .clientRequested))
        eventContinuation.finish()
        return collectedSegments
    }

    public func cancel() async {
        guard !isClosing else { return }
        isClosing = true
        pendingAudio = Data()
        uncommittedAudioBytes = 0
        pendingCommitCount = 0
        webSocket?.cancel(with: .goingAway, reason: nil)
        receiveTask?.cancel()
        eventContinuation.yield(.closed(reason: .clientRequested))
        eventContinuation.finish()
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

        guard config.provider == "openai" else {
            throw ProviderError.unsupportedModel(config.provider)
        }
        guard websocketURL?.isEmpty == false else {
            throw ProviderError.transcriberInternal(message: "OpenAI realtime session is missing server-minted websocket URL")
        }
        guard !token.isEmpty else {
            throw ProviderError.transcriberInternal(message: "OpenAI realtime session is missing server-minted token")
        }
        guard config.authScheme == "bearer" else {
            throw ProviderError.transcriberInternal(message: "OpenAI realtime session has unsupported auth scheme: \(config.authScheme ?? "nil")")
        }
    }

    private func flushPendingAudio(to webSocket: URLSessionWebSocketTask) async throws {
        for chunk in Self.pcmAudioChunks(
            pending: &pendingAudio,
            appending: Data(),
            forceFlush: true,
            sampleRate: config.sampleRate,
            channels: config.channels
        ) {
            try await webSocket.send(.string(Self.encodeJSON([
                "type": "input_audio_buffer.append",
                "audio": chunk.base64EncodedString(),
            ])))
            uncommittedAudioBytes += chunk.count
        }
    }

    private func shouldAutoCommitAudio() -> Bool {
        uncommittedAudioBytes >= openAIAutoCommitBytes()
    }

    private func openAIAutoCommitBytes() -> Int {
        max(1, config.sampleRate) * max(1, config.channels) * 2
    }

    private func commitAudioBuffer(to webSocket: URLSessionWebSocketTask) async throws {
        guard uncommittedAudioBytes > 0 else { return }
        try await webSocket.send(.string(Self.encodeJSON(["type": "input_audio_buffer.commit"])))
        uncommittedAudioBytes = 0
        pendingCommitCount += 1
    }

    private func openAISessionUpdatePayload() -> [String: Any] {
        var transcription: [String: Any] = ["model": config.model]
        if let language = normalisedProviderLanguage(config.language) {
            transcription["language"] = language
        }

        return [
            "type": "session.update",
            "session": [
                "type": "transcription",
                "audio": [
                    "input": [
                        "format": [
                            "type": "audio/pcm",
                            "rate": config.sampleRate,
                        ],
                        "transcription": transcription,
                        "turn_detection": NSNull(),
                    ],
                ],
            ],
        ]
    }

    private func normalisedProviderLanguage(_ language: String) -> String? {
        switch language {
        case "multi", "und", "":
            return nil
        case let other where other.contains("-"):
            return String(other.split(separator: "-").first ?? Substring(other))
        default:
            return language
        }
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

        handleOpenAI(json)
    }

    private func handleOpenAI(_ json: [String: Any]) {
        let type = json["type"] as? String
        switch type {
        case "conversation.item.input_audio_transcription.delta":
            handleOpenAIDelta(json)
        case "conversation.item.input_audio_transcription.completed":
            handleOpenAICompleted(json)
        case "error":
            eventContinuation.yield(.providerWarning(Self.openAIProviderError(json["error"])))
        default:
            break
        }
    }

    private func handleOpenAIDelta(_ payload: [String: Any]) {
        let delta = payload["delta"] as? String ?? ""
        guard !delta.isEmpty else { return }
        let itemID = payload["item_id"] as? String ?? "default"
        let transcript = (transcriptByItemID[itemID] ?? "") + delta
        transcriptByItemID[itemID] = transcript
        markTranscriptEvent()
        let displayText = transcript.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !displayText.isEmpty else { return }
        eventContinuation.yield(.interim(text: displayText, language: nil))
    }

    private func handleOpenAICompleted(_ payload: [String: Any]) {
        let itemID = payload["item_id"] as? String ?? "default"
        let transcript = ((payload["transcript"] as? String) ?? transcriptByItemID[itemID] ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        transcriptByItemID[itemID] = nil
        if pendingCommitCount > 0 {
            pendingCommitCount -= 1
        }
        if didSendEndTurn && pendingCommitCount == 0 {
            finalizationMarkerReceived = true
        }
        guard !transcript.isEmpty else { return }
        appendFinal(
            text: transcript,
            speaker: nil,
            startMs: nil,
            endMs: nil,
            confidence: 0
        )
        markTranscriptEvent()
    }

    private func appendFinal(_ segment: LiveTranscriptSegment) {
        collectedSegments.append(segment)
        markTranscriptEvent()
        eventContinuation.yield(.committed(segment))
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
        markTranscriptEvent()
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

    private static func openAIProviderError(_ value: Any?) -> ProviderError {
        let payload = value as? [String: Any]
        let code = (payload?["code"] as? String)?.lowercased()
            ?? (payload?["type"] as? String)?.lowercased()
            ?? "unknown"
        let message = payload?["message"] as? String
        switch code {
        case "invalid_api_key", "authentication_error", "unauthorized":
            return .authError(server: message)
        case "insufficient_quota", "billing_hard_limit_reached":
            return .quotaExceeded
        case "rate_limit_exceeded":
            return .rateLimited(retryAfterMs: nil)
        case "unsupported_model":
            return .unsupportedModel(message ?? "")
        default:
            return .transcriberInternal(message: message ?? code)
        }
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

    func testingHandleOpenAIMessage(_ text: String) {
        guard let data = text.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return }
        handleOpenAI(json)
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

    func testingOpenAISessionUpdatePayload() -> [String: Any] {
        openAISessionUpdatePayload()
    }

    func testingRequest() throws -> URLRequest {
        try makeRequest()
    }
}
