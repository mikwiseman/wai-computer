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

    private let wsLog = Logger(subsystem: "is.waiwai.computer.kit", category: "websocket")
    private let apiClient: APIClient
    private let language: String
    private let channels: Int
    private let purpose: RealtimeTranscriptionPurpose

    private var webSocket: URLSessionWebSocketTask?
    private var eventContinuation: AsyncStream<WebSocketEvent>.Continuation?
    private var receiveTask: Task<Void, Never>?
    private var connectionId: UInt64 = 0
    private var sendCount = 0
    private var transcriptionSession: RealtimeTranscriptionSessionConfig?
    private let reconnectClock = ContinuousClock()
    private var lastTranscriptReceivedAt: ContinuousClock.Instant?
    private var openAIInterimByItem: [String: String] = [:]
    private var inworldPendingAudio = Data()

    private enum CommittedTranscriptKind {
        case plain
        case timestamped
    }

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
    private static let inworldMinAudioChunkBytes = 16_000 * 2 * 20 / 1000
    private static let inworldMaxAudioChunkBytes = 16_000 * 2

    /// All final transcript segments collected during this session.
    /// Preserved across reconnections so no transcript data is lost.
    public private(set) var collectedSegments: [LiveTranscriptSegment] = []
    private var collectedSegmentKinds: [CommittedTranscriptKind] = []

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
    /// toward — names, jargon, custom spellings). Capped + truncated to the
    /// provider's hard limit inside `buildElevenLabsURL`.
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
        collectedSegmentKinds = []
        lastTranscriptReceivedAt = nil
        openAIInterimByItem = [:]
        inworldPendingAudio = Data()
        reconnectAttempt = 0
        audioBuffer = []
        isReconnecting = false
        reconnectTask?.cancel()
        reconnectTask = nil
        endOfStreamRequested = false
        endOfStreamSent = false

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
        try await sendOpenAISessionUpdateIfNeeded(sessionConfig)
        try await sendInworldTranscribeConfigIfNeeded(sessionConfig)
        try await sendSonioxRealtimeConfigIfNeeded(sessionConfig)

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
        let minimumWaitUntil = reconnectClock.now + .milliseconds(150)
        let quietWindow: Duration = .milliseconds(350)
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

        let didFinalize = endOfStreamSent
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

    // MARK: - URL builders

    func buildElevenLabsURL(
        token: String,
        model: String,
        commitStrategy: String?,
        noVerbatim: Bool = false
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
        if noVerbatim {
            queryItems.append(URLQueryItem(name: "no_verbatim", value: "true"))
        }
        // ElevenLabs Scribe v2 Realtime hard limits: 50 keyterms, 20 chars each.
        // Trim then truncate so we send the most distinctive terms first
        // (the dictionary list is already user-curated, so just take the head).
        for term in Self.cappedKeyTerms(keyTerms) {
            queryItems.append(URLQueryItem(name: "keyterms", value: term))
        }
        components?.queryItems = queryItems
        guard let url = components?.url else {
            throw WebSocketConnectionError.invalidURL
        }
        return url
    }

    static let elevenLabsKeyTermsLimit = 50
    static let elevenLabsKeyTermCharLimit = 20

    static func cappedKeyTerms(_ terms: [String]) -> [String] {
        terms
            .lazy
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
            .prefix(elevenLabsKeyTermsLimit)
            .map { String($0.prefix(elevenLabsKeyTermCharLimit)) }
    }

    // MARK: - Private

    private func requestForRealtimeSession(
        _ sessionConfig: RealtimeTranscriptionSessionConfig
    ) throws -> URLRequest {
        if ["openai", "inworld", "deepgram", "soniox"].contains(sessionConfig.provider) {
            guard let urlString = sessionConfig.websocketURL,
                  let url = URL(string: urlString) else {
                throw WebSocketConnectionError.invalidURL
            }
            var request = URLRequest(url: url)
            request.timeoutInterval = 300
            switch sessionConfig.authScheme {
            case "bearer":
                request.setValue("Bearer \(sessionConfig.token)", forHTTPHeaderField: "Authorization")
            case "basic":
                request.setValue(sessionConfig.token, forHTTPHeaderField: "Authorization")
            case "message_api_key", nil:
                break
            case let scheme?:
                throw WebSocketConnectionError.tokenFetchFailed(
                    "Unsupported auth scheme for \(sessionConfig.provider): \(scheme)"
                )
            }
            return request
        }

        guard sessionConfig.provider == "elevenlabs" else {
            throw WebSocketConnectionError.tokenFetchFailed(
                "Unsupported transcription provider: \(sessionConfig.provider)"
            )
        }

        let url = try buildElevenLabsURL(
            token: sessionConfig.token,
            model: sessionConfig.model,
            commitStrategy: sessionConfig.commitStrategy,
            noVerbatim: sessionConfig.noVerbatim ?? false
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

        if transcriptionSession?.provider == "openai" {
            try await webSocket.send(.string(makeOpenAIAudioAppendMessage(data: data)))
            return
        }

        if transcriptionSession?.provider == "inworld" {
            try await sendInworldAudio(data, forceFlush: false)
            return
        }

        if transcriptionSession?.provider == "deepgram" || transcriptionSession?.provider == "soniox" {
            try await webSocket.send(.data(data))
            return
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

        return Self.encodeJSONPayload(payload)
    }

    private func makeOpenAIAudioAppendMessage(data: Data) -> String {
        let payload: [String: Any] = [
            "type": "input_audio_buffer.append",
            "audio": Self.openAI24kMonoPCM(from16kPCM: data, channels: channels).base64EncodedString(),
        ]
        return Self.encodeJSONPayload(payload)
    }

    private func makeInworldAudioChunkMessage(data: Data) -> String {
        let payload: [String: Any] = [
            "audioChunk": [
                "content": data.base64EncodedString()
            ]
        ]
        return Self.encodeJSONPayload(payload)
    }

    private func makeOpenAISessionUpdateMessage(_ sessionConfig: RealtimeTranscriptionSessionConfig) -> String {
        var transcription: [String: Any] = ["model": sessionConfig.model]
        if !sessionConfig.language.isEmpty, sessionConfig.language != "multi" {
            transcription["language"] = sessionConfig.language
        }
        let payload: [String: Any] = [
            "type": "session.update",
            "session": [
                "type": "transcription",
                "audio": [
                    "input": [
                        "format": [
                            "type": "audio/pcm",
                            "rate": sessionConfig.sampleRate,
                        ],
                        "transcription": transcription,
                        "turn_detection": NSNull(),
                    ],
                ],
            ],
        ]
        return Self.encodeJSONPayload(payload)
    }

    private func makeInworldTranscribeConfigMessage(_ sessionConfig: RealtimeTranscriptionSessionConfig) -> String {
        let normalisedLanguage: String
        switch sessionConfig.language {
        case "multi", "und":
            normalisedLanguage = ""
        case let other where other.contains("-"):
            normalisedLanguage = String(other.split(separator: "-").first ?? Substring(other))
        default:
            normalisedLanguage = sessionConfig.language
        }

        var transcribeConfig: [String: Any] = [
            "modelId": sessionConfig.model,
            "language": normalisedLanguage,
            "audioEncoding": "LINEAR16",
            "sampleRateHertz": sessionConfig.sampleRate,
            "numberOfChannels": sessionConfig.channels,
            "inactivityTimeoutSeconds": 60,
        ]
        let cappedTerms = InworldProviderSession.cappedKeyTerms(keyTerms)
        if !cappedTerms.isEmpty {
            transcribeConfig["context"] = ["terms": cappedTerms]
        }

        let payload: [String: Any] = [
            "transcribeConfig": transcribeConfig
        ]
        return Self.encodeJSONPayload(payload)
    }

    private func makeSonioxRealtimeConfigMessage(_ sessionConfig: RealtimeTranscriptionSessionConfig) -> String {
        let normalisedLanguage = sessionConfig.language.trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
        let isAutoLanguage = normalisedLanguage.isEmpty
            || normalisedLanguage == "multi"
            || normalisedLanguage == "auto"
            || normalisedLanguage == "und"

        var payload: [String: Any] = [
            "api_key": sessionConfig.token,
            "model": sessionConfig.model,
            "audio_format": "pcm_s16le",
            "sample_rate": sessionConfig.sampleRate,
            "num_channels": sessionConfig.channels,
            "enable_speaker_diarization": true,
            "enable_language_identification": isAutoLanguage,
            "enable_endpoint_detection": true,
            "max_endpoint_delay_ms": 500,
        ]
        if !isAutoLanguage {
            payload["language_hints"] = [normalisedLanguage]
        }
        let cappedTerms = InworldProviderSession.cappedKeyTerms(keyTerms)
        if !cappedTerms.isEmpty {
            payload["context"] = ["terms": cappedTerms]
        }
        return Self.encodeJSONPayload(payload)
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

    static func openAI24kMonoPCM(from16kPCM data: Data, channels: Int) -> Data {
        let sourceChannels = max(1, channels)
        let bytesPerFrame = sourceChannels * MemoryLayout<Int16>.size
        guard data.count >= bytesPerFrame else { return data }

        var monoSamples: [Double] = []
        monoSamples.reserveCapacity(data.count / bytesPerFrame)
        data.withUnsafeBytes { rawBuffer in
            let samples = rawBuffer.bindMemory(to: Int16.self)
            let frameCount = samples.count / sourceChannels
            for frame in 0..<frameCount {
                var mixed = 0
                for channel in 0..<sourceChannels {
                    mixed += Int(Int16(littleEndian: samples[frame * sourceChannels + channel]))
                }
                monoSamples.append(Double(mixed) / Double(sourceChannels))
            }
        }

        guard monoSamples.count > 1 else { return data }

        let sourceRate = 16_000.0
        let targetRate = 24_000.0
        let outputCount = Int((Double(monoSamples.count) * targetRate / sourceRate).rounded(.down))
        var output = Data(capacity: outputCount * MemoryLayout<Int16>.size)
        for index in 0..<outputCount {
            let sourcePosition = Double(index) * sourceRate / targetRate
            let lower = min(Int(sourcePosition), monoSamples.count - 1)
            let upper = min(lower + 1, monoSamples.count - 1)
            let fraction = sourcePosition - Double(lower)
            let interpolated = monoSamples[lower] + (monoSamples[upper] - monoSamples[lower]) * fraction
            let clamped = max(Double(Int16.min), min(Double(Int16.max), interpolated.rounded()))
            let sample = Int16(clamped).littleEndian
            withUnsafeBytes(of: sample) { output.append(contentsOf: $0) }
        }
        return output
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

    func testingMakeOpenAIAudioAppendMessage(data: Data) -> String {
        makeOpenAIAudioAppendMessage(data: data)
    }

    func testingMakeInworldAudioChunkMessage(data: Data) -> String {
        makeInworldAudioChunkMessage(data: data)
    }

    func testingMakeInworldTranscribeConfigMessage(_ sessionConfig: RealtimeTranscriptionSessionConfig) -> String {
        makeInworldTranscribeConfigMessage(sessionConfig)
    }

    func testingMakeSonioxRealtimeConfigMessage(_ sessionConfig: RealtimeTranscriptionSessionConfig) -> String {
        makeSonioxRealtimeConfigMessage(sessionConfig)
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
        if transcriptionSession?.provider == "openai" {
            handleOpenAIMessage(text)
            return
        }
        if transcriptionSession?.provider == "inworld" {
            handleInworldMessage(text)
            return
        }
        if transcriptionSession?.provider == "deepgram" {
            handleDeepgramMessage(text)
            return
        }
        if transcriptionSession?.provider == "soniox" {
            handleSonioxMessage(text)
            return
        }
        handleElevenLabsMessage(text)
    }

    private func handleOpenAIMessage(_ text: String) {
        guard let data = text.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let type = json["type"] as? String
        else { return }

        switch type {
        case "conversation.item.input_audio_transcription.delta":
            let itemId = json["item_id"] as? String ?? "unknown"
            let delta = json["delta"] as? String ?? ""
            guard !delta.isEmpty else { return }
            let current = (openAIInterimByItem[itemId] ?? "") + delta
            openAIInterimByItem[itemId] = current
            let lastEndMs = collectedSegments.last?.endMs ?? 0
            eventContinuation?.yield(.transcript(LiveTranscriptSegment(
                text: current,
                speaker: nil,
                isFinal: false,
                startMs: lastEndMs,
                endMs: lastEndMs,
                confidence: 0.0
            )))

        case "conversation.item.input_audio_transcription.completed":
            let itemId = json["item_id"] as? String ?? "unknown"
            let transcript = (json["transcript"] as? String ?? openAIInterimByItem[itemId] ?? "")
                .trimmingCharacters(in: .whitespacesAndNewlines)
            openAIInterimByItem[itemId] = nil
            guard !transcript.isEmpty else { return }
            lastTranscriptReceivedAt = reconnectClock.now
            let lastEndMs = collectedSegments.last?.endMs ?? 0
            let segment = LiveTranscriptSegment(
                text: transcript,
                speaker: nil,
                isFinal: true,
                startMs: lastEndMs,
                endMs: lastEndMs,
                confidence: 0.0
            )
            if let emittedSegment = collectCommittedSegment(segment, kind: .plain) {
                eventContinuation?.yield(.transcript(emittedSegment))
            }

        case "error":
            let message = (json["error"] as? [String: Any])?["message"] as? String
                ?? "OpenAI realtime transcription error"
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

        default:
            break
        }
    }

    private func handleInworldMessage(_ text: String) {
        guard let data = text.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return }

        if let transcription = json["transcription"] as? [String: Any] {
            handleInworldTranscription(transcription)
            return
        }
        if let result = json["result"] as? [String: Any],
           let transcription = result["transcription"] as? [String: Any] {
            handleInworldTranscription(transcription)
            return
        }
        if let error = json["error"] as? [String: Any] {
            let message = error["message"] as? String
                ?? error["error_message"] as? String
                ?? "Inworld realtime transcription error"
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
        }
    }

    private func handleInworldTranscription(_ payload: [String: Any]) {
        let transcript = ((payload["text"] as? String) ?? (payload["transcript"] as? String) ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard !transcript.isEmpty else { return }

        let isFinal = (payload["is_final"] as? Bool) ?? (payload["isFinal"] as? Bool) ?? false
        let confidence = (payload["confidence"] as? Double) ?? 0.0
        let words = payload["words"] as? [[String: Any]]
            ?? payload["word_timestamps"] as? [[String: Any]]
            ?? payload["wordTimestamps"] as? [[String: Any]]

        if isFinal {
            lastTranscriptReceivedAt = reconnectClock.now
            let startMs = Self.inworldTimestampMs(
                words?.first?["start_ms"]
                    ?? words?.first?["startMs"]
                    ?? words?.first?["start_time_ms"]
                    ?? words?.first?["start"]
            ) ?? (collectedSegments.last?.endMs ?? 0)
            let endMs = Self.inworldTimestampMs(
                words?.last?["end_ms"]
                    ?? words?.last?["endMs"]
                    ?? words?.last?["end_time_ms"]
                    ?? words?.last?["end"]
            ) ?? startMs
            let speaker = words?.first?["speaker"] as? String
                ?? words?.first?["speaker_id"] as? String
            let segment = LiveTranscriptSegment(
                text: transcript,
                speaker: speaker,
                isFinal: true,
                startMs: startMs,
                endMs: endMs,
                confidence: confidence
            )
            if let emittedSegment = collectCommittedSegment(segment, kind: .timestamped) {
                eventContinuation?.yield(.transcript(emittedSegment))
            }
        } else {
            let lastEndMs = collectedSegments.last?.endMs ?? 0
            eventContinuation?.yield(.transcript(LiveTranscriptSegment(
                text: transcript,
                speaker: nil,
                isFinal: false,
                startMs: lastEndMs,
                endMs: lastEndMs,
                confidence: confidence
            )))
        }
    }

    private static func inworldTimestampMs(_ value: Any?) -> Int? {
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

    private func handleDeepgramMessage(_ text: String) {
        guard let data = text.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return }

        let messageType = json["type"] as? String
        if messageType == "Results",
           let channel = json["channel"] as? [String: Any],
           let alternatives = channel["alternatives"] as? [[String: Any]],
           let alternative = alternatives.first {
            handleDeepgramTranscript(
                alternative,
                isFinal: (json["is_final"] as? Bool) ?? (json["speech_final"] as? Bool) ?? false
            )
            return
        }

        if messageType == "TurnInfo" {
            handleDeepgramTranscript(json, isFinal: (json["event"] as? String) == "EndOfTurn")
            return
        }

        if json["transcript"] is String {
            handleDeepgramTranscript(json, isFinal: true)
            return
        }

        if messageType == "Error" || json["error"] != nil {
            let message = (json["description"] as? String)
                ?? (json["message"] as? String)
                ?? (json["error"] as? String)
                ?? "Deepgram realtime transcription error"
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

    private func handleDeepgramTranscript(_ payload: [String: Any], isFinal: Bool) {
        let transcript = (payload["transcript"] as? String ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard !transcript.isEmpty else { return }

        let words = payload["words"] as? [[String: Any]] ?? []
        let startMs = Self.secondsTimestampMs(words.first?["start"]) ?? (collectedSegments.last?.endMs ?? 0)
        let endMs = Self.secondsTimestampMs(words.last?["end"]) ?? startMs
        let confidence = (payload["confidence"] as? Double)
            ?? Self.averageConfidence(words)
        let speaker = Self.speakerLabel(words.first?["speaker"])

        let segment = LiveTranscriptSegment(
            text: transcript,
            speaker: speaker,
            isFinal: isFinal,
            startMs: startMs,
            endMs: endMs,
            confidence: confidence ?? 0.0
        )
        if isFinal {
            lastTranscriptReceivedAt = reconnectClock.now
            if let emittedSegment = collectCommittedSegment(segment, kind: .timestamped) {
                eventContinuation?.yield(.transcript(emittedSegment))
            }
        } else {
            eventContinuation?.yield(.transcript(segment))
        }
    }

    private func handleSonioxMessage(_ text: String) {
        guard let data = text.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return }

        if let errorCode = json["error_code"] as? String, !errorCode.isEmpty {
            let message = json["error_message"] as? String
                ?? "Soniox realtime transcription error: \(errorCode)"
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
            return
        }

        let tokens = json["tokens"] as? [[String: Any]] ?? []
        guard !tokens.isEmpty else { return }

        let finalTokens = tokens.filter { ($0["is_final"] as? Bool) == true }
        let nonFinalTokens = tokens.filter { ($0["is_final"] as? Bool) != true }

        if let finalSegment = sonioxSegment(from: finalTokens, isFinal: true) {
            lastTranscriptReceivedAt = reconnectClock.now
            if let emittedSegment = collectCommittedSegment(finalSegment, kind: .timestamped) {
                eventContinuation?.yield(.transcript(emittedSegment))
            }
        }

        if let nonFinalSegment = sonioxSegment(from: nonFinalTokens, isFinal: false) {
            eventContinuation?.yield(.transcript(nonFinalSegment))
        }
    }

    private func sonioxSegment(from tokens: [[String: Any]], isFinal: Bool) -> LiveTranscriptSegment? {
        let speechTokens = tokens.filter { token in
            (token["translation_status"] as? String) != "translation"
                && ((token["text"] as? String)?.hasPrefix("<") != true)
        }
        let transcript = speechTokens
            .compactMap { $0["text"] as? String }
            .joined()
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard !transcript.isEmpty else { return nil }

        return LiveTranscriptSegment(
            text: transcript,
            speaker: Self.speakerLabel(speechTokens.first?["speaker"]),
            isFinal: isFinal,
            startMs: Self.integerTimestampMs(speechTokens.first?["start_ms"]) ?? (collectedSegments.last?.endMs ?? 0),
            endMs: Self.integerTimestampMs(speechTokens.last?["end_ms"]) ?? (collectedSegments.last?.endMs ?? 0),
            confidence: Self.averageConfidence(speechTokens) ?? 0.0
        )
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

    private static func secondsTimestampMs(_ value: Any?) -> Int? {
        guard let value else { return nil }
        if let double = value as? Double {
            return Int(double * 1000)
        }
        if let int = value as? Int {
            return int * 1000
        }
        if let number = value as? NSNumber {
            return Int(number.doubleValue * 1000)
        }
        if let string = value as? String, let double = Double(string) {
            return Int(double * 1000)
        }
        return nil
    }

    private static func integerTimestampMs(_ value: Any?) -> Int? {
        guard let value else { return nil }
        if let int = value as? Int {
            return int
        }
        if let number = value as? NSNumber {
            return number.intValue
        }
        if let string = value as? String, let int = Int(string) {
            return int
        }
        return nil
    }

    private static func averageConfidence(_ words: [[String: Any]]) -> Double? {
        let values = words.compactMap { word -> Double? in
            if let value = word["confidence"] as? Double {
                return value
            }
            if let number = word["confidence"] as? NSNumber {
                return number.doubleValue
            }
            return nil
        }
        guard !values.isEmpty else { return nil }
        return values.reduce(0, +) / Double(values.count)
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
            if let emittedSegment = collectCommittedSegment(segment, kind: .timestamped) {
                eventContinuation?.yield(.transcript(emittedSegment))
            }

        case "committed_transcript":
            guard let segment = committedElevenLabsSegment(
                from: json,
                textOverride: json["text"] as? String
            ) else { return }
            lastTranscriptReceivedAt = reconnectClock.now
            if let emittedSegment = collectCommittedSegment(segment, kind: .plain) {
                eventContinuation?.yield(.transcript(emittedSegment))
            }

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

    private func collectCommittedSegment(
        _ segment: LiveTranscriptSegment,
        kind: CommittedTranscriptKind
    ) -> LiveTranscriptSegment? {
        if let last = collectedSegments.last,
           let lastKind = collectedSegmentKinds.last,
           normalizedTranscriptText(last.text) == normalizedTranscriptText(segment.text) {
            if lastKind == .plain, kind == .timestamped {
                collectedSegments[collectedSegments.count - 1] = segment
                collectedSegmentKinds[collectedSegmentKinds.count - 1] = kind
                return nil
            }

            if lastKind == .timestamped, kind == .plain {
                return nil
            }
        }

        collectedSegments.append(segment)
        collectedSegmentKinds.append(kind)
        return segment
    }

    private func normalizedTranscriptText(_ text: String) -> String {
        text
            .split(whereSeparator: \.isWhitespace)
            .joined(separator: " ")
            .trimmingCharacters(in: .whitespacesAndNewlines)
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
                try await sendOpenAISessionUpdateIfNeeded(sessionConfig)
                try await sendInworldTranscribeConfigIfNeeded(sessionConfig)
                try await sendSonioxRealtimeConfigIfNeeded(sessionConfig)

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

    private func sendCommitChunkIfNeeded() async throws {
        guard endOfStreamRequested, !endOfStreamSent else { return }
        guard let webSocket else { return }

        if transcriptionSession?.provider == "openai" {
            try await webSocket.send(.string("{\"type\":\"input_audio_buffer.commit\"}"))
            endOfStreamSent = true
            reconnectEnabled = false
            cancelReconnection(clearBufferedAudio: false)
            wsLog.debug("Sent commit event to OpenAI")
            return
        }

        if transcriptionSession?.provider == "inworld" {
            try await flushInworldPendingAudio()
            try await webSocket.send(.string("{\"endTurn\":{}}"))
            try await webSocket.send(.string("{\"closeStream\":{}}"))
            endOfStreamSent = true
            reconnectEnabled = false
            cancelReconnection(clearBufferedAudio: false)
            wsLog.debug("Sent endTurn and closeStream to Inworld")
            return
        }

        if transcriptionSession?.provider == "deepgram" {
            let sampleRate = transcriptionSession?.sampleRate ?? 16_000
            let silenceBytes = max(1, sampleRate / 5) * 2
            try await webSocket.send(.data(Data(repeating: 0, count: silenceBytes)))
            try await webSocket.send(.string("{\"type\":\"CloseStream\"}"))
            endOfStreamSent = true
            reconnectEnabled = false
            cancelReconnection(clearBufferedAudio: false)
            wsLog.debug("Sent silence and CloseStream to Deepgram")
            return
        }

        if transcriptionSession?.provider == "soniox" {
            let sampleRate = transcriptionSession?.sampleRate ?? 16_000
            let silenceBytes = max(1, sampleRate / 5) * 2
            try await webSocket.send(.data(Data(repeating: 0, count: silenceBytes)))
            try await webSocket.send(.string("{\"type\":\"finalize\"}"))
            try await webSocket.send(.string(""))
            endOfStreamSent = true
            reconnectEnabled = false
            cancelReconnection(clearBufferedAudio: false)
            wsLog.debug("Sent silence, finalize, and finish signal to Soniox")
            return
        }

        try await webSocket.send(.string(makeElevenLabsAudioChunkMessage(
            data: Data(repeating: 0, count: 640),
            previousText: nil,
            commit: true
        )))

        endOfStreamSent = true
        reconnectEnabled = false
        cancelReconnection(clearBufferedAudio: false)
        wsLog.debug("Sent commit chunk to ElevenLabs")
    }

    private func cancelReconnection(clearBufferedAudio: Bool = true) {
        isReconnecting = false
        reconnectTask?.cancel()
        reconnectTask = nil
        if clearBufferedAudio {
            audioBuffer = []
            inworldPendingAudio = Data()
        }
    }

    private func sendInworldAudio(_ data: Data, forceFlush: Bool) async throws {
        guard let webSocket else {
            throw APIError.networkError(URLError(.notConnectedToInternet))
        }
        for chunk in Self.inworldAudioChunks(
            pending: &inworldPendingAudio,
            appending: data,
            forceFlush: forceFlush
        ) {
            try await webSocket.send(.string(makeInworldAudioChunkMessage(data: chunk)))
        }
    }

    private func flushInworldPendingAudio() async throws {
        guard !inworldPendingAudio.isEmpty else { return }
        try await sendInworldAudio(Data(), forceFlush: true)
    }

    static func inworldAudioChunks(
        pending: inout Data,
        appending data: Data,
        forceFlush: Bool
    ) -> [Data] {
        if !data.isEmpty {
            pending.append(data)
        }

        var chunks: [Data] = []
        while pending.count >= inworldMaxAudioChunkBytes {
            chunks.append(Data(pending.prefix(inworldMaxAudioChunkBytes)))
            pending.removeFirst(inworldMaxAudioChunkBytes)
        }

        if forceFlush {
            guard !pending.isEmpty else { return chunks }
            var chunk = pending
            pending.removeAll(keepingCapacity: true)
            if chunk.count < inworldMinAudioChunkBytes {
                chunk.append(Data(repeating: 0, count: inworldMinAudioChunkBytes - chunk.count))
            }
            chunks.append(chunk)
        } else if pending.count >= inworldMinAudioChunkBytes {
            chunks.append(pending)
            pending = Data()
        }

        return chunks
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

    func testingSetReconnectState(enabled: Bool, reconnecting: Bool) {
        reconnectEnabled = enabled
        isReconnecting = reconnecting
    }

    func testingEndOfStreamRequested() -> Bool {
        endOfStreamRequested
    }

    func testingHandleElevenLabsMessage(_ text: String) {
        handleElevenLabsMessage(text)
    }

    func testingHandleOpenAIMessage(_ text: String) {
        handleOpenAIMessage(text)
    }

    func testingHandleInworldMessage(_ text: String) {
        handleInworldMessage(text)
    }

    func testingHandleDeepgramMessage(_ text: String) {
        handleDeepgramMessage(text)
    }

    func testingHandleSonioxMessage(_ text: String) {
        handleSonioxMessage(text)
    }

    private func sendOpenAISessionUpdateIfNeeded(
        _ sessionConfig: RealtimeTranscriptionSessionConfig
    ) async throws {
        guard sessionConfig.provider == "openai", let webSocket else { return }
        try await webSocket.send(.string(makeOpenAISessionUpdateMessage(sessionConfig)))
    }

    private func sendInworldTranscribeConfigIfNeeded(
        _ sessionConfig: RealtimeTranscriptionSessionConfig
    ) async throws {
        guard sessionConfig.provider == "inworld", let webSocket else { return }
        try await webSocket.send(.string(makeInworldTranscribeConfigMessage(sessionConfig)))
    }

    private func sendSonioxRealtimeConfigIfNeeded(
        _ sessionConfig: RealtimeTranscriptionSessionConfig
    ) async throws {
        guard sessionConfig.provider == "soniox", let webSocket else { return }
        try await webSocket.send(.string(makeSonioxRealtimeConfigMessage(sessionConfig)))
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
        inworldPendingAudio = Data()

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
    }

    func testingYieldEvent(_ event: WebSocketEvent) {
        ensureEventStream()
        eventContinuation?.yield(event)
    }

    func testingInworldAudioChunks(
        pending: inout Data,
        appending data: Data,
        forceFlush: Bool
    ) -> [Data] {
        Self.inworldAudioChunks(pending: &pending, appending: data, forceFlush: forceFlush)
    }
}
