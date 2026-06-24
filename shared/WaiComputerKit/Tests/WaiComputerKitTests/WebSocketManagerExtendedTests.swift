import Foundation
import XCTest
@testable import WaiComputerKit

final class WebSocketManagerExtendedTests: XCTestCase {

    private func config(
        provider: String = "deepgram",
        token: String = "deepgram-temp-token",
        language: String = "multi",
        channels: Int = 1,
        model: String = "nova-3",
        websocketURL: String? = "wss://wai.computer/api/transcription/stream",
        authScheme: String? = "bearer"
    ) -> RealtimeTranscriptionSessionConfig {
        RealtimeTranscriptionSessionConfig(
            provider: provider,
            token: token,
            expiresInSeconds: 60,
            sampleRate: 16_000,
            audioFormat: "linear16",
            language: language,
            channels: channels,
            model: model,
            keepAliveIntervalSeconds: 4,
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

    func testDeepgramRequestUsesConfiguredWebSocketURLAndBearerAuth() async throws {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)

        let request = try await manager.testingRequestForRealtimeSession(config())

        XCTAssertEqual(request.url?.host, "wai.computer")
        XCTAssertEqual(request.url?.path, "/api/transcription/stream")
        XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer deepgram-temp-token")
    }

    func testRealtimeSessionRequestRejectsLegacyLiveProviders() async throws {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)

        for provider in ["legacy-provider", "removed-live-provider"] {
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
            XCTFail("Expected non-bearer Deepgram auth to be rejected")
        } catch WebSocketConnectionError.tokenFetchFailed(let message) {
            XCTAssertTrue(message.contains("Unsupported auth scheme for deepgram: basic"))
        } catch {
            XCTFail("Expected tokenFetchFailed, got \(error)")
        }
    }

    func testDeepgramFinalizeControlMessageShape() async throws {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)

        let message = await manager.testingDeepgramFinalizeMessage()
        let payload = try XCTUnwrap(
            try JSONSerialization.jsonObject(with: Data(message.utf8)) as? [String: Any]
        )

