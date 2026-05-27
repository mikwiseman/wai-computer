import Foundation
import XCTest
@testable import WaiComputerKit

final class WebSocketManagerExtendedTests: XCTestCase {

    private func config(
        provider: String = "openai",
        token: String = "openai-client-secret",
        language: String = "multi",
        channels: Int = 1,
        model: String = "gpt-realtime-whisper",
        websocketURL: String? = "wss://api.openai.com/v1/realtime?model=gpt-realtime-whisper",
        authScheme: String? = "bearer"
    ) -> RealtimeTranscriptionSessionConfig {
        RealtimeTranscriptionSessionConfig(
            provider: provider,
            token: token,
            expiresInSeconds: 900,
            sampleRate: 24_000,
            audioFormat: "pcm_24000",
            language: language,
            channels: channels,
            model: model,
            commitStrategy: "manual",
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

    func testOpenAIRequestUsesConfiguredWebSocketURLAndBearerAuth() async throws {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)

        let request = try await manager.testingRequestForRealtimeSession(config())

        XCTAssertEqual(request.url?.host, "api.openai.com")
        XCTAssertEqual(request.url?.path, "/v1/realtime")
        XCTAssertEqual(request.url?.query, "model=gpt-realtime-whisper")
        XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer openai-client-secret")
    }

    func testRealtimeSessionRequestRejectsLegacyLiveProviders() async throws {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)

        for provider in ["legacy-provider", "deepgram", "soniox", "elevenlabs"] {
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
            XCTFail("Expected non-bearer OpenAI auth to be rejected")
        } catch WebSocketConnectionError.tokenFetchFailed(let message) {
            XCTAssertTrue(message.contains("Unsupported auth scheme for openai: basic"))
        } catch {
            XCTFail("Expected tokenFetchFailed, got \(error)")
        }
    }

    func testOpenAIAudioAppendMessageUsesRealtimePayloadShape() async throws {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)

        let message = await manager.testingMakeOpenAIAudioAppendMessage(data: Data([0x01, 0x02, 0x03]))
        let payload = try XCTUnwrap(
            try JSONSerialization.jsonObject(with: Data(message.utf8)) as? [String: Any]
        )

