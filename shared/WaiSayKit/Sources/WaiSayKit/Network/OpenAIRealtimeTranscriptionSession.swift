import Foundation
import os

private let openAILog = Logger(subsystem: "com.waisay.kit", category: "openaiRealtime")

public actor OpenAIRealtimeTranscriptionSession: ProviderSession {
    public nonisolated let events: AsyncStream<TranscriptionEvent>

    private let eventContinuation: AsyncStream<TranscriptionEvent>.Continuation
    private let websocketURL: URL
    private let bearerToken: String
    private let model: String
    private let language: String
    private let sampleRate: Int
    private let urlSession: URLSession

    private var webSocket: URLSessionWebSocketTask?
    private var receiveTask: Task<Void, Never>?
    private var collectedSegments: [LiveTranscriptSegment] = []
    private var interimByItem: [String: String] = [:]
    private var isClosing = false

    public init(
        websocketURL: URL,
        bearerToken: String,
        model: String,
        language: String,
        sampleRate: Int = 24_000,
        urlSession: URLSession = .shared
    ) {
        self.websocketURL = websocketURL
        self.bearerToken = bearerToken
        self.model = model
        self.language = language
        self.sampleRate = sampleRate
        self.urlSession = urlSession

        let (stream, continuation) = AsyncStream.makeStream(of: TranscriptionEvent.self)
        self.events = stream
        self.eventContinuation = continuation
    }

    public func open() async throws {
        guard webSocket == nil else { return }
        var request = URLRequest(url: websocketURL)
        request.timeoutInterval = 30
        request.setValue("Bearer \(bearerToken)", forHTTPHeaderField: "Authorization")

        let task = urlSession.webSocketTask(with: request)
        webSocket = task
        task.resume()

        startReceiveLoop(for: task)
        try await task.send(.string(Self.encodeJSON(sessionUpdatePayload())))
        eventContinuation.yield(.opened(sessionId: "openai"))
    }

    public func send(pcm16: Data) async throws {
        guard let webSocket else {
            throw ProviderError.transcriberInternal(message: "OpenAI socket is not open")
        }
        let payload: [String: Any] = [
            "type": "input_audio_buffer.append",
            "audio": pcm16.base64EncodedString()
        ]
        try await webSocket.send(.string(Self.encodeJSON(payload)))
    }

    public func endTurn() async throws {
        guard let webSocket else { return }
        try await webSocket.send(.string(Self.encodeJSON(["type": "input_audio_buffer.commit"])))
    }

    public func close(timeout: Duration = .seconds(5)) async throws -> [LiveTranscriptSegment] {
        guard !isClosing else { return collectedSegments }
        isClosing = true
        try? await endTurn()

        let deadline = ContinuousClock().now + timeout
        while ContinuousClock().now < deadline, webSocket?.closeCode == .invalid {
            try? await Task.sleep(for: .milliseconds(100))
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
        webSocket?.cancel(with: .goingAway, reason: nil)
        receiveTask?.cancel()
        eventContinuation.yield(.closed(reason: .clientRequested))
        eventContinuation.finish()
    }

    private func sessionUpdatePayload() -> [String: Any] {
        var transcription: [String: Any] = ["model": model]
        if !language.isEmpty, language != "multi" {
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
                            "rate": sampleRate
                        ],
                        "transcription": transcription,
                        "turn_detection": NSNull()
                    ]
                ]
            ]
        ]
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
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let type = json["type"] as? String
        else { return }

        switch type {
        case "conversation.item.input_audio_transcription.delta":
            let itemId = json["item_id"] as? String ?? "unknown"
            let delta = json["delta"] as? String ?? ""
            guard !delta.isEmpty else { return }
            let current = (interimByItem[itemId] ?? "") + delta
            interimByItem[itemId] = current
            eventContinuation.yield(.interim(text: current, language: nil))
        case "conversation.item.input_audio_transcription.completed":
            let itemId = json["item_id"] as? String ?? "unknown"
            let transcript = (json["transcript"] as? String ?? interimByItem[itemId] ?? "")
                .trimmingCharacters(in: .whitespacesAndNewlines)
            interimByItem[itemId] = nil
            guard !transcript.isEmpty else { return }
            let segment = LiveTranscriptSegment(
                text: transcript,
                speaker: nil,
                isFinal: true,
                startMs: collectedSegments.last?.endMs ?? 0,
                endMs: collectedSegments.last?.endMs ?? 0,
                confidence: 0.0
            )
            collectedSegments.append(segment)
            eventContinuation.yield(.committed(segment))
        case "error":
            let message = (json["error"] as? [String: Any])?["message"] as? String
            eventContinuation.yield(.providerWarning(.transcriberInternal(message: message ?? "OpenAI realtime error")))
        default:
            break
        }
    }

    private func handleSocketError(_ error: Error) {
        openAILog.error("[OpenAI] WebSocket error: \(error.localizedDescription, privacy: .public)")
        eventContinuation.yield(.closed(reason: .networkLost))
        eventContinuation.finish()
    }

    static func encodeJSON(_ payload: [String: Any]) -> String {
        let data = try? JSONSerialization.data(withJSONObject: payload, options: [])
        return String(data: data ?? Data("{}".utf8), encoding: .utf8) ?? "{}"
    }

    public func testingSessionUpdatePayload() -> String {
        Self.encodeJSON(sessionUpdatePayload())
    }
}
