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
    private var interimByItem: [String: String] = [:]
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

        switch config.provider {
        case "openai":
            try await task.send(.string(Self.encodeJSON(openAISessionUpdatePayload())))
        case "inworld":
            try await task.send(.string(Self.encodeJSON(inworldTranscribeConfigPayload())))
        case "soniox":
            try await task.send(.string(Self.encodeJSON(sonioxRealtimeConfigPayload())))
        default:
            break
        }
        eventContinuation.yield(.opened(sessionId: config.provider))
    }

    public func send(pcm16: Data) async throws {
        guard let webSocket else {
            throw ProviderError.transcriberInternal(message: "\(config.provider) socket is not open")
        }
        switch config.provider {
        case "openai":
            let audio = WebSocketManager.openAI24kMonoPCM(
                from16kPCM: pcm16,
                channels: config.channels
            )
            try await webSocket.send(.string(Self.encodeJSON([
                "type": "input_audio_buffer.append",
                "audio": audio.base64EncodedString(),
            ])))
        case "inworld":
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
        case "deepgram", "soniox":
            try await webSocket.send(.data(pcm16))
        case "elevenlabs":
            try await webSocket.send(.string(Self.encodeJSON([
                "message_type": "input_audio_chunk",
                "audio_base_64": pcm16.base64EncodedString(),
                "sample_rate": config.sampleRate,
                "commit": false,
            ])))
        default:
            throw ProviderError.unsupportedModel(config.provider)
        }
    }

    public func endTurn() async throws {
        guard !didSendEndTurn, let webSocket else { return }
        didSendEndTurn = true
        switch config.provider {
        case "openai":
            try await webSocket.send(.string(Self.encodeJSON(["type": "input_audio_buffer.commit"])))
        case "inworld":
            try await flushInworldPendingAudio(to: webSocket)
            try await webSocket.send(.string(Self.encodeJSON(["endTurn": [String: Any]()])))
        case "deepgram":
            try await webSocket.send(.string(Self.encodeJSON(["type": "CloseStream"])))
        case "soniox":
            let silenceBytes = max(1, config.sampleRate / 5) * 2
            try await webSocket.send(.data(Data(repeating: 0, count: silenceBytes)))
            try await webSocket.send(.string(Self.encodeJSON(["type": "finalize"])))
        case "elevenlabs":
            try await webSocket.send(.string(Self.encodeJSON([
                "message_type": "input_audio_chunk",
                "audio_base_64": Data(repeating: 0, count: 640).base64EncodedString(),
                "sample_rate": config.sampleRate,
                "commit": true,
            ])))
        default:
            break
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
        if config.provider == "inworld" {
            try? await webSocket?.send(.string(Self.encodeJSON(["closeStream": [String: Any]()])))
        } else if config.provider == "soniox" {
            try? await webSocket?.send(.string(""))
        }

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

        let url: URL
        if config.provider == "elevenlabs" {
            url = try elevenLabsURL()
        } else {
            guard let urlString = config.websocketURL,
                  let parsed = URL(string: urlString) else {
                throw WebSocketConnectionError.invalidURL
            }
            url = parsed
        }

        var request = URLRequest(url: url)
        request.timeoutInterval = 30
        switch config.authScheme {
        case "bearer":
            request.setValue("Bearer \(config.token)", forHTTPHeaderField: "Authorization")
        case "basic":
            request.setValue(config.token, forHTTPHeaderField: "Authorization")
        case "message_api_key", "query_token", nil:
            break
        case let scheme?:
            throw ProviderError.transcriberInternal(message: "Unsupported auth scheme: \(scheme)")
        }
        return request
    }

    private func validateServerMintedRouting() throws {
        let token = config.token.trimmingCharacters(in: .whitespacesAndNewlines)
        let websocketURL = config.websocketURL?.trimmingCharacters(in: .whitespacesAndNewlines)

        switch config.provider {
        case "inworld":
            guard websocketURL?.isEmpty == false else {
                throw ProviderError.transcriberInternal(message: "Inworld realtime session is missing server-minted websocket URL")
            }
            guard !token.isEmpty else {
                throw ProviderError.transcriberInternal(message: "Inworld realtime session is missing server-minted token")
            }
            guard config.authScheme == "bearer" || config.authScheme == "basic" else {
                throw ProviderError.transcriberInternal(message: "Inworld realtime session has unsupported auth scheme: \(config.authScheme ?? "nil")")
            }
        case "soniox":
            guard websocketURL?.isEmpty == false else {
                throw ProviderError.transcriberInternal(message: "Soniox realtime session is missing server-minted websocket URL")
            }
            guard !token.isEmpty else {
                throw ProviderError.transcriberInternal(message: "Soniox realtime session is missing server-minted token")
            }
            guard config.authScheme == "message_api_key" else {
                throw ProviderError.transcriberInternal(message: "Soniox realtime session must use server-minted message_api_key auth")
            }
        case "elevenlabs":
            guard !token.isEmpty else {
                throw ProviderError.transcriberInternal(message: "ElevenLabs realtime session is missing server-minted query token")
            }
            guard config.authScheme == nil || config.authScheme == "query_token" else {
                throw ProviderError.transcriberInternal(message: "ElevenLabs realtime session must use server-minted query_token auth")
            }
        default:
            break
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

    private func elevenLabsURL() throws -> URL {
        var components = URLComponents(string: "wss://api.elevenlabs.io/v1/speech-to-text/realtime")
        var queryItems = [
            URLQueryItem(name: "model_id", value: config.model),
            URLQueryItem(name: "token", value: config.token),
            URLQueryItem(name: "include_timestamps", value: "true"),
            URLQueryItem(name: "audio_format", value: "pcm_16000"),
        ]
        if config.language == "multi" {
            queryItems.append(URLQueryItem(name: "include_language_detection", value: "true"))
        } else {
            queryItems.append(URLQueryItem(name: "language_code", value: config.language))
        }
        if let commitStrategy = config.commitStrategy, !commitStrategy.isEmpty {
            queryItems.append(URLQueryItem(name: "commit_strategy", value: commitStrategy))
        }
        if config.noVerbatim == true {
            queryItems.append(URLQueryItem(name: "no_verbatim", value: "true"))
        }
        for term in InworldProviderSession.cappedKeyTerms(keyTerms) {
            queryItems.append(URLQueryItem(name: "keyterms", value: term))
        }
        components?.queryItems = queryItems
        guard let url = components?.url else {
            throw WebSocketConnectionError.invalidURL
        }
        return url
    }

    private func openAISessionUpdatePayload() -> [String: Any] {
        var transcription: [String: Any] = ["model": config.model]
        if !config.language.isEmpty, config.language != "multi" {
            transcription["language"] = config.language
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
        let terms = InworldProviderSession.cappedKeyTerms(keyTerms)
        if !terms.isEmpty {
            transcribeConfig["context"] = ["terms": terms]
        }
        return ["transcribeConfig": transcribeConfig]
    }

    private func sonioxRealtimeConfigPayload() -> [String: Any] {
        let language = config.language.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        let autoLanguage = language.isEmpty || language == "multi" || language == "auto" || language == "und"
        var payload: [String: Any] = [
            "api_key": config.token,
            "model": config.model,
            "audio_format": "pcm_s16le",
            "sample_rate": config.sampleRate,
            "num_channels": config.channels,
            "enable_speaker_diarization": true,
            "enable_language_identification": autoLanguage,
            "enable_endpoint_detection": true,
            "max_endpoint_delay_ms": 500,
        ]
        if !autoLanguage {
            payload["language_hints"] = [language]
        }
        let terms = InworldProviderSession.cappedKeyTerms(keyTerms)
        if !terms.isEmpty {
            payload["context"] = ["terms": terms]
        }
        return payload
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

        switch config.provider {
        case "openai":
            handleOpenAI(json)
        case "inworld":
            handleInworld(json)
        case "deepgram":
            handleDeepgram(json)
        case "soniox":
            handleSoniox(json)
        case "elevenlabs":
            handleElevenLabs(json)
        default:
            break
        }
    }

    private func handleOpenAI(_ json: [String: Any]) {
        guard let type = json["type"] as? String else { return }
        switch type {
        case "conversation.item.input_audio_transcription.delta":
            let itemId = json["item_id"] as? String ?? "unknown"
            let delta = json["delta"] as? String ?? ""
            guard !delta.isEmpty else { return }
            let current = (interimByItem[itemId] ?? "") + delta
            interimByItem[itemId] = current
            markTranscriptEvent()
            eventContinuation.yield(.interim(text: current, language: nil))
        case "conversation.item.input_audio_transcription.completed":
            let itemId = json["item_id"] as? String ?? "unknown"
            let transcript = (json["transcript"] as? String ?? interimByItem[itemId] ?? "")
                .trimmingCharacters(in: .whitespacesAndNewlines)
            interimByItem[itemId] = nil
            appendFinal(text: transcript, speaker: nil, startMs: collectedSegments.last?.endMs ?? 0, endMs: collectedSegments.last?.endMs ?? 0, confidence: 0)
        case "error":
            let message = (json["error"] as? [String: Any])?["message"] as? String ?? "OpenAI realtime error"
            eventContinuation.yield(.providerWarning(.transcriberInternal(message: message)))
        default:
            break
        }
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
            startMs: Self.providerMs(words?.first?["start_ms"] ?? words?.first?["startMs"] ?? words?.first?["start"]),
            endMs: Self.providerMs(words?.last?["end_ms"] ?? words?.last?["endMs"] ?? words?.last?["end"]),
            confidence: (payload["confidence"] as? Double) ?? 0
        )
    }

    private func handleDeepgram(_ json: [String: Any]) {
        let type = json["type"] as? String
        if type == "Results",
           let channel = json["channel"] as? [String: Any],
           let alternatives = channel["alternatives"] as? [[String: Any]],
           let alternative = alternatives.first {
            handleDeepgramTranscript(
                alternative,
                isFinal: (json["is_final"] as? Bool) ?? (json["speech_final"] as? Bool) ?? false
            )
        } else if type == "TurnInfo" {
            handleDeepgramTranscript(json, isFinal: (json["event"] as? String) == "EndOfTurn")
        } else if json["transcript"] is String {
            handleDeepgramTranscript(json, isFinal: true)
        } else if type == "Error" || json["error"] != nil {
            eventContinuation.yield(.providerWarning(.transcriberInternal(
                message: json["message"] as? String ?? json["description"] as? String ?? "Deepgram realtime error"
            )))
        }
    }

    private func handleDeepgramTranscript(_ payload: [String: Any], isFinal: Bool) {
        let transcript = (payload["transcript"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        guard !transcript.isEmpty else { return }
        if !isFinal {
            markTranscriptEvent()
            eventContinuation.yield(.interim(text: transcript, language: nil))
            return
        }
        let words = payload["words"] as? [[String: Any]] ?? []
        appendFinal(
            text: transcript,
            speaker: Self.speakerLabel(words.first?["speaker"]),
            startMs: Self.secondsMs(words.first?["start"]),
            endMs: Self.secondsMs(words.last?["end"]),
            confidence: (payload["confidence"] as? Double) ?? Self.averageConfidence(words) ?? 0
        )
    }

    private func handleSoniox(_ json: [String: Any]) {
        if let errorCode = json["error_code"] as? String, !errorCode.isEmpty {
            eventContinuation.yield(.providerWarning(.transcriberInternal(
                message: json["error_message"] as? String ?? "Soniox realtime error: \(errorCode)"
            )))
            return
        }
        let tokens = json["tokens"] as? [[String: Any]] ?? []
        let finalTokens = tokens.filter { ($0["is_final"] as? Bool) == true }
        let nonFinalTokens = tokens.filter { ($0["is_final"] as? Bool) != true }
        if finalTokens.contains(where: { (($0["text"] as? String) ?? "").hasPrefix("<") }) {
            markTranscriptEvent(finalizationMarker: true)
        }
        if let segment = sonioxSegment(from: finalTokens, isFinal: true) {
            collectedSegments.append(segment)
            markTranscriptEvent()
            eventContinuation.yield(.committed(segment))
        }
        if let segment = sonioxSegment(from: nonFinalTokens, isFinal: false) {
            markTranscriptEvent()
            eventContinuation.yield(.interim(text: segment.text, language: nil))
        }
    }

    private func handleElevenLabs(_ json: [String: Any]) {
        let type = (json["message_type"] as? String) ?? (json["type"] as? String) ?? ""
        switch type {
        case "partial_transcript":
            let text = (json["text"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            if !text.isEmpty {
                markTranscriptEvent()
                eventContinuation.yield(.interim(text: text, language: nil))
            }
        case "committed_transcript", "committed_transcript_with_timestamps":
            let text = (json["text"] as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            let words = (json["words"] as? [[String: Any]] ?? []).filter { ($0["type"] as? String) != "spacing" }
            appendFinal(
                text: text,
                speaker: nil,
                startMs: Self.secondsMs(words.first?["start"]),
                endMs: Self.secondsMs(words.last?["end"]),
                confidence: Self.elevenLabsConfidence(words)
            )
        default:
            if type.hasSuffix("error") || type.contains("_error") {
                eventContinuation.yield(.providerWarning(.transcriberInternal(message: type)))
            }
        }
    }

    private func sonioxSegment(from tokens: [[String: Any]], isFinal: Bool) -> LiveTranscriptSegment? {
        let speechTokens = tokens.filter {
            ($0["translation_status"] as? String) != "translation"
                && (($0["text"] as? String)?.hasPrefix("<") != true)
        }
        let text = speechTokens.compactMap { $0["text"] as? String }
            .joined()
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return nil }
        return LiveTranscriptSegment(
            text: text,
            speaker: Self.speakerLabel(speechTokens.first?["speaker"]),
            isFinal: isFinal,
            startMs: Self.providerMs(speechTokens.first?["start_ms"]) ?? (collectedSegments.last?.endMs ?? 0),
            endMs: Self.providerMs(speechTokens.last?["end_ms"]) ?? (collectedSegments.last?.endMs ?? 0),
            confidence: Self.averageConfidence(speechTokens) ?? 0
        )
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
        if let int = value as? Int { return int }
        if let number = value as? NSNumber { return number.intValue }
        if let double = value as? Double { return Int(double) }
        if let string = value as? String { return Int(string) }
        return nil
    }

    private static func secondsMs(_ value: Any?) -> Int? {
        guard let value else { return nil }
        if let double = value as? Double { return Int(double * 1000) }
        if let number = value as? NSNumber { return Int(number.doubleValue * 1000) }
        if let string = value as? String, let double = Double(string) { return Int(double * 1000) }
        return nil
    }

    private static func averageConfidence(_ words: [[String: Any]]) -> Double? {
        let values = words.compactMap { word -> Double? in
            if let double = word["confidence"] as? Double { return double }
            if let number = word["confidence"] as? NSNumber { return number.doubleValue }
            return nil
        }
        guard !values.isEmpty else { return nil }
        return values.reduce(0, +) / Double(values.count)
    }

    private static func elevenLabsConfidence(_ words: [[String: Any]]) -> Double {
        let logprobs = words.compactMap { word -> Double? in
            if let double = word["logprob"] as? Double { return double }
            if let number = word["logprob"] as? NSNumber { return number.doubleValue }
            return nil
        }
        guard !logprobs.isEmpty else { return 0 }
        let average = logprobs.reduce(0, +) / Double(logprobs.count)
        return max(0, min(1, 1 + average / 10))
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

    func testingHandleDeepgramMessage(_ text: String) {
        guard let data = text.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return }
        handleDeepgram(json)
    }

    func testingHandleSonioxMessage(_ text: String) {
        guard let data = text.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return }
        handleSoniox(json)
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

    func testingRequest() throws -> URLRequest {
        try makeRequest()
    }
}
