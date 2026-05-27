import Foundation
import os

private let providerRealtimeLog = Logger(subsystem: "is.waiwai.computer.kit", category: "providerRealtime")

public actor ProviderBackedRealtimeSession: ProviderSession {
    public nonisolated let events: AsyncStream<TranscriptionEvent>

    private let eventContinuation: AsyncStream<TranscriptionEvent>.Continuation
    private let config: RealtimeTranscriptionSessionConfig
    private let keyTerms: [String]
    private let urlSession: URLSession

    private var webSocket: URLSessionWebSocketTask?
    private var receiveTask: Task<Void, Never>?
    private var collectedSegments: [LiveTranscriptSegment] = []
    private var inworldPendingAudio = Data()
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
        self.keyTerms = keyTerms
        self.urlSession = urlSession
        let (stream, continuation) = AsyncStream.makeStream(
            of: TranscriptionEvent.self,
            bufferingPolicy: .bufferingNewest(256)
        )
        self.events = stream
        self.eventContinuation = continuation
    }

    public func open() async throws {
        guard webSocket == nil else { return }
        let request = try makeRequest()
        let task = urlSession.webSocketTask(with: request)
        webSocket = task
        task.resume()
        startReceiveLoop(for: task)

        try await task.send(.string(Self.encodeJSON(inworldTranscribeConfigPayload())))
        eventContinuation.yield(.opened(sessionId: "inworld"))
    }

    public func send(pcm16: Data) async throws {
        guard let webSocket else {
            throw ProviderError.transcriberInternal(message: "Inworld socket is not open")
        }
        for chunk in Self.inworldAudioChunks(
            pending: &inworldPendingAudio,
            appending: pcm16,
            forceFlush: false,
            sampleRate: config.sampleRate,
            channels: config.channels
        ) {
            try await webSocket.send(.string(Self.encodeJSON([
                "audioChunk": ["content": chunk.base64EncodedString()]
            ])))
        }
    }

    public func endTurn() async throws {
        guard !didSendEndTurn, let webSocket else { return }
        didSendEndTurn = true
        try await flushInworldPendingAudio(to: webSocket)
        try await webSocket.send(.string(Self.encodeJSON(["endTurn": [String: Any]()])))
    }

    public func close(timeout: Duration = .seconds(5)) async throws -> [LiveTranscriptSegment] {
        guard !isClosing else { return collectedSegments }
        isClosing = true
        guard webSocket != nil else {
            eventContinuation.finish()
            return collectedSegments
        }
        try? await endTurn()
        try? await webSocket?.send(.string(Self.encodeJSON(["closeStream": [String: Any]()])))

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
        inworldPendingAudio = Data()
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

        guard config.provider == "inworld" else {
            throw ProviderError.unsupportedModel(config.provider)
        }
        guard websocketURL?.isEmpty == false else {
            throw ProviderError.transcriberInternal(message: "Inworld realtime session is missing server-minted websocket URL")
        }
        guard !token.isEmpty else {
            throw ProviderError.transcriberInternal(message: "Inworld realtime session is missing server-minted token")
        }
        guard config.authScheme == "bearer" else {
            throw ProviderError.transcriberInternal(message: "Inworld realtime session has unsupported auth scheme: \(config.authScheme ?? "nil")")
        }
    }

    private func flushInworldPendingAudio(to webSocket: URLSessionWebSocketTask) async throws {
        for chunk in Self.inworldAudioChunks(
            pending: &inworldPendingAudio,
            appending: Data(),
            forceFlush: true,
            sampleRate: config.sampleRate,
            channels: config.channels
        ) {
            try await webSocket.send(.string(Self.encodeJSON([
                "audioChunk": ["content": chunk.base64EncodedString()]
            ])))
        }
    }

    private func inworldTranscribeConfigPayload() -> [String: Any] {
        let language = normalisedProviderLanguage(config.language)
        var transcribeConfig: [String: Any] = [
            "modelId": config.model,
            "language": language,
            "audioEncoding": "LINEAR16",
            "sampleRateHertz": config.sampleRate,
            "numberOfChannels": config.channels,
            "inactivityTimeoutSeconds": 60,
        ]
        InworldProviderSession.applyPromptHints(from: keyTerms, to: &transcribeConfig)
        return ["transcribeConfig": transcribeConfig]
    }

    private func normalisedProviderLanguage(_ language: String) -> String {
        switch language {
        case "multi", "und":
            return ""
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

        handleInworld(json)
    }

    private func handleInworld(_ json: [String: Any]) {
        if let transcription = json["transcription"] as? [String: Any] {
            handleInworldTranscription(transcription)
        } else if let result = json["result"] as? [String: Any],
                  let transcription = result["transcription"] as? [String: Any] {
            handleInworldTranscription(transcription)
        } else if let error = json["error"] as? [String: Any] {
            eventContinuation.yield(.providerWarning(.transcriberInternal(
                message: error["message"] as? String ?? "Inworld realtime error"
            )))
        }
    }

    private func handleInworldTranscription(_ payload: [String: Any]) {
        let transcript = ((payload["text"] as? String) ?? (payload["transcript"] as? String) ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard !transcript.isEmpty else { return }
        let isFinal = (payload["is_final"] as? Bool) ?? (payload["isFinal"] as? Bool) ?? false
        if !isFinal {
            markTranscriptEvent()
            eventContinuation.yield(.interim(text: transcript, language: nil))
            return
        }
        let words = payload["words"] as? [[String: Any]]
            ?? payload["word_timestamps"] as? [[String: Any]]
            ?? payload["wordTimestamps"] as? [[String: Any]]
        appendFinal(
            text: transcript,
            speaker: Self.speakerLabel(words?.first?["speaker"] ?? words?.first?["speaker_id"]),
            startMs: Self.providerMs(
                words?.first?["start_ms"]
                    ?? words?.first?["startMs"]
                    ?? words?.first?["start_time_ms"]
                    ?? words?.first?["start"]
            ),
            endMs: Self.providerMs(
                words?.last?["end_ms"]
                    ?? words?.last?["endMs"]
                    ?? words?.last?["end_time_ms"]
                    ?? words?.last?["end"]
            ),
            confidence: (payload["confidence"] as? Double) ?? 0
        )
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

    private static func speakerLabel(_ value: Any?) -> String? {
        guard let value else { return nil }
        if let string = value as? String {
            if string.lowercased().hasPrefix("speaker") {
                return string
            }
            return "Speaker \(string)"
        }
        if let int = value as? Int {
            return "Speaker \(int)"
        }
        if let number = value as? NSNumber {
            return "Speaker \(number.intValue)"
        }
        return nil
    }

    private static func providerMs(_ value: Any?) -> Int? {
        guard let value else { return nil }
        let numeric: Double?
        if let double = value as? Double {
            numeric = double
        } else if let int = value as? Int {
            numeric = Double(int)
        } else if let number = value as? NSNumber {
            numeric = number.doubleValue
        } else if let string = value as? String {
            numeric = Double(string)
        } else {
            numeric = nil
        }
        guard var resolved = numeric else { return nil }
        if resolved >= 0, resolved < 10_000, resolved.rounded(.towardZero) != resolved {
            resolved *= 1_000
        }
        return Int(resolved)
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

    static func inworldAudioChunks(
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

    func testingHandleInworldMessage(_ text: String) {
        guard let data = text.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return }
        handleInworld(json)
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

    func testingInworldTranscribeConfigPayload() -> [String: Any] {
        inworldTranscribeConfigPayload()
    }

    func testingRequest() throws -> URLRequest {
        try makeRequest()
    }
}
