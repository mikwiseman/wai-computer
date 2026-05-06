import Foundation
import AVFoundation
import os

private let inworldLog = Logger(subsystem: "com.waisay.kit", category: "inworld")

/// Inworld AI realtime STT WebSocket session — single primary path for the
/// dictation flow. Connects to Soniox v4 RT (default model) via Inworld's
/// unified bidirectional streaming endpoint.
///
/// Protocol (verified against docs.inworld.ai 2026-05-06):
/// - URL: `wss://api.inworld.ai/stt/v1/transcribe:streamBidirectional`
/// - Auth: HTTP `Authorization: Basic <base64-id:secret>` header
/// - First message: `transcribe_config` JSON
/// - Audio: `audio_chunk` with base64-encoded LINEAR16 PCM
/// - End turn: `end_turn` (signals utterance boundary for VAD)
/// - Close: `close_stream` (mandatory before disconnect)
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

    private var webSocket: URLSessionWebSocketTask?
    private var receiveTask: Task<Void, Never>?
    private var collectedSegments: [LiveTranscriptSegment] = []
    private var isClosing = false
    private var didOpen = false

    public init(
        websocketURL: URL,
        authHeader: String,
        modelId: String,
        language: String,
        sampleRate: Int = 16_000,
        channels: Int = 1,
        urlSession: URLSession = .shared
    ) {
        self.websocketURL = websocketURL
        self.authHeader = authHeader
        self.modelId = modelId
        self.language = language
        self.sampleRate = sampleRate
        self.channels = channels
        self.urlSession = urlSession

        let (stream, continuation) = AsyncStream.makeStream(of: TranscriptionEvent.self)
        self.events = stream
        self.eventContinuation = continuation
    }

    // MARK: - ProviderSession

    public func send(pcm16: Data) async throws {
        guard let webSocket else { throw ProviderError.transcriberInternal(message: "socket not open") }
        let payload: [String: Any] = [
            "audio_chunk": [
                "content": pcm16.base64EncodedString()
            ]
        ]
        try await webSocket.send(.string(Self.encodeJSON(payload)))
    }

    public func endTurn() async throws {
        guard let webSocket else { return }
        try await webSocket.send(.string(Self.encodeJSON(["end_turn": [String: Any]()])))
    }

    public func close(timeout: Duration = .seconds(5)) async throws -> [LiveTranscriptSegment] {
        guard !isClosing else { return collectedSegments }
        isClosing = true

        guard let webSocket else { return collectedSegments }
        try? await webSocket.send(.string(Self.encodeJSON(["close_stream": [String: Any]()])))

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

    /// Open the WebSocket and send the initial `transcribe_config`. Throws
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
        inworldLog.info("[Inworld] WebSocket task created, sending transcribe_config model=\(self.modelId, privacy: .public) lang=\(self.language, privacy: .public)")

        // First message — provider session config.
        let configPayload: [String: Any] = [
            "transcribe_config": [
                "model_id": modelId,
                "language": language,
                "audio_encoding": "LINEAR16",
                "sample_rate_hertz": sampleRate,
                "number_of_channels": channels,
            ] as [String: Any]
        ]
        try await task.send(.string(Self.encodeJSON(configPayload)))

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
        let text = (payload["text"] as? String) ?? ""
        let isFinal = (payload["is_final"] as? Bool) ?? false
        let language = payload["language"] as? String
        let confidence = (payload["confidence"] as? Double) ?? 0.0

        if didOpen == false {
            didOpen = true
            eventContinuation.yield(.opened(sessionId: UUID().uuidString))
        }

        if isFinal {
            // Soniox / Inworld may include word-level timing as `words`. Fold
            // start/end ms when present; fall back to 0 otherwise.
            let words = payload["words"] as? [[String: Any]] ?? []
            let startMs = (words.first?["start_ms"] as? Int)
                ?? (words.first?["start_ms"] as? Double).map(Int.init)
                ?? 0
            let endMs = (words.last?["end_ms"] as? Int)
                ?? (words.last?["end_ms"] as? Double).map(Int.init)
                ?? 0
            let speaker = words.first?["speaker"] as? String

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
        inworldLog.error("[Inworld] error frame code=\(code, privacy: .public)")
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
