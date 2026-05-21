import Foundation
import XCTest
@testable import WaiComputerKit

final class WebSocketManagerExtendedTests: XCTestCase {

    private let decoder = JSONDecoder()

    // MARK: - collectedSegments empty on init

    func testCollectedSegmentsEmptyOnInit() async {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)
        let segments = await manager.collectedSegments
        XCTAssertTrue(segments.isEmpty, "collectedSegments should be empty immediately after init")
    }

    // MARK: - buildElevenLabsURL

    func testBuildElevenLabsURLIncludesRealtimeParams() async throws {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient, language: "multi", channels: 1)

        let url = try await manager.buildElevenLabsURL(
            token: "sutkn_123",
            model: "scribe_v2_realtime",
            commitStrategy: "vad",
            noVerbatim: true
        )
        let urlString = url.absoluteString

        XCTAssertTrue(urlString.hasPrefix("wss://api.elevenlabs.io/v1/speech-to-text/realtime?"))
        XCTAssertTrue(urlString.contains("model_id=scribe_v2_realtime"))
        XCTAssertTrue(urlString.contains("token=sutkn_123"))
        XCTAssertTrue(urlString.contains("include_timestamps=true"))
        XCTAssertTrue(urlString.contains("audio_format=pcm_16000"))
        XCTAssertTrue(urlString.contains("include_language_detection=true"))
        XCTAssertTrue(urlString.contains("commit_strategy=vad"))
        XCTAssertTrue(urlString.contains("no_verbatim=true"))
    }

    func testAudioChunkMessageIncludesExplicitCommitFlag() async throws {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)

        let message = await manager.testingMakeElevenLabsAudioChunkMessage(
            data: Data([0x01, 0x02, 0x03]),
            previousText: nil,
            commit: false
        )

        let payload = try XCTUnwrap(
            try JSONSerialization.jsonObject(with: Data(message.utf8)) as? [String: Any]
        )

        XCTAssertEqual(payload["message_type"] as? String, "input_audio_chunk")
        XCTAssertEqual(payload["commit"] as? Bool, false)
        XCTAssertEqual(payload["sample_rate"] as? Int, 16_000)
        XCTAssertNotNil(payload["audio_base_64"] as? String)
    }

    func testOpenAIAudioAppendMessageUpsamplesTo24kMonoPCM() async throws {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)

        let source = Data([0x00, 0x00, 0x64, 0x00, 0xc8, 0x00, 0x2c, 0x01])
        let message = await manager.testingMakeOpenAIAudioAppendMessage(data: source)
        let payload = try XCTUnwrap(
            try JSONSerialization.jsonObject(with: Data(message.utf8)) as? [String: Any]
        )

        XCTAssertEqual(payload["type"] as? String, "input_audio_buffer.append")
        let audio = try XCTUnwrap(payload["audio"] as? String)
        let decoded = try XCTUnwrap(Data(base64Encoded: audio))
        XCTAssertEqual(decoded.count, 12, "16 kHz mono PCM should be converted to 24 kHz mono PCM")
    }

    func testInworldRequestUsesConfiguredWebSocketURLAndBearerAuth() async throws {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)
        let config = RealtimeTranscriptionSessionConfig(
            provider: "inworld",
            token: "jwt-token",
            expiresInSeconds: 900,
            sampleRate: 16_000,
            audioFormat: "linear16_16000",
            language: "multi",
            channels: 1,
            model: "inworld/inworld-stt-1",
            websocketURL: "wss://api.inworld.ai/stt/v1/transcribe:streamBidirectional",
            authScheme: "bearer"
        )

        let request = try await manager.testingRequestForRealtimeSession(config)

        XCTAssertEqual(request.url?.host, "api.inworld.ai")
        XCTAssertEqual(request.url?.path, "/stt/v1/transcribe:streamBidirectional")
        XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer jwt-token")
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
        XCTAssertTrue(first.isEmpty)
        XCTAssertEqual(pending.count, 320)

        let second = await manager.testingInworldAudioChunks(
            pending: &pending,
            appending: Data(repeating: 0x02, count: 320),
            forceFlush: false
        )
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
        let manager = WebSocketManager(apiClient: apiClient, language: "multi", channels: 1)
        let config = RealtimeTranscriptionSessionConfig(
            provider: "inworld",
            token: "jwt-token",
            expiresInSeconds: 900,
            sampleRate: 16_000,
            audioFormat: "linear16_16000",
            language: "multi",
            channels: 1,
            model: "inworld/inworld-stt-1",
            websocketURL: "wss://api.inworld.ai/stt/v1/transcribe:streamBidirectional",
            authScheme: "bearer"
        )

        let message = await manager.testingMakeInworldTranscribeConfigMessage(config)
        let payload = try XCTUnwrap(
            try JSONSerialization.jsonObject(with: Data(message.utf8)) as? [String: Any]
        )
        let transcribeConfig = try XCTUnwrap(payload["transcribeConfig"] as? [String: Any])

        XCTAssertEqual(transcribeConfig["modelId"] as? String, "inworld/inworld-stt-1")
        XCTAssertEqual(transcribeConfig["audioEncoding"] as? String, "LINEAR16")
        XCTAssertEqual(transcribeConfig["sampleRateHertz"] as? Int, 16_000)
        XCTAssertEqual(transcribeConfig["numberOfChannels"] as? Int, 1)
        XCTAssertEqual(transcribeConfig["language"] as? String, "")
        XCTAssertNil(payload["transcribe_config"])
    }

    func testDeepgramRequestUsesConfiguredURLAndTokenAuth() async throws {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)
        let config = RealtimeTranscriptionSessionConfig(
            provider: "deepgram",
            token: "dg-token",
            expiresInSeconds: 900,
            sampleRate: 16_000,
            audioFormat: "linear16_16000",
            language: "multi",
            channels: 1,
            model: "nova-3",
            keepAliveIntervalSeconds: 8,
            commitStrategy: "vad",
            noVerbatim: false,
            websocketURL: "wss://api.deepgram.com/v1/listen?model=nova-3&encoding=linear16",
            authScheme: "bearer"
        )

        let request = try await manager.testingRequestForRealtimeSession(config)

        XCTAssertEqual(request.url?.host, "api.deepgram.com")
        XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer dg-token")
    }

    func testSonioxRequestUsesConfiguredURLWithoutAuthHeader() async throws {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)
        let config = RealtimeTranscriptionSessionConfig(
            provider: "soniox",
            token: "sx-temp",
            expiresInSeconds: 60,
            sampleRate: 16_000,
            audioFormat: "linear16_16000",
            language: "ru",
            channels: 1,
            model: "stt-rt-v4",
            websocketURL: "wss://stt-rt.soniox.com/transcribe-websocket",
            authScheme: "message_api_key"
        )

        let request = try await manager.testingRequestForRealtimeSession(config)

        XCTAssertEqual(request.url?.host, "stt-rt.soniox.com")
        XCTAssertNil(request.value(forHTTPHeaderField: "Authorization"))
    }

    func testProviderBackedSonioxRequiresServerMintedMessageApiKeySession() async throws {
        let session = ProviderBackedRealtimeSession(config: RealtimeTranscriptionSessionConfig(
            provider: "soniox",
            token: "",
            expiresInSeconds: 60,
            sampleRate: 16_000,
            audioFormat: "linear16_16000",
            language: "ru",
            channels: 1,
            model: "stt-rt-v4",
            websocketURL: "wss://stt-rt.soniox.com/transcribe-websocket",
            authScheme: "message_api_key"
        ))

        do {
            _ = try await session.testingRequest()
            XCTFail("Expected missing Soniox token to throw")
        } catch {
            XCTAssertTrue(String(describing: error).contains("Soniox realtime session is missing server-minted token"))
        }
    }

    func testProviderBackedInworldRequiresServerMintedWebSocketURL() async throws {
        let session = ProviderBackedRealtimeSession(config: RealtimeTranscriptionSessionConfig(
            provider: "inworld",
            token: "jwt-token",
            expiresInSeconds: 900,
            sampleRate: 16_000,
            audioFormat: "linear16_16000",
            language: "multi",
            channels: 1,
            model: "inworld/inworld-stt-1",
            websocketURL: nil,
            authScheme: "bearer"
        ))

        do {
            _ = try await session.testingRequest()
            XCTFail("Expected missing Inworld websocket URL to throw")
        } catch {
            XCTAssertTrue(String(describing: error).contains("Inworld realtime session is missing server-minted websocket URL"))
        }
    }

    func testProviderBackedElevenLabsUsesQueryTokenWithoutAuthorizationHeader() async throws {
        let session = ProviderBackedRealtimeSession(config: RealtimeTranscriptionSessionConfig(
            provider: "elevenlabs",
            token: "sutkn_server_minted",
            expiresInSeconds: 60,
            sampleRate: 16_000,
            audioFormat: "linear16_16000",
            language: "multi",
            channels: 1,
            model: "scribe_v2_realtime",
            websocketURL: nil,
            authScheme: "query_token"
        ))

        let request = try await session.testingRequest()

        XCTAssertEqual(request.url?.host, "api.elevenlabs.io")
        XCTAssertEqual(request.url?.query?.contains("token=sutkn_server_minted"), true)
        XCTAssertNil(request.value(forHTTPHeaderField: "Authorization"))
    }

    func testSonioxRealtimeConfigUsesTemporaryApiKeyMessageShape() async throws {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)
        let config = RealtimeTranscriptionSessionConfig(
            provider: "soniox",
            token: "sx-temp",
            expiresInSeconds: 60,
            sampleRate: 16_000,
            audioFormat: "linear16_16000",
            language: "ru",
            channels: 2,
            model: "stt-rt-v4",
            websocketURL: "wss://stt-rt.soniox.com/transcribe-websocket",
            authScheme: "message_api_key"
        )

        let message = await manager.testingMakeSonioxRealtimeConfigMessage(config)
        let payload = try XCTUnwrap(
            try JSONSerialization.jsonObject(with: Data(message.utf8)) as? [String: Any]
        )

        XCTAssertEqual(payload["api_key"] as? String, "sx-temp")
        XCTAssertEqual(payload["model"] as? String, "stt-rt-v4")
        XCTAssertEqual(payload["audio_format"] as? String, "pcm_s16le")
        XCTAssertEqual(payload["sample_rate"] as? Int, 16_000)
        XCTAssertEqual(payload["num_channels"] as? Int, 2)
        XCTAssertEqual(payload["language_hints"] as? [String], ["ru"])
        XCTAssertEqual(payload["enable_speaker_diarization"] as? Bool, true)
        XCTAssertEqual(payload["enable_endpoint_detection"] as? Bool, true)
    }

    func testDeepgramFinalTranscriptCollectsSegment() async {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)
        _ = await manager.events
        await manager.testingSetSessionConfig(RealtimeTranscriptionSessionConfig(
            provider: "deepgram",
            token: "dg-token",
            expiresInSeconds: 900,
            sampleRate: 16_000,
            audioFormat: "linear16_16000",
            language: "en",
            channels: 1,
            model: "nova-3",
            keepAliveIntervalSeconds: 8,
            commitStrategy: "vad",
            noVerbatim: false,
            websocketURL: "wss://api.deepgram.com/v1/listen?model=nova-3",
            authScheme: "bearer"
        ))

        await manager.testingHandleDeepgramMessage("""
        {
            "type":"Results",
            "is_final":true,
            "channel":{
                "alternatives":[{
                    "transcript":"Hello world.",
                    "confidence":0.91,
                    "words":[
                        {"word":"Hello","start":0.0,"end":0.4,"confidence":0.9,"speaker":0},
                        {"punctuated_word":"world.","start":0.4,"end":0.8,"confidence":0.92,"speaker":0}
                    ]
                }]
            }
        }
        """)

        let segments = await manager.collectedSegments
        XCTAssertEqual(segments.count, 1)
        XCTAssertEqual(segments.first?.text, "Hello world.")
        XCTAssertEqual(segments.first?.speaker, "Speaker 0")
        XCTAssertEqual(segments.first?.startMs, 0)
        XCTAssertEqual(segments.first?.endMs, 800)
        XCTAssertEqual(segments.first?.confidence, 0.91)
    }

    func testDeepgramFluxTurnInfoUpdatesStayInterimUntilEndOfTurn() async {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)
        _ = await manager.events
        await manager.testingSetSessionConfig(RealtimeTranscriptionSessionConfig(
            provider: "deepgram",
            token: "dg-token",
            expiresInSeconds: 900,
            sampleRate: 16_000,
            audioFormat: "linear16_16000",
            language: "ru",
            channels: 1,
            model: "flux-general-multi",
            keepAliveIntervalSeconds: nil,
            commitStrategy: "vad",
            noVerbatim: false,
            websocketURL: "wss://wai.computer/api/transcription/deepgram-proxy?model=flux-general-multi",
            authScheme: "bearer"
        ))

        await manager.testingHandleDeepgramMessage("""
        {"type":"TurnInfo","event":"Update","transcript":"Привет"}
        """)
        var segments = await manager.collectedSegments
        XCTAssertTrue(segments.isEmpty)

        await manager.testingHandleDeepgramMessage("""
        {"type":"TurnInfo","event":"EndOfTurn","transcript":"Привет мир.","words":[{"start":0.0,"end":0.4},{"start":0.4,"end":0.8}]}
        """)

        segments = await manager.collectedSegments
        XCTAssertEqual(segments.count, 1)
        XCTAssertEqual(segments.first?.text, "Привет мир.")
        XCTAssertEqual(segments.first?.startMs, 0)
        XCTAssertEqual(segments.first?.endMs, 800)
    }

    func testProviderBackedDeepgramFluxTurnInfoUpdatesStayInterimUntilEndOfTurn() async {
        let session = ProviderBackedRealtimeSession(config: RealtimeTranscriptionSessionConfig(
            provider: "deepgram",
            token: "dg-token",
            expiresInSeconds: 900,
            sampleRate: 16_000,
            audioFormat: "linear16_16000",
            language: "ru",
            channels: 1,
            model: "flux-general-multi",
            keepAliveIntervalSeconds: nil,
            commitStrategy: "vad",
            noVerbatim: false,
            websocketURL: "wss://wai.computer/api/transcription/deepgram-proxy?model=flux-general-multi",
            authScheme: "bearer"
        ))

        await session.testingHandleDeepgramMessage("""
        {"type":"TurnInfo","event":"Update","transcript":"Привет"}
        """)
        var segments = await session.testingCollectedSegments()
        XCTAssertTrue(segments.isEmpty)

        await session.testingHandleDeepgramMessage("""
        {"type":"TurnInfo","event":"EndOfTurn","transcript":"Привет мир.","words":[{"start":0.0,"end":0.4},{"start":0.4,"end":0.8}]}
        """)

        segments = await session.testingCollectedSegments()
        XCTAssertEqual(segments.count, 1)
        XCTAssertEqual(segments.first?.text, "Привет мир.")
        XCTAssertEqual(segments.first?.startMs, 0)
        XCTAssertEqual(segments.first?.endMs, 800)
    }

    func testProviderBackedSonioxFinalMarkerIsFinalizationOnly() async {
        let session = ProviderBackedRealtimeSession(config: RealtimeTranscriptionSessionConfig(
            provider: "soniox",
            token: "sx-temp",
            expiresInSeconds: 60,
            sampleRate: 16_000,
            audioFormat: "linear16_16000",
            language: "ru",
            channels: 1,
            model: "stt-rt-v4",
            websocketURL: "wss://stt-rt.soniox.com/transcribe-websocket",
            authScheme: "message_api_key"
        ))

        await session.testingHandleSonioxMessage("""
        {
            "tokens": [
                {"text":"Привет","is_final":true,"start_ms":0,"end_ms":400,"confidence":0.93},
                {"text":"<fin>","is_final":true,"start_ms":400,"end_ms":400,"confidence":1.0}
            ],
            "finished": false
        }
        """)

        let segments = await session.testingCollectedSegments()
        let sawTranscript = await session.testingHasTranscriptActivity()
        let sawFinalMarker = await session.testingHasFinalizationMarker()

        XCTAssertEqual(segments.map(\.text), ["Привет"])
        XCTAssertTrue(sawTranscript)
        XCTAssertTrue(sawFinalMarker)
    }

    func testProviderBackedInworldAudioChunkerBuffersSub20MsFrames() {
        var pending = Data()

        let first = ProviderBackedRealtimeSession.inworldAudioChunks(
            pending: &pending,
            appending: Data(repeating: 0x01, count: 320),
            forceFlush: false,
            sampleRate: 16_000,
            channels: 1
        )
        XCTAssertTrue(first.isEmpty)
        XCTAssertEqual(pending.count, 320)

        let second = ProviderBackedRealtimeSession.inworldAudioChunks(
            pending: &pending,
            appending: Data(repeating: 0x02, count: 320),
            forceFlush: false,
            sampleRate: 16_000,
            channels: 1
        )
        XCTAssertEqual(second.map(\.count), [640])
        XCTAssertTrue(pending.isEmpty)
    }

    func testProviderBackedInworldAudioChunkerPadsFinalShortFrame() {
        var pending = Data()

        _ = ProviderBackedRealtimeSession.inworldAudioChunks(
            pending: &pending,
            appending: Data(repeating: 0x01, count: 160),
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

        XCTAssertEqual(flushed.map(\.count), [640])
        XCTAssertTrue(pending.isEmpty)
    }

    func testOpenAICompletedTranscriptCollectsSegment() async {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)
        _ = await manager.events

        await manager.testingHandleOpenAIMessage("""
        {"type":"conversation.item.input_audio_transcription.delta","item_id":"item_1","delta":"Hello"}
        """)
        await manager.testingHandleOpenAIMessage("""
        {"type":"conversation.item.input_audio_transcription.completed","item_id":"item_1","transcript":"Hello world."}
        """)

        let segments = await manager.collectedSegments
        XCTAssertEqual(segments.count, 1)
        XCTAssertEqual(segments.first?.text, "Hello world.")
        XCTAssertEqual(segments.first?.isFinal, true)
    }

    func testInworldFinalTranscriptCollectsSegment() async {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)
        _ = await manager.events
        await manager.testingSetSessionConfig(RealtimeTranscriptionSessionConfig(
            provider: "inworld",
            token: "jwt-token",
            expiresInSeconds: 900,
            sampleRate: 16_000,
            audioFormat: "linear16_16000",
            language: "en",
            channels: 1,
            model: "inworld/inworld-stt-1",
            websocketURL: "wss://api.inworld.ai/stt/v1/transcribe:streamBidirectional",
            authScheme: "bearer"
        ))

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
        await manager.testingSetSessionConfig(RealtimeTranscriptionSessionConfig(
            provider: "inworld",
            token: "jwt-token",
            expiresInSeconds: 900,
            sampleRate: 16_000,
            audioFormat: "linear16_16000",
            language: "en",
            channels: 1,
            model: "inworld/inworld-stt-1",
            websocketURL: "wss://api.inworld.ai/stt/v1/transcribe:streamBidirectional",
            authScheme: "bearer"
        ))

        await manager.testingHandleInworldMessage("""
        {
            "result": {
                "transcription": {
                    "transcript": "This is an in-world real-time smoke test.",
                    "isFinal": true,
                    "wordTimestamps": []
                }
            }
        }
        """)

        let segments = await manager.collectedSegments
        XCTAssertEqual(segments.count, 1)
        XCTAssertEqual(segments.first?.text, "This is an in-world real-time smoke test.")
        XCTAssertEqual(segments.first?.isFinal, true)
    }

    func testSonioxFinalTokensCollectSegment() async {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)
        _ = await manager.events
        await manager.testingSetSessionConfig(RealtimeTranscriptionSessionConfig(
            provider: "soniox",
            token: "sx-temp",
            expiresInSeconds: 60,
            sampleRate: 16_000,
            audioFormat: "linear16_16000",
            language: "ru",
            channels: 1,
            model: "stt-rt-v4",
            websocketURL: "wss://stt-rt.soniox.com/transcribe-websocket",
            authScheme: "message_api_key"
        ))

        await manager.testingHandleSonioxMessage("""
        {
            "tokens": [
                {"text":"Привет","is_final":true,"start_ms":0,"end_ms":400,"confidence":0.93,"speaker":1},
                {"text":" мир","is_final":true,"start_ms":400,"end_ms":800,"confidence":0.95,"speaker":1},
                {"text":"<fin>","is_final":true,"start_ms":800,"end_ms":800,"confidence":1.0,"speaker":1}
            ],
            "finished": false
        }
        """)

        let segments = await manager.collectedSegments
        XCTAssertEqual(segments.count, 1)
        XCTAssertEqual(segments.first?.text, "Привет мир")
        XCTAssertEqual(segments.first?.speaker, "Speaker 1")
        XCTAssertEqual(segments.first?.endMs, 800)
        XCTAssertEqual(segments.first?.confidence ?? 0, 0.94, accuracy: 0.001)
    }

    func testTimestampedCommittedTranscriptReplacesPlainDuplicate() async {
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

        await manager.testingHandleElevenLabsMessage("""
        {"message_type":"committed_transcript","text":"Hello world."}
        """)
        await manager.testingHandleElevenLabsMessage("""
        {
            "message_type":"committed_transcript_with_timestamps",
            "text":"Hello world.",
            "words":[
                {"text":"Hello","start":0.0,"end":0.4,"type":"word","logprob":-0.1},
                {"text":" ","start":0.4,"end":0.45,"type":"spacing"},
                {"text":"world.","start":0.45,"end":0.8,"type":"word","logprob":-0.1}
            ]
        }
        """)
        await manager.disconnect()

        let events = await task.value
        let transcriptEvents = events.compactMap { event -> LiveTranscriptSegment? in
            if case .transcript(let segment) = event { return segment }
            return nil
        }
        let segments = await manager.collectedSegments

        XCTAssertEqual(transcriptEvents.count, 1)
        XCTAssertEqual(transcriptEvents.first?.text, "Hello world.")
        XCTAssertEqual(segments.count, 1)
        XCTAssertEqual(segments.first?.text, "Hello world.")
        XCTAssertEqual(segments.first?.endMs, 800)
    }

    func testRepeatedPlainCommittedTranscriptsArePreserved() async {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)

        await manager.testingHandleElevenLabsMessage("""
        {"message_type":"committed_transcript","text":"Yes."}
        """)
        await manager.testingHandleElevenLabsMessage("""
        {"message_type":"committed_transcript","text":"Yes."}
        """)

        let segments = await manager.collectedSegments
        XCTAssertEqual(segments.map(\.text), ["Yes.", "Yes."])
    }

    // MARK: - events stream survives disconnects

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

    // MARK: - WebSocketEvent pattern matching

    func testWebSocketEventPatternMatching() {
        let segment = LiveTranscriptSegment(
            text: "hello",
            speaker: "Speaker 0",
            isFinal: true,
            startMs: 0,
            endMs: 500,
            confidence: 0.99
        )

        let events: [WebSocketEvent] = [
            .connected,
            .transcript(segment),
            .disconnected(nil),
            .disconnected(URLError(.timedOut)),
            .reconnecting(attempt: 1, maxAttempts: 10),
            .reconnected,
            .reconnectionFailed(nil),
        ]

        // Verify each case matches correctly
        var connectedCount = 0
        var transcriptCount = 0
        var disconnectedCount = 0
        var reconnectingCount = 0
        var reconnectedCount = 0
        var reconnectionFailedCount = 0

        for event in events {
            switch event {
            case .connected:
                connectedCount += 1
            case .transcript(let seg):
                transcriptCount += 1
                XCTAssertEqual(seg.text, "hello")
                XCTAssertEqual(seg.confidence, 0.99)
            case .disconnected(let error):
                disconnectedCount += 1
                if disconnectedCount == 1 {
                    XCTAssertNil(error, "First disconnect should have nil error")
                } else {
                    XCTAssertNotNil(error, "Second disconnect should have an error")
                }
            case .reconnecting(let attempt, let maxAttempts):
                reconnectingCount += 1
                XCTAssertEqual(attempt, 1)
                XCTAssertEqual(maxAttempts, 10)
            case .reconnected:
                reconnectedCount += 1
            case .reconnectionFailed(let error):
                reconnectionFailedCount += 1
                XCTAssertNil(error)
            }
        }

        XCTAssertEqual(connectedCount, 1)
        XCTAssertEqual(transcriptCount, 1)
        XCTAssertEqual(disconnectedCount, 2)
        XCTAssertEqual(reconnectingCount, 1)
        XCTAssertEqual(reconnectedCount, 1)
        XCTAssertEqual(reconnectionFailedCount, 1)
    }

    // MARK: - LiveTranscriptSegment with all nil optional fields

    func testLiveTranscriptSegmentAllNilOptionals() throws {
        // Only 'speaker' is optional in the struct, but test JSON with missing speaker
        let json = """
        {
            "text": "",
            "is_final": false,
            "start_ms": 0,
            "end_ms": 0,
            "confidence": 0.0
        }
        """.data(using: .utf8)!

        let segment = try decoder.decode(LiveTranscriptSegment.self, from: json)
        XCTAssertNil(segment.speaker, "Speaker should be nil when absent from JSON")
        XCTAssertEqual(segment.text, "")
        XCTAssertFalse(segment.isFinal)
        XCTAssertEqual(segment.startMs, 0)
        XCTAssertEqual(segment.endMs, 0)
        XCTAssertEqual(segment.confidence, 0.0)
    }

    func testLiveTranscriptSegmentExplicitNullSpeaker() throws {
        let json = """
        {
            "text": "test",
            "speaker": null,
            "is_final": true,
            "start_ms": 100,
            "end_ms": 200,
            "confidence": 0.5
        }
        """.data(using: .utf8)!

        let segment = try decoder.decode(LiveTranscriptSegment.self, from: json)
        XCTAssertNil(segment.speaker, "Speaker should be nil when explicitly null")
        XCTAssertEqual(segment.text, "test")
        XCTAssertTrue(segment.isFinal)
    }

    // MARK: - WebSocketConnectionError invalidURL

    func testConnectionErrorInvalidURLDescription() {
        let error = WebSocketConnectionError.invalidURL
        XCTAssertNotNil(error.errorDescription)
        XCTAssertTrue(error.errorDescription!.contains("URL"),
                       "invalidURL description should mention URL")
    }

    // MARK: - WebSocketConnectionError disconnected with underlying error message

    func testConnectionErrorDisconnectedWithUnderlyingError() {
        let underlying = URLError(.networkConnectionLost)
        let error = WebSocketConnectionError.disconnected(underlying)
        XCTAssertNotNil(error.errorDescription)
        // The description should come from the underlying error
        XCTAssertEqual(error.errorDescription, underlying.localizedDescription)
    }

    func testConnectionErrorDisconnectedNilUsesDefault() {
        let error = WebSocketConnectionError.disconnected(nil)
        XCTAssertEqual(error.errorDescription, "The WebSocket disconnected.")
    }

    // MARK: - WebSocketConnectionError reconnectionExhausted

    func testConnectionErrorReconnectionExhausted() {
        let error = WebSocketConnectionError.reconnectionExhausted(10)
        XCTAssertNotNil(error.errorDescription)
        XCTAssertTrue(error.errorDescription!.contains("10"),
                       "reconnectionExhausted description should mention attempt count")
        XCTAssertTrue(error.errorDescription!.contains("reconnect"),
                       "reconnectionExhausted description should mention reconnect")
    }

    // MARK: - Reconnection events carry correct data

    func testReconnectingEventData() {
        let event = WebSocketEvent.reconnecting(attempt: 3, maxAttempts: 10)
        if case .reconnecting(let attempt, let maxAttempts) = event {
            XCTAssertEqual(attempt, 3)
            XCTAssertEqual(maxAttempts, 10)
        } else {
            XCTFail("Expected .reconnecting")
        }
    }

    func testReconnectedEvent() {
        let event = WebSocketEvent.reconnected
        if case .reconnected = event {} else {
            XCTFail("Expected .reconnected")
        }
    }

    func testReconnectionFailedWithError() {
        let underlying = WebSocketConnectionError.reconnectionExhausted(10)
        let event = WebSocketEvent.reconnectionFailed(underlying)
        if case .reconnectionFailed(let error) = event {
            XCTAssertNotNil(error)
            XCTAssertTrue(error is WebSocketConnectionError)
        } else {
            XCTFail("Expected .reconnectionFailed")
        }
    }

    func testReconnectionFailedWithNilError() {
        let event = WebSocketEvent.reconnectionFailed(nil)
        if case .reconnectionFailed(let error) = event {
            XCTAssertNil(error)
        } else {
            XCTFail("Expected .reconnectionFailed(nil)")
        }
    }

    // MARK: - collectedSegments preserved (not cleared by default)

    func testCollectedSegmentsEmptyAfterInit() async {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)
        let segments = await manager.collectedSegments
        XCTAssertTrue(segments.isEmpty)
    }

    // MARK: - WebSocketManager default init values

    func testWebSocketManagerDefaultLanguageAndChannels() async throws {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)

        let url = try await manager.buildElevenLabsURL(
            token: "tok",
            model: "scribe_v2_realtime",
            commitStrategy: "vad"
        )
        let urlString = url.absoluteString

        XCTAssertTrue(urlString.contains("include_language_detection=true"),
                      "Default language should enable automatic language detection")
        XCTAssertTrue(urlString.contains("commit_strategy=vad"))
    }

    func testBufferedAudioSurvivesReconnectionState() async {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)

        await manager.testingBufferAudioChunk(Data("chunk-1".utf8))
        await manager.testingBufferAudioChunk(Data("chunk-2".utf8))
        await manager.testingMarkReconnecting()

        let bufferedCount = await manager.testingBufferedAudioCount()
        XCTAssertEqual(bufferedCount, 2, "Buffered audio should survive the reconnect window")
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

        XCTAssertEqual(bufferedCount, 2, "Stopping during reconnect must not discard buffered tail audio")
        XCTAssertTrue(endRequested)
    }
}
