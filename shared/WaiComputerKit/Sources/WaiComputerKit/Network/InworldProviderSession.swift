import Foundation
import AVFoundation
import os

private let inworldLog = Logger(subsystem: "is.waiwai.computer.kit", category: "inworld")

/// Inworld AI realtime STT WebSocket session — single primary path for the
/// dictation flow. Connects to Inworld's unified bidirectional streaming
/// endpoint.
///
/// Protocol (verified against docs.inworld.ai 2026-05-06):
/// - URL: `wss://api.inworld.ai/stt/v1/transcribe:streamBidirectional`
/// - Auth: HTTP `Authorization: Bearer <jwt>` header
/// - First message: `transcribeConfig` JSON
/// - Audio: `audioChunk` with base64-encoded LINEAR16 PCM
/// - End turn: `endTurn` (signals utterance boundary for VAD)
/// - Close: `closeStream` (mandatory before disconnect)
/// - Server frames: `transcription` (interim+final), `voice_profile`,
///   `usage`, `error`
public actor InworldProviderSession: ProviderSession {
    public nonisolated let events: AsyncStream<TranscriptionEvent>

    private let eventContinuation: AsyncStream<TranscriptionEvent>.Continuation
    private let urlSession: URLSession
    private let websocketURL: URL
    private let authHeader: String
    private let modelId: String
    private let language: String
    private let sampleRate: Int
    private let channels: Int
    private let keyTerms: [String]

    private var webSocket: URLSessionWebSocketTask?
    private var receiveTask: Task<Void, Never>?
    private var collectedSegments: [LiveTranscriptSegment] = []
    private var isClosing = false
    private var didOpen = false
    // Diagnostic counters to debug "session ready but no transcripts" — log
    // every 20 audio chunks (≈1 s of audio at 50 ms cadence) and every WS
    // message we receive so the live trail in Console.app shows whether the
    // problem is on the send side, receive side, or upstream silence.
    private var audioChunksSent: Int = 0
    private var rxFrames: Int = 0

    public init(
        websocketURL: URL,
        authHeader: String,
        modelId: String,
        language: String,
        sampleRate: Int = 16_000,
        channels: Int = 1,
        keyTerms: [String] = [],
        urlSession: URLSession = .shared
    ) {
        self.websocketURL = websocketURL
        self.authHeader = authHeader
        self.modelId = modelId
        self.language = language
        self.sampleRate = sampleRate
        self.channels = channels
        self.keyTerms = keyTerms
        self.urlSession = urlSession

        let (stream, continuation) = AsyncStream.makeStream(
            of: TranscriptionEvent.self,
            bufferingPolicy: .bufferingNewest(256)
        )
        self.events = stream
        self.eventContinuation = continuation
    }

    /// Soniox v4 RT documents a ~10K char total context budget across all
    /// fields. Cap and de-dupe so a runaway dictionary doesn't get the
    /// session rejected at the wire edge.
    static let sonioxContextCharBudget = 9_000
    static let sonioxTermCharLimit = 60

    static func cappedKeyTerms(_ terms: [String]) -> [String] {
        var seen = Set<String>()
        var result: [String] = []
        var totalChars = 0
        for raw in terms {
            let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !trimmed.isEmpty else { continue }
            let term = String(trimmed.prefix(sonioxTermCharLimit))
            let key = term.lowercased()
            if seen.contains(key) { continue }
            if totalChars + term.count > sonioxContextCharBudget { break }
            seen.insert(key)
            result.append(term)
            totalChars += term.count + 1  // +1 for join separator
        }
        return result
    }

    static func applyPromptHints(from keyTerms: [String], to transcribeConfig: inout [String: Any]) {
        let prompts = cappedKeyTerms(keyTerms)
        guard !prompts.isEmpty else { return }

        // Inworld STT reads contextual hints from top-level `prompts`.
        // Soniox keeps using its provider-specific `context.terms` field.
        transcribeConfig["prompts"] = prompts
    }

    // MARK: - ProviderSession

    public func send(pcm16: Data) async throws {
        guard let webSocket else { throw ProviderError.transcriberInternal(message: "socket not open") }
        let payload: [String: Any] = [
            "audioChunk": [
                "content": pcm16.base64EncodedString()
            ]
        ]
        try await webSocket.send(.string(Self.encodeJSON(payload)))
        audioChunksSent &+= 1
        // Log first 5 chunks (so we see audio actually starts) then every 20th
        // (so we get ~1Hz progress signal without spamming).
        if audioChunksSent <= 5 || audioChunksSent % 20 == 0 {
            inworldLog.info("[Inworld] TX audioChunk #\(self.audioChunksSent) bytes=\(pcm16.count)")
        }
    }

    public func endTurn() async throws {
        guard let webSocket else { return }
        try await webSocket.send(.string(Self.encodeJSON(["endTurn": [String: Any]()])))
    }

    public func close(timeout: Duration = .seconds(5)) async throws -> [LiveTranscriptSegment] {
        guard !isClosing else { return collectedSegments }
        isClosing = true

        guard let webSocket else { return collectedSegments }
        try? await webSocket.send(.string(Self.encodeJSON(["closeStream": [String: Any]()])))

        // Drain remaining transcription frames within `timeout`. The server
        // closes the socket after the final `usage` frame; we wait for that
        // event or the deadline, whichever comes first.
        let deadline = ContinuousClock().now + timeout
        while ContinuousClock().now < deadline, webSocket.closeCode == .invalid {
            try? await Task.sleep(for: .milliseconds(100))
        }

        webSocket.cancel(with: .normalClosure, reason: nil)
        receiveTask?.cancel()
        eventContinuation.yield(.closed(reason: .clientRequested))
        eventContinuation.finish()
        return collectedSegments
    }

    public func cancel() async {
        guard !isClosing else { return }
        isClosing = true
        webSocket?.cancel(with: .goingAway, reason: nil)
        receiveTask?.cancel()
        eventContinuation.yield(.closed(reason: .clientRequested))
        eventContinuation.finish()
    }

    // MARK: - Connection bring-up

    /// Open the WebSocket and send the initial `transcribeConfig`. Throws
    /// when the handshake or first-message send fails. After this call
    /// returns, `events` will start emitting `.opened` followed by
    /// `.interim` / `.committed` frames.
    public func open() async throws {
        guard webSocket == nil else { return }

        var request = URLRequest(url: websocketURL)
        request.timeoutInterval = 30
        request.setValue(authHeader, forHTTPHeaderField: "Authorization")

        let task = urlSession.webSocketTask(with: request)
        webSocket = task
        task.resume()
        inworldLog.info("[Inworld] WebSocket task created, sending transcribeConfig model=\(self.modelId, privacy: .public) lang=\(self.language, privacy: .public)")

        // First message — provider session config.
        //
        // Language tag rules (verified against the live API on 2026-05-07):
        //   - Simple 2-letter BCP-47 ("en", "ru") work and transcribe.
        //   - Region-qualified BCP-47 ("en-US", "ru-RU") silently close the
        //     socket despite the API's own error message claiming they are
        //     valid. Don't send those.
        //   - Empty string is the multi-language auto-detect (replaces the
        //     legacy "multi" tag, which is now rejected with
        //     "invalid language tag format 'multi'").
        // We translate the legacy "multi" caller value to "" at the wire
        // edge so backend + UserDefaults that still say "multi" keep
        // working without a coordinated rollout.
        let normalisedLanguage: String
        switch language {
        case "multi", "und":
            normalisedLanguage = ""  // Soniox auto-detect
        case let other where other.contains("-"):
            // "en-US" → "en" — drop the region. The ASR model is
            // multilingual already; the region was only ever a hint.
            normalisedLanguage = String(other.split(separator: "-").first ?? Substring(other))
        default:
            normalisedLanguage = language
        }
        // `inactivity_timeout_seconds` keeps hands-free silent gaps alive
        // (Inworld's undocumented default fires too aggressively).
        var transcribeConfig: [String: Any] = [
            "modelId": modelId,
            "language": normalisedLanguage,
            "audioEncoding": "LINEAR16",
            "sampleRateHertz": sampleRate,
            "numberOfChannels": channels,
            "inactivityTimeoutSeconds": 60,
        ]
        Self.applyPromptHints(from: keyTerms, to: &transcribeConfig)
        let configPayload: [String: Any] = [
            "transcribeConfig": transcribeConfig
        ]
        try await task.send(.string(Self.encodeJSON(configPayload)))
        inworldLog.info("[Inworld] sent transcribeConfig language='\(normalisedLanguage, privacy: .public)' (caller passed '\(self.language, privacy: .public)')")

        startReceiveLoop(for: task)
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
        rxFrames &+= 1
        switch message {
        case .string(let text):
            inworldLog.info("[Inworld] RX #\(self.rxFrames) \(Self.safeReceivedTextFrameSummary(text), privacy: .public)")
            handleText(text)
        case .data(let data):
            inworldLog.info("[Inworld] RX #\(self.rxFrames) binary: \(data.count) bytes")
            if let text = String(data: data, encoding: .utf8) {
                handleText(text)
            }
        @unknown default:
            inworldLog.warning("[Inworld] RX #\(self.rxFrames) unknown frame type")
        }
    }

    private func handleText(_ text: String) {
        guard let data = text.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else {
            inworldLog.warning("[Inworld] Unparseable frame received")
            return
        }

        if let transcription = json["transcription"] as? [String: Any] {
            handleTranscription(transcription)
            return
        }
        if let voiceProfile = json["voice_profile"] as? [String: Any] {
            handleVoiceProfile(voiceProfile)
            return
        }
        if let usage = json["usage"] as? [String: Any] {
            let secs = (usage["audio_duration_seconds"] as? Double)
                ?? (usage["prompted_seconds"] as? Double)
                ?? 0
            eventContinuation.yield(.usage(promptedSeconds: secs))
            return
        }
        if let err = json["error"] as? [String: Any] {
            handleErrorFrame(err)
            return
        }
        // Some Inworld variants wrap the actual payload in a `result` field.
        if let result = json["result"] as? [String: Any],
           let transcription = result["transcription"] as? [String: Any] {
            handleTranscription(transcription)
        }
    }

    private func handleTranscription(_ payload: [String: Any]) {
        let text = ((payload["text"] as? String) ?? (payload["transcript"] as? String) ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard text.isEmpty == false else { return }

        let isFinal = (payload["is_final"] as? Bool) ?? (payload["isFinal"] as? Bool) ?? false
        let language = payload["language"] as? String
        let confidence = (payload["confidence"] as? Double) ?? 0.0

        if didOpen == false {
            didOpen = true
            eventContinuation.yield(.opened(sessionId: UUID().uuidString))
        }

        if isFinal {
            // Soniox / Inworld may include word-level timing as `words`. Fold
            // start/end ms when present; fall back to 0 otherwise.
            let words = (payload["words"] as? [[String: Any]])
                ?? (payload["word_timestamps"] as? [[String: Any]])
                ?? (payload["wordTimestamps"] as? [[String: Any]])
                ?? []
            let startMs = Self.timestampMs(
                words.first?["start_ms"]
                    ?? words.first?["startMs"]
                    ?? words.first?["start_time_ms"]
                    ?? words.first?["start"]
            )
                ?? 0
            let endMs = Self.timestampMs(
                words.last?["end_ms"]
                    ?? words.last?["endMs"]
                    ?? words.last?["end_time_ms"]
                    ?? words.last?["end"]
            )
                ?? 0
            let speaker = (words.first?["speaker"] as? String)
                ?? (words.first?["speaker_id"] as? String)

            let segment = LiveTranscriptSegment(
                text: text,
                speaker: speaker,
                isFinal: true,
                startMs: startMs,
                endMs: endMs,
                confidence: confidence
            )
            collectedSegments.append(segment)
            eventContinuation.yield(.committed(segment))
        } else {
            eventContinuation.yield(.interim(text: text, language: language))
        }
    }

    private static func timestampMs(_ value: Any?) -> Int? {
        if let intValue = value as? Int {
            return intValue
        }
        if let doubleValue = value as? Double {
            return doubleValue > 10_000 ? Int(doubleValue) : Int(doubleValue * 1000)
        }
        if let stringValue = value as? String, let doubleValue = Double(stringValue) {
            return doubleValue > 10_000 ? Int(doubleValue) : Int(doubleValue * 1000)
        }
        return nil
    }

    private func handleVoiceProfile(_ payload: [String: Any]) {
        let profile = VoiceProfile(
            age: payload["age"] as? String,
            pitch: payload["pitch"] as? String,
            emotion: payload["emotion"] as? String,
            vocalStyle: payload["vocal_style"] as? String ?? payload["vocalStyle"] as? String,
            accent: payload["accent"] as? String
        )
        eventContinuation.yield(.voiceProfile(profile))
    }

    private func handleErrorFrame(_ payload: [String: Any]) {
        let code = (payload["code"] as? String)?.lowercased()
            ?? (payload["error_code"] as? String)?.lowercased()
            ?? "unknown"
        let message = (payload["message"] as? String) ?? (payload["error_message"] as? String)
        let providerError: ProviderError = Self.mapError(code: code, message: message)
        eventContinuation.yield(.providerWarning(providerError))
        inworldLog.error(
            "[Inworld] error frame code=\(code, privacy: .public) messageLen=\(message?.count ?? 0) mappedTo=\(String(describing: providerError), privacy: .public)"
        )
    }

    private func handleSocketError(_ error: Error) {
        let urlError = error as? URLError
        let code = urlError?.code
        inworldLog.error("[Inworld] socket error code=\(String(describing: code))")
        if case .cancelled = code { return }
        eventContinuation.yield(.closed(reason: .networkLost))
        eventContinuation.finish()
    }

    private static func mapError(code: String, message: String?) -> ProviderError {
        switch code {
        case "auth_error", "unauthenticated", "unauthorized":
            return .authError(server: message)
        case "quota_exceeded", "billing_quota_exceeded":
            return .quotaExceeded
        case "rate_limited", "too_many_requests":
            return .rateLimited(retryAfterMs: nil)
        case "insufficient_audio_activity":
            return .insufficientAudioActivity
        case "session_time_limit_exceeded":
            return .sessionTimeLimitExceeded
        case "chunk_size_exceeded":
            return .chunkSizeExceeded
        case "commit_throttled":
            return .commitThrottled
        case "unsupported_model":
            return .unsupportedModel(message ?? "")
        case "transcriber_error", "internal":
            return .transcriberInternal(message: message ?? "")
        default:
            return .transcriberInternal(message: message ?? code)
        }
    }

    static func safeReceivedTextFrameSummary(_ text: String) -> String {
        guard let data = text.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else {
            return "text frame bytes=\(text.utf8.count) parseable=false"
        }

        if let transcription = json["transcription"] as? [String: Any] {
            let transcript = (transcription["transcript"] as? String)
                ?? (transcription["text"] as? String)
                ?? ""
            let isFinal = (transcription["is_final"] as? Bool)
                ?? (transcription["isFinal"] as? Bool)
            return "transcription frame chars=\(transcript.count) final=\(isFinal.map(String.init) ?? "unknown")"
        }

        if json["error"] != nil {
            return "error frame bytes=\(text.utf8.count)"
        }

        let keys = json.keys.sorted().joined(separator: ",")
        return "text frame bytes=\(text.utf8.count) keys=\(keys)"
    }

    private static func encodeJSON(_ payload: [String: Any]) -> String {
        guard let data = try? JSONSerialization.data(withJSONObject: payload, options: []) else {
            return "{}"
        }
        return String(data: data, encoding: .utf8) ?? "{}"
    }
}

/// Convert a Float32 mono PCM buffer (the format `AudioEngineHost` emits
/// after resampling) to little-endian Int16 LINEAR16 bytes — the wire
/// format Inworld / Soniox expect.
public enum LINEAR16Encoder {
    public static func encode(_ buffer: AVAudioPCMBuffer) -> Data? {
        guard let floats = buffer.floatChannelData?[0] else { return nil }
        let frames = Int(buffer.frameLength)
        guard frames > 0 else { return nil }

        var bytes = Data(count: frames * MemoryLayout<Int16>.size)
        bytes.withUnsafeMutableBytes { rawBufferPointer in
            guard let dst = rawBufferPointer.bindMemory(to: Int16.self).baseAddress else { return }
            for i in 0..<frames {
                let sample = max(-1.0, min(1.0, floats[i]))
                dst[i] = Int16(sample * 32767.0)
            }
        }
        return bytes
    }
}