        XCTAssertEqual(payload["type"] as? String, "input_audio_buffer.append")
        XCTAssertEqual(payload["audio"] as? String, Data([0x01, 0x02, 0x03]).base64EncodedString())
    }

    func testOpenAIAudioChunkerBuffersSub20MsFrames() async throws {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)
        var pending = Data()

        let first = await manager.testingPCMAudioChunks(
            pending: &pending,
            appending: Data(repeating: 0x01, count: 480),
            forceFlush: false,
            sampleRate: 24_000,
            channels: 1
        )
        let second = await manager.testingPCMAudioChunks(
            pending: &pending,
            appending: Data(repeating: 0x02, count: 480),
            forceFlush: false,
            sampleRate: 24_000,
            channels: 1
        )

        XCTAssertTrue(first.isEmpty)
        XCTAssertEqual(second.map(\.count), [960])
        XCTAssertTrue(pending.isEmpty)
    }

    func testOpenAIAudioChunkerPadsFinalShortFrame() async throws {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)
        var pending = Data()

        _ = await manager.testingPCMAudioChunks(
            pending: &pending,
            appending: Data(repeating: 0x01, count: 240),
            forceFlush: false,
            sampleRate: 24_000,
            channels: 1
        )
        let flushed = await manager.testingPCMAudioChunks(
            pending: &pending,
            appending: Data(),
            forceFlush: true,
            sampleRate: 24_000,
            channels: 1
        )

        XCTAssertEqual(flushed.map(\.count), [960])
        XCTAssertTrue(pending.isEmpty)
    }

    func testOpenAISessionUpdateUsesRealtimeTranscriptionShape() async throws {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(
            apiClient: apiClient,
            language: "multi",
            channels: 1,
            keyTerms: ["WaiComputer", "waicomputer", "Anthropic"]
        )

        let message = await manager.testingMakeOpenAISessionUpdateMessage(config())
        let payload = try XCTUnwrap(
            try JSONSerialization.jsonObject(with: Data(message.utf8)) as? [String: Any]
        )
        let session = try XCTUnwrap(payload["session"] as? [String: Any])
        let audio = try XCTUnwrap(session["audio"] as? [String: Any])
        let input = try XCTUnwrap(audio["input"] as? [String: Any])
        let format = try XCTUnwrap(input["format"] as? [String: Any])
        let transcription = try XCTUnwrap(input["transcription"] as? [String: Any])

        XCTAssertEqual(payload["type"] as? String, "session.update")
        XCTAssertEqual(session["type"] as? String, "transcription")
        XCTAssertEqual(format["type"] as? String, "audio/pcm")
        XCTAssertEqual(format["rate"] as? Int, 24_000)
        XCTAssertEqual(transcription["model"] as? String, "gpt-realtime-whisper")
        XCTAssertNil(transcription["language"])
        XCTAssertTrue(input["turn_detection"] is NSNull)
        XCTAssertNil(transcription["prompts"])
    }

    func testOpenAISessionUpdateNormalisesLanguageHint() async throws {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)

        let message = await manager.testingMakeOpenAISessionUpdateMessage(config(language: "ru-RU"))
        let payload = try XCTUnwrap(
            try JSONSerialization.jsonObject(with: Data(message.utf8)) as? [String: Any]
        )
        let session = try XCTUnwrap(payload["session"] as? [String: Any])
        let audio = try XCTUnwrap(session["audio"] as? [String: Any])
        let input = try XCTUnwrap(audio["input"] as? [String: Any])
        let transcription = try XCTUnwrap(input["transcription"] as? [String: Any])

        XCTAssertEqual(transcription["language"] as? String, "ru")
    }

    func testOpenAICompletedTranscriptCollectsSegment() async {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)
        _ = await manager.events
        await manager.testingSetSessionConfig(config(language: "en"))

        await manager.testingHandleOpenAIMessage("""
        {
            "type": "conversation.item.input_audio_transcription.completed",
            "item_id": "item_1",
            "transcript": "Hello world."
        }
        """)

        let segments = await manager.collectedSegments
        XCTAssertEqual(segments.count, 1)
        XCTAssertEqual(segments.first?.text, "Hello world.")
        XCTAssertNil(segments.first?.speaker)
        XCTAssertEqual(segments.first?.confidence, 0)
    }

    func testOpenAIDeltaTranscriptYieldsInterimEvent() async {
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

        await manager.testingHandleOpenAIMessage("""
        {
            "type": "conversation.item.input_audio_transcription.delta",
            "item_id": "item_1",
            "delta": "partial text"
        }
        """)

        let segment = await task.value
        XCTAssertEqual(segment?.text, "partial text")
        XCTAssertEqual(segment?.isFinal, false)
    }

    func testDuplicateOpenAIFinalTranscriptsAreDeduped() async {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)
        _ = await manager.events
        await manager.testingSetSessionConfig(config(language: "en"))

        await manager.testingHandleOpenAIMessage("""
        {"type":"conversation.item.input_audio_transcription.completed","item_id":"a","transcript":"Same final."}
        """)
        await manager.testingHandleOpenAIMessage("""
        {"type":"conversation.item.input_audio_transcription.completed","item_id":"b","transcript":"Same final."}
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
        for provider in ["legacy-provider", "deepgram", "soniox", "elevenlabs"] {
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

    func testProviderBackedOpenAIRequiresServerMintedWebSocketURL() async throws {
        let session = ProviderBackedRealtimeSession(config: config(websocketURL: nil))

        do {
            _ = try await session.testingRequest()
            XCTFail("Expected missing OpenAI websocket URL to throw")
        } catch {
            XCTAssertTrue(String(describing: error).contains("OpenAI realtime session is missing server-minted websocket URL"))
        }
    }

    func testProviderBackedOpenAIRequiresBearerAuth() async throws {
        let session = ProviderBackedRealtimeSession(config: config(authScheme: "basic"))

        do {
            _ = try await session.testingRequest()
            XCTFail("Expected non-bearer OpenAI auth to throw")
        } catch {
            XCTAssertTrue(String(describing: error).contains("OpenAI realtime session has unsupported auth scheme: basic"))
        }
    }

    func testProviderBackedOpenAISessionUpdateUsesRealtimeTranscriptionShape() async throws {
        let session = ProviderBackedRealtimeSession(
            config: config(language: "ru-RU"),
            keyTerms: ["Mikhail", "mikhail", "WaiComputer"]
        )

        let payload = await session.testingOpenAISessionUpdatePayload()
        let sessionPayload = try XCTUnwrap(payload["session"] as? [String: Any])
        let audio = try XCTUnwrap(sessionPayload["audio"] as? [String: Any])
        let input = try XCTUnwrap(audio["input"] as? [String: Any])
        let format = try XCTUnwrap(input["format"] as? [String: Any])
        let transcription = try XCTUnwrap(input["transcription"] as? [String: Any])

        XCTAssertEqual(sessionPayload["type"] as? String, "transcription")
        XCTAssertEqual(format["type"] as? String, "audio/pcm")
        XCTAssertEqual(format["rate"] as? Int, 24_000)
        XCTAssertEqual(transcription["model"] as? String, "gpt-realtime-whisper")
        XCTAssertEqual(transcription["language"] as? String, "ru")
        XCTAssertTrue(input["turn_detection"] is NSNull)
        XCTAssertNil(transcription["prompts"])
    }

    func testProviderBackedOpenAIAudioChunkerBuffersAndPadsFinalShortFrame() async throws {
        var pending = Data()

        let first = ProviderBackedRealtimeSession.pcmAudioChunks(
            pending: &pending,
            appending: Data(repeating: 0x01, count: 480),
            forceFlush: false,
            sampleRate: 24_000,
            channels: 1
        )
        let flushed = ProviderBackedRealtimeSession.pcmAudioChunks(
            pending: &pending,
            appending: Data(),
            forceFlush: true,
            sampleRate: 24_000,
            channels: 1
        )

        XCTAssertTrue(first.isEmpty)
        XCTAssertEqual(flushed.map(\.count), [960])
        XCTAssertTrue(pending.isEmpty)
    }

    func testProviderBackedOpenAICompletedTranscriptCollectsSegment() async {
        let session = ProviderBackedRealtimeSession(config: config(language: "en"))

        await session.testingHandleOpenAIMessage("""
        {
            "type": "conversation.item.input_audio_transcription.completed",
            "item_id": "item_1",
            "transcript": "Provider backed final."
        }
        """)

        let segments = await session.testingCollectedSegments()
        XCTAssertEqual(segments.count, 1)
        XCTAssertEqual(segments.first?.text, "Provider backed final.")
        XCTAssertNil(segments.first?.speaker)
    }

    func testProviderBackedDuplicateOpenAIFinalTranscriptsAreDeduped() async {
        let session = ProviderBackedRealtimeSession(config: config(language: "en"))

        await session.testingHandleOpenAIMessage("""
        {"type":"conversation.item.input_audio_transcription.completed","item_id":"a","transcript":"Same provider final."}
        """)
        await session.testingHandleOpenAIMessage("""
        {"type":"conversation.item.input_audio_transcription.completed","item_id":"b","transcript":"Same provider final."}
        """)

        let segments = await session.testingCollectedSegments()
        XCTAssertEqual(segments.map(\.text), ["Same provider final."])
    }
}
