import Foundation
import XCTest
@testable import WaiComputerKit

final class WebSocketManagerExtendedTests: XCTestCase {

    private func config(
        provider: String = "inworld",
        token: String = "jwt-token",
        language: String = "multi",
        channels: Int = 1,
        model: String = "inworld/inworld-stt-1",
        websocketURL: String? = "wss://api.inworld.ai/stt/v1/transcribe:streamBidirectional",
        authScheme: String? = "bearer"
    ) -> RealtimeTranscriptionSessionConfig {
        RealtimeTranscriptionSessionConfig(
            provider: provider,
            token: token,
            expiresInSeconds: 900,
            sampleRate: 16_000,
            audioFormat: "linear16_16000",
            language: language,
            channels: channels,
            model: model,
            websocketURL: websocketURL,
            authScheme: authScheme
        )
    }

    func testCollectedSegmentsEmptyOnInit() async {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)

        let segments = await manager.collectedSegments

        XCTAssertTrue(segments.isEmpty)
    }

    func testInworldRequestUsesConfiguredWebSocketURLAndBearerAuth() async throws {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)

        let request = try await manager.testingRequestForRealtimeSession(config())

        XCTAssertEqual(request.url?.host, "api.inworld.ai")
        XCTAssertEqual(request.url?.path, "/stt/v1/transcribe:streamBidirectional")
        XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer jwt-token")
    }

    func testRealtimeSessionRequestRejectsLegacyLiveProviders() async throws {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)

        for provider in ["openai", "deepgram", "soniox", "elevenlabs"] {
            do {
                _ = try await manager.testingRequestForRealtimeSession(config(
                    provider: provider,
                    token: "legacy-token",
                    model: "legacy-model",
                    websocketURL: "wss://legacy.example.test/stream"
                ))
                XCTFail("Expected \(provider) live STT config to be rejected")
            } catch WebSocketConnectionError.tokenFetchFailed(let message) {
                XCTAssertTrue(message.contains("Unsupported transcription provider: \(provider)"))
            } catch {
                XCTFail("Expected tokenFetchFailed for \(provider), got \(error)")
            }
        }
    }

    func testRealtimeSessionRequestRequiresBearerAuth() async throws {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)

        do {
            _ = try await manager.testingRequestForRealtimeSession(config(authScheme: "basic"))
            XCTFail("Expected non-bearer Inworld auth to be rejected")
        } catch WebSocketConnectionError.tokenFetchFailed(let message) {
            XCTAssertTrue(message.contains("Unsupported auth scheme for inworld: basic"))
        } catch {
            XCTFail("Expected tokenFetchFailed, got \(error)")
        }
    }

    func testInworldAudioChunkMessageUsesProviderPayloadShape() async throws {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)

        let message = await manager.testingMakeInworldAudioChunkMessage(data: Data([0x01, 0x02, 0x03]))
        let payload = try XCTUnwrap(
            try JSONSerialization.jsonObject(with: Data(message.utf8)) as? [String: Any]
        )
        let audioChunk = try XCTUnwrap(payload["audioChunk"] as? [String: Any])

        XCTAssertEqual(audioChunk["content"] as? String, Data([0x01, 0x02, 0x03]).base64EncodedString())
    }

    func testInworldAudioChunkerBuffersSub20MsFrames() async throws {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)
        var pending = Data()

        let first = await manager.testingInworldAudioChunks(
            pending: &pending,
            appending: Data(repeating: 0x01, count: 320),
            forceFlush: false
        )
        let second = await manager.testingInworldAudioChunks(
            pending: &pending,
            appending: Data(repeating: 0x02, count: 320),
            forceFlush: false
        )

        XCTAssertTrue(first.isEmpty)
        XCTAssertEqual(second.map(\.count), [640])
        XCTAssertTrue(pending.isEmpty)
    }

    func testInworldAudioChunkerPadsFinalShortFrame() async throws {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)
        var pending = Data()

        _ = await manager.testingInworldAudioChunks(
            pending: &pending,
            appending: Data(repeating: 0x01, count: 160),
            forceFlush: false
        )
        let flushed = await manager.testingInworldAudioChunks(
            pending: &pending,
            appending: Data(),
            forceFlush: true
        )

        XCTAssertEqual(flushed.map(\.count), [640])
        XCTAssertTrue(pending.isEmpty)
    }

    func testInworldTranscribeConfigUsesCurrentCamelCaseWireShape() async throws {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(
            apiClient: apiClient,
            language: "multi",
            channels: 1,
            keyTerms: ["WaiComputer", "waicomputer", "Anthropic"]
        )

        let message = await manager.testingMakeInworldTranscribeConfigMessage(config())
        let payload = try XCTUnwrap(
            try JSONSerialization.jsonObject(with: Data(message.utf8)) as? [String: Any]
        )
        let transcribeConfig = try XCTUnwrap(payload["transcribeConfig"] as? [String: Any])

        XCTAssertEqual(transcribeConfig["modelId"] as? String, "inworld/inworld-stt-1")
        XCTAssertEqual(transcribeConfig["audioEncoding"] as? String, "LINEAR16")
        XCTAssertEqual(transcribeConfig["sampleRateHertz"] as? Int, 16_000)
        XCTAssertEqual(transcribeConfig["numberOfChannels"] as? Int, 1)
        XCTAssertEqual(transcribeConfig["language"] as? String, "")
        XCTAssertEqual(transcribeConfig["prompts"] as? [String], ["WaiComputer", "Anthropic"])
        XCTAssertNil(transcribeConfig["context"])
        XCTAssertNil(payload["transcribe_config"])
    }

    func testInworldFinalTranscriptCollectsSegment() async {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)
        _ = await manager.events
        await manager.testingSetSessionConfig(config(language: "en"))

        await manager.testingHandleInworldMessage("""
        {
            "transcription": {
                "text": "Hello world.",
                "is_final": true,
                "confidence": 0.92,
                "words": [
                    {"start_ms": 100, "end_ms": 400, "speaker": "Speaker 1"},
                    {"start_ms": 450, "end_ms": 900, "speaker": "Speaker 1"}
                ]
            }
        }
        """)

        let segments = await manager.collectedSegments
        XCTAssertEqual(segments.count, 1)
        XCTAssertEqual(segments.first?.text, "Hello world.")
        XCTAssertEqual(segments.first?.speaker, "Speaker 1")
        XCTAssertEqual(segments.first?.startMs, 100)
        XCTAssertEqual(segments.first?.endMs, 900)
        XCTAssertEqual(segments.first?.confidence, 0.92)
    }

    func testInworldWrappedResultTranscriptCollectsSegment() async {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)
        _ = await manager.events
        await manager.testingSetSessionConfig(config(language: "en"))

        await manager.testingHandleInworldMessage("""
        {
            "result": {
                "transcription": {
                    "transcript": "This is an Inworld realtime smoke test.",
                    "isFinal": true,
                    "wordTimestamps": []
                }
            }
        }
        """)

        let segments = await manager.collectedSegments
        XCTAssertEqual(segments.count, 1)
        XCTAssertEqual(segments.first?.text, "This is an Inworld realtime smoke test.")
        XCTAssertEqual(segments.first?.isFinal, true)
    }

    func testInworldInterimTranscriptYieldsEvent() async {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)
        let stream = await manager.events
        await manager.testingSetSessionConfig(config(language: "en"))

        let task = Task<LiveTranscriptSegment?, Never> {
            var iterator = stream.makeAsyncIterator()
            while let event = await iterator.next() {
                if case .transcript(let segment) = event {
                    return segment
                }
            }
            return nil
        }

        await manager.testingHandleInworldMessage("""
        {"transcription":{"transcript":"partial text","isFinal":false,"confidence":0.3}}
        """)

        let segment = await task.value
        XCTAssertEqual(segment?.text, "partial text")
        XCTAssertEqual(segment?.isFinal, false)
    }

    func testDuplicateInworldFinalTranscriptsAreDeduped() async {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)
        _ = await manager.events
        await manager.testingSetSessionConfig(config(language: "en"))

        await manager.testingHandleInworldMessage("""
        {"transcription":{"transcript":"Same final.","isFinal":true,"wordTimestamps":[]}}
        """)
        await manager.testingHandleInworldMessage("""
        {"transcription":{"transcript":"Same final.","isFinal":true,"wordTimestamps":[]}}
        """)

        let segments = await manager.collectedSegments
        XCTAssertEqual(segments.map(\.text), ["Same final."])
    }

    func testEventStreamRemainsUsableAfterDisconnect() async {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)
        let stream = await manager.events

        let task = Task<[WebSocketEvent], Never> {
            var iterator = stream.makeAsyncIterator()
            var events: [WebSocketEvent] = []
            if let first = await iterator.next() {
                events.append(first)
            }
            if let second = await iterator.next() {
                events.append(second)
            }
            return events
        }

        await manager.disconnect()
        await manager.testingYieldEvent(.reconnected)

        let events = await task.value
        XCTAssertEqual(events.count, 2)
        if case .disconnected = events[0] {} else {
            XCTFail("Expected disconnect event first")
        }
        if case .reconnected = events[1] {} else {
            XCTFail("Expected a later event after disconnect")
        }
    }

    func testBufferedAudioSurvivesReconnectionState() async {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)

        await manager.testingBufferAudioChunk(Data("chunk-1".utf8))
        await manager.testingBufferAudioChunk(Data("chunk-2".utf8))
        await manager.testingMarkReconnecting()

        let bufferedCount = await manager.testingBufferedAudioCount()
        XCTAssertEqual(bufferedCount, 2)
    }

    func testSendEndDuringReconnectPreservesBufferedTail() async throws {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)

        await manager.testingBufferAudioChunk(Data("tail-1".utf8))
        await manager.testingBufferAudioChunk(Data("tail-2".utf8))
        await manager.testingSetReconnectState(enabled: true, reconnecting: true)

        try await manager.sendEnd()
        let bufferedCount = await manager.testingBufferedAudioCount()
        let endRequested = await manager.testingEndOfStreamRequested()

        XCTAssertEqual(bufferedCount, 2)
        XCTAssertTrue(endRequested)
    }

    func testStopRealtimeStreamingForLocalRecordingDropsBufferedAudioAndMakesSendThrow() async throws {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)

        await manager.testingSetReconnectState(enabled: true, reconnecting: true)
        await manager.testingBufferAudioChunk(Data("buffered-live-audio".utf8))

        await manager.stopRealtimeStreamingForLocalRecording(reason: "reconnectionFailed")

        let bufferedCount = await manager.testingBufferedAudioCount()
        XCTAssertEqual(bufferedCount, 0)
        do {
            try await manager.sendAudio(data: Data("new-live-audio".utf8))
            XCTFail("sendAudio should fail after realtime streaming is stopped")
        } catch {
            XCTAssertNotNil(error)
        }
    }

    func testProviderBackedRequestRejectsLegacyLiveProviders() async throws {
        for provider in ["openai", "deepgram", "soniox", "elevenlabs"] {
            let session = ProviderBackedRealtimeSession(config: config(
                provider: provider,
                token: "legacy-token",
                model: "legacy-model",
                websocketURL: "wss://legacy.example.test/stream"
            ))

            do {
                _ = try await session.testingRequest()
                XCTFail("Expected \(provider) ProviderBackedRealtimeSession to be rejected")
            } catch {
                XCTAssertTrue(String(describing: error).contains(provider))
            }
        }
    }

    func testProviderBackedInworldRequiresServerMintedWebSocketURL() async throws {
        let session = ProviderBackedRealtimeSession(config: config(websocketURL: nil))

        do {
            _ = try await session.testingRequest()
            XCTFail("Expected missing Inworld websocket URL to throw")
        } catch {
            XCTAssertTrue(String(describing: error).contains("Inworld realtime session is missing server-minted websocket URL"))
        }
    }

    func testProviderBackedInworldRequiresBearerAuth() async throws {
        let session = ProviderBackedRealtimeSession(config: config(authScheme: "basic"))

        do {
            _ = try await session.testingRequest()
            XCTFail("Expected non-bearer Inworld auth to throw")
        } catch {
            XCTAssertTrue(String(describing: error).contains("Inworld realtime session has unsupported auth scheme: basic"))
        }
    }

    func testProviderBackedInworldTranscribeConfigUsesPromptsField() async throws {
        let session = ProviderBackedRealtimeSession(
            config: config(language: "ru-RU"),
            keyTerms: ["Mikhail", "mikhail", "WaiComputer"]
        )

        let payload = await session.testingInworldTranscribeConfigPayload()
        let transcribeConfig = try XCTUnwrap(payload["transcribeConfig"] as? [String: Any])

        XCTAssertEqual(transcribeConfig["language"] as? String, "ru")
        XCTAssertEqual(transcribeConfig["prompts"] as? [String], ["Mikhail", "WaiComputer"])
        XCTAssertNil(transcribeConfig["context"])
    }

    func testProviderBackedInworldAudioChunkerBuffersAndPadsFinalShortFrame() async throws {
        var pending = Data()

        let first = ProviderBackedRealtimeSession.inworldAudioChunks(
            pending: &pending,
            appending: Data(repeating: 0x01, count: 320),
            forceFlush: false,
            sampleRate: 16_000,
            channels: 1
        )
        let flushed = ProviderBackedRealtimeSession.inworldAudioChunks(
            pending: &pending,
            appending: Data(),
            forceFlush: true,
            sampleRate: 16_000,
            channels: 1
        )

        XCTAssertTrue(first.isEmpty)
        XCTAssertEqual(flushed.map(\.count), [640])
        XCTAssertTrue(pending.isEmpty)
    }

    func testProviderBackedInworldFinalTranscriptCollectsSegment() async {
        let session = ProviderBackedRealtimeSession(config: config(language: "en"))

        await session.testingHandleInworldMessage("""
        {
            "transcription": {
                "transcript": "Provider backed final.",
                "isFinal": true,
                "wordTimestamps": [
                    {"start": 0.2, "end": 0.9, "speaker": "Speaker 1"}
                ]
            }
        }
        """)

        let segments = await session.testingCollectedSegments()
        XCTAssertEqual(segments.count, 1)
        XCTAssertEqual(segments.first?.text, "Provider backed final.")
        XCTAssertEqual(segments.first?.speaker, "Speaker 1")
        XCTAssertEqual(segments.first?.startMs, 200)
        XCTAssertEqual(segments.first?.endMs, 900)
    }

    func testProviderBackedDuplicateInworldFinalTranscriptsAreDeduped() async {
        let session = ProviderBackedRealtimeSession(config: config(language: "en"))

        await session.testingHandleInworldMessage("""
        {"transcription":{"transcript":"Same provider final.","isFinal":true,"wordTimestamps":[]}}
        """)
        await session.testingHandleInworldMessage("""
        {"transcription":{"transcript":"Same provider final.","isFinal":true,"wordTimestamps":[]}}
        """)

        let segments = await session.testingCollectedSegments()
        XCTAssertEqual(segments.map(\.text), ["Same provider final."])
    }
}