        XCTAssertEqual(payload["type"] as? String, "Finalize")
    }

    func testDeepgramAudioChunkerBuffersSub20MsFrames() async throws {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)
        var pending = Data()

        let first = await manager.testingPCMAudioChunks(
            pending: &pending,
            appending: Data(repeating: 0x01, count: 320),
            forceFlush: false,
            sampleRate: 16_000,
            channels: 1
        )
        let second = await manager.testingPCMAudioChunks(
            pending: &pending,
            appending: Data(repeating: 0x02, count: 320),
            forceFlush: false,
            sampleRate: 16_000,
            channels: 1
        )

        XCTAssertTrue(first.isEmpty)
        XCTAssertEqual(second.map(\.count), [640])
        XCTAssertTrue(pending.isEmpty)
    }

    func testDeepgramAudioChunkerPadsFinalShortFrame() async throws {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)
        var pending = Data()

        _ = await manager.testingPCMAudioChunks(
            pending: &pending,
            appending: Data(repeating: 0x01, count: 160),
            forceFlush: false,
            sampleRate: 16_000,
            channels: 1
        )
        let flushed = await manager.testingPCMAudioChunks(
            pending: &pending,
            appending: Data(),
            forceFlush: true,
            sampleRate: 16_000,
            channels: 1
        )

        XCTAssertEqual(flushed.map(\.count), [640])
        XCTAssertTrue(pending.isEmpty)
    }

    func testDeepgramFinalTranscriptCollectsSegment() async {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)
        _ = await manager.events
        await manager.testingSetSessionConfig(config(language: "en"))

        await manager.testingHandleDeepgramMessage("""
        {
            "type": "Results",
            "is_final": true,
            "start": 1.2,
            "duration": 0.8,
            "channel": {
                "alternatives": [
                    {"transcript": "Hello world.", "confidence": 0.98}
                ]
            }
        }
        """)

        let segments = await manager.collectedSegments
        XCTAssertEqual(segments.count, 1)
        XCTAssertEqual(segments.first?.text, "Hello world.")
        XCTAssertEqual(segments.first?.startMs, 1_200)
        XCTAssertEqual(segments.first?.endMs, 2_000)
        XCTAssertEqual(segments.first?.confidence, 0.98)
    }

    func testDeepgramInterimTranscriptYieldsEvent() async {
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

        await manager.testingHandleDeepgramMessage("""
        {
            "type": "Results",
            "is_final": false,
            "start": 0,
            "duration": 0.5,
            "channel": {
                "alternatives": [
                    {"transcript": "partial text", "confidence": 0.7}
                ]
            }
        }
        """)

        let segment = await task.value
        XCTAssertEqual(segment?.text, "partial text")
        XCTAssertEqual(segment?.isFinal, false)
    }

    func testDuplicateDeepgramFinalTranscriptsAreDeduped() async {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)
        _ = await manager.events
        await manager.testingSetSessionConfig(config(language: "en"))

        let message = """
        {"type":"Results","is_final":true,"channel":{"alternatives":[{"transcript":"Same final.","confidence":0.9}]}}
        """
        await manager.testingHandleDeepgramMessage(message)
        await manager.testingHandleDeepgramMessage(message)

        let segments = await manager.collectedSegments
        XCTAssertEqual(segments.map(\.text), ["Same final."])
    }

    func testDeepgramEmptyFinalizeFrameMarksProviderFinalization() async {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)
        await manager.testingSetSessionConfig(config(language: "en"))

        await manager.testingHandleDeepgramMessage("""
        {
            "type": "Results",
            "is_final": true,
            "from_finalize": true,
            "channel": {
                "alternatives": [
                    {"transcript": "", "confidence": 0}
                ]
            }
        }
        """)

        let finalized = await manager.testingProviderFinalizationReceived()
        XCTAssertTrue(finalized)
        let segments = await manager.collectedSegments
        XCTAssertTrue(segments.isEmpty)
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
        for provider in ["legacy-provider", "removed-live-provider"] {
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

    func testProviderBackedDeepgramRequiresServerMintedWebSocketURL() async throws {
        let session = ProviderBackedRealtimeSession(config: config(websocketURL: nil))

        do {
            _ = try await session.testingRequest()
            XCTFail("Expected missing Deepgram websocket URL to throw")
        } catch {
            XCTAssertTrue(String(describing: error).contains("Deepgram realtime session is missing server-minted websocket URL"))
        }
    }

    func testProviderBackedDeepgramRequiresBearerAuth() async throws {
        let session = ProviderBackedRealtimeSession(config: config(authScheme: "basic"))

        do {
            _ = try await session.testingRequest()
            XCTFail("Expected non-bearer Deepgram auth to throw")
        } catch {
            XCTAssertTrue(String(describing: error).contains("Deepgram realtime session has unsupported auth scheme: basic"))
        }
    }

    func testProviderBackedDeepgramFinalizePayload() async throws {
        let session = ProviderBackedRealtimeSession(config: config(language: "ru"))

        let payload = await session.testingDeepgramFinalizePayload()

        XCTAssertEqual(payload["type"] as? String, "Finalize")
    }

    func testProviderBackedDeepgramAudioChunkerBuffersAndPadsFinalShortFrame() async throws {
        var pending = Data()

        let first = ProviderBackedRealtimeSession.pcmAudioChunks(
            pending: &pending,
            appending: Data(repeating: 0x01, count: 320),
            forceFlush: false,
            sampleRate: 16_000,
            channels: 1
        )
        let flushed = ProviderBackedRealtimeSession.pcmAudioChunks(
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

    func testProviderBackedDeepgramFinalTranscriptCollectsSegment() async {
        let session = ProviderBackedRealtimeSession(config: config(language: "en"))

        await session.testingHandleDeepgramMessage("""
        {
            "type": "Results",
            "is_final": true,
            "channel": {
                "alternatives": [
                    {"transcript": "Provider backed final.", "confidence": 0.95}
                ]
            }
        }
        """)

        let segments = await session.testingCollectedSegments()
        XCTAssertEqual(segments.count, 1)
        XCTAssertEqual(segments.first?.text, "Provider backed final.")
        XCTAssertNil(segments.first?.speaker)
    }

    func testProviderBackedDuplicateDeepgramFinalTranscriptsAreDeduped() async {
        let session = ProviderBackedRealtimeSession(config: config(language: "en"))
        let message = """
        {"type":"Results","is_final":true,"channel":{"alternatives":[{"transcript":"Same provider final.","confidence":0.9}]}}
        """

        await session.testingHandleDeepgramMessage(message)
        await session.testingHandleDeepgramMessage(message)

        let segments = await session.testingCollectedSegments()
        XCTAssertEqual(segments.map(\.text), ["Same provider final."])
    }

    func testProviderBackedExtendedFinalTranscriptReplacesEarlierFinal() async {
        let session = ProviderBackedRealtimeSession(config: config(language: "en"))
        var events = session.events.makeAsyncIterator()

        await session.testingHandleDeepgramMessage("""
        {
            "type": "Results",
            "is_final": true,
            "start": 0.0,
            "duration": 0.8,
            "channel": {
                "alternatives": [
                    {"transcript": "Hello world", "confidence": 0.92}
                ]
            }
        }
        """)
        if case .committed(let segment)? = await events.next() {
            XCTAssertEqual(segment.text, "Hello world")
        } else {
            XCTFail("Expected initial committed event")
        }
        await session.testingHandleDeepgramMessage("""
        {
            "type": "Results",
            "is_final": true,
            "from_finalize": true,
            "start": 0.0,
            "duration": 1.2,
            "channel": {
                "alternatives": [
                    {"transcript": "Hello world today", "confidence": 0.94}
                ]
            }
        }
        """)
        if case .committedReplacement(let segment)? = await events.next() {
            XCTAssertEqual(segment.text, "Hello world today")
        } else {
            XCTFail("Expected committed replacement event")
        }

        let segments = await session.testingCollectedSegments()
        XCTAssertEqual(segments.map(\.text), ["Hello world today"])
    }

    func testWebSocketManagerExtendedFinalTranscriptReplacesEarlierFinal() async {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)
        let stream = await manager.events
        var events = stream.makeAsyncIterator()

        await manager.testingHandleDeepgramMessage("""
        {
            "type": "Results",
            "is_final": true,
            "start": 0.0,
            "duration": 0.8,
            "channel": {
                "alternatives": [
                    {"transcript": "Hello world", "confidence": 0.92}
                ]
            }
        }
        """)
        if case .transcript(let segment)? = await events.next() {
            XCTAssertEqual(segment.text, "Hello world")
        } else {
            XCTFail("Expected initial transcript event")
        }

        await manager.testingHandleDeepgramMessage("""
        {
            "type": "Results",
            "is_final": true,
            "from_finalize": true,
            "start": 0.0,
            "duration": 1.2,
            "channel": {
                "alternatives": [
                    {"transcript": "Hello world today", "confidence": 0.94}
                ]
            }
        }
        """)
        if case .transcriptReplacement(let segment)? = await events.next() {
            XCTAssertEqual(segment.text, "Hello world today")
        } else {
            XCTFail("Expected transcript replacement event")
        }

        let segments = await manager.collectedSegments
        XCTAssertEqual(segments.map(\.text), ["Hello world today"])
    }

    func testProviderBackedEmptyFinalizeFrameMarksFinalization() async {
        let session = ProviderBackedRealtimeSession(config: config(language: "en"))

        await session.testingHandleDeepgramMessage("""
        {
            "type": "Results",
            "is_final": true,
            "from_finalize": true,
            "channel": {
                "alternatives": [
                    {"transcript": "", "confidence": 0}
                ]
            }
        }
        """)

        let finalized = await session.testingHasFinalizationMarker()
        XCTAssertTrue(finalized)
        let segments = await session.testingCollectedSegments()
        XCTAssertTrue(segments.isEmpty)
    }

    func testProviderBackedConnectTimeMetadataDoesNotMarkFinalization() async {
        // Deepgram emits a Metadata frame at connection start (model and
        // sample_rate echo). Previously this was treated as a finalization
        // marker, which made `RealtimeCloseDrainPolicy.shouldKeepWaiting`
        // short-circuit on EVERY session — even though the real Results
        // frame hadn't arrived yet. Result: final words dropped.
        let session = ProviderBackedRealtimeSession(config: config(language: "en"))

        await session.testingHandleDeepgramMessage("""
        {"type":"Metadata","request_id":"abc","model_info":{"name":"nova-3"}}
        """)

        let finalized = await session.testingHasFinalizationMarker()
        XCTAssertFalse(finalized)
    }

    func testProviderBackedPostEndTurnMetadataMarksFinalization() async {
        // After we've sent {"type":"Finalize"}, a subsequent Metadata frame
        // is Deepgram's signal that there will be no more transcripts —
        // honour it so the close-drain loop can exit promptly.
        let session = ProviderBackedRealtimeSession(config: config(language: "en"))
        await session.testingSetDidSendEndTurn(true)

        await session.testingHandleDeepgramMessage("""
        {"type":"Metadata","request_id":"abc","model_info":{"name":"nova-3"}}
        """)

        let finalized = await session.testingHasFinalizationMarker()
        XCTAssertTrue(finalized)
    }

    func testProviderBackedPostEndTurnFinalResultWithoutFinalizeMarkerDoesNotCompleteFinalization() async {
        let session = ProviderBackedRealtimeSession(config: config(language: "en"))
        await session.testingSetDidSendEndTurn(true)

        await session.testingHandleDeepgramMessage("""
        {
            "type": "Results",
            "is_final": true,
            "channel": {
                "alternatives": [
                    {"transcript": "First final piece.", "confidence": 0.95}
                ]
            }
        }
        """)

        let finalized = await session.testingHasFinalizationMarker()
        let hasTranscriptActivity = await session.testingHasTranscriptActivity()
        XCTAssertFalse(finalized)
        XCTAssertTrue(hasTranscriptActivity)
        let segments = await session.testingCollectedSegments()
        XCTAssertEqual(segments.map(\.text), ["First final piece."])
    }

    func testProviderBackedFromFinalizeResultCompletesFinalization() async {
        let session = ProviderBackedRealtimeSession(config: config(language: "en"))
        await session.testingSetDidSendEndTurn(true)

        await session.testingHandleDeepgramMessage("""
        {
            "type": "Results",
            "is_final": true,
            "from_finalize": true,
            "channel": {
                "alternatives": [
                    {"transcript": "Finalized piece.", "confidence": 0.95}
                ]
            }
        }
        """)

        let finalized = await session.testingHasFinalizationMarker()
        XCTAssertTrue(finalized)
        let segments = await session.testingCollectedSegments()
        XCTAssertEqual(segments.map(\.text), ["Finalized piece."])
    }

    func testWebSocketManagerConnectTimeMetadataDoesNotMarkFinalization() async {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)

        await manager.testingHandleDeepgramMessage("""
        {"type":"Metadata","request_id":"abc","model_info":{"name":"nova-3"}}
        """)

        let finalized = await manager.testingProviderFinalizationReceived()
        XCTAssertFalse(finalized)
    }

    func testWebSocketManagerPostFinalizeMetadataMarksFinalization() async {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)
        await manager.testingSetEndOfStreamState(requested: true, sent: true)

        await manager.testingHandleDeepgramMessage("""
        {"type":"Metadata","request_id":"abc","model_info":{"name":"nova-3"}}
        """)

        let finalized = await manager.testingProviderFinalizationReceived()
        XCTAssertTrue(finalized)
    }

    func testWebSocketManagerPostEndTurnFinalResultWithoutFinalizeMarkerDoesNotCompleteFinalization() async {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)
        await manager.testingSetEndOfStreamState(requested: true, sent: true)

        await manager.testingHandleDeepgramMessage("""
        {
            "type": "Results",
            "is_final": true,
            "channel": {
                "alternatives": [
                    {"transcript": "First final piece.", "confidence": 0.95}
                ]
            }
        }
        """)

        let finalized = await manager.testingProviderFinalizationReceived()
        XCTAssertFalse(finalized)
    }

    func testWebSocketManagerFromFinalizeResultCompletesFinalization() async {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)
        await manager.testingSetEndOfStreamState(requested: true, sent: true)

        await manager.testingHandleDeepgramMessage("""
        {
            "type": "Results",
            "is_final": true,
            "from_finalize": true,
            "channel": {
                "alternatives": [
                    {"transcript": "Finalized piece.", "confidence": 0.95}
                ]
            }
        }
        """)

        let finalized = await manager.testingProviderFinalizationReceived()
        XCTAssertTrue(finalized)
    }

    func testWebSocketManagerCloseStreamDrainKeepsDelayedFinalResult() async {
        let apiClient = APIClient(baseURL: URL(string: "https://example.com")!)
        let manager = WebSocketManager(apiClient: apiClient)
        await manager.testingSetEndOfStreamState(requested: true, sent: true)

        let drain = Task {
            await manager.testingDrainCloseStreamWindow(timeout: .seconds(1))
        }
        try? await Task.sleep(for: .milliseconds(100))
        await manager.testingHandleDeepgramMessage("""
        {
            "type": "Results",
            "is_final": true,
            "channel": {
                "alternatives": [
                    {"transcript": "Tail after close stream.", "confidence": 0.95}
                ]
            }
        }
        """)
        await manager.testingHandleDeepgramMessage("""
        {"type":"Metadata","request_id":"abc","duration":1.1,"channels":1}
        """)
        await drain.value

        let finalized = await manager.testingProviderFinalizationReceived()
        let segments = await manager.collectedSegments
        XCTAssertTrue(finalized)
        XCTAssertEqual(segments.map(\.text), ["Tail after close stream."])
    }

    func testProviderBackedCloseStreamDrainKeepsDelayedFinalResult() async {
        let session = ProviderBackedRealtimeSession(config: config(language: "en"))
        await session.testingSetDidSendEndTurn(true)

        let drain = Task {
            await session.testingDrainCloseStreamWindow(timeout: .seconds(1))
        }
        try? await Task.sleep(for: .milliseconds(100))
        await session.testingHandleDeepgramMessage("""
        {
            "type": "Results",
            "is_final": true,
            "channel": {
                "alternatives": [
                    {"transcript": "Dictation tail after close stream.", "confidence": 0.95}
                ]
            }
        }
        """)
        await session.testingHandleDeepgramMessage("""
        {"type":"Metadata","request_id":"abc","duration":1.1,"channels":1}
        """)
        await drain.value

        let finalized = await session.testingHasFinalizationMarker()
        let segments = await session.testingCollectedSegments()
        XCTAssertTrue(finalized)
        XCTAssertEqual(segments.map(\.text), ["Dictation tail after close stream."])
    }
}
