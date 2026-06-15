package `is`.waiwai.computer.recording

import `is`.waiwai.computer.data.RealtimeTranscriptionSessionConfig
import `is`.waiwai.computer.data.WaiApi
import io.mockk.coEvery
import io.mockk.mockk
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.test.runTest
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class WebSocketManagerTest {
    private val api = mockk<WaiApi>(relaxed = true)

    @Test
    fun `close drain waits for provider finalization marker after client close`() {
        val startedAt = 1_000L
        assertTrue(
            DeepgramRealtimeWebSocketManager.shouldKeepWaitingForCloseDrain(
                nowMs = startedAt + 2_499,
                deadlineMs = startedAt + 5_000,
                startedAtMs = startedAt,
                lastTranscriptEventAtMs = null,
                finalizationMarkerReceived = false,
            ),
        )
        assertFalse(
            DeepgramRealtimeWebSocketManager.shouldKeepWaitingForCloseDrain(
                nowMs = startedAt + 650,
                deadlineMs = startedAt + 5_000,
                startedAtMs = startedAt,
                lastTranscriptEventAtMs = null,
                finalizationMarkerReceived = true,
            ),
        )
    }

    @Test
    fun `close drain waits for quiet window after transcript activity`() {
        val startedAt = 1_000L
        val transcriptAt = startedAt + 700
        assertTrue(
            DeepgramRealtimeWebSocketManager.shouldKeepWaitingForCloseDrain(
                nowMs = transcriptAt + 899,
                deadlineMs = startedAt + 5_000,
                startedAtMs = startedAt,
                lastTranscriptEventAtMs = transcriptAt,
                finalizationMarkerReceived = false,
            ),
        )
        assertFalse(
            DeepgramRealtimeWebSocketManager.shouldKeepWaitingForCloseDrain(
                nowMs = transcriptAt + 900,
                deadlineMs = startedAt + 5_000,
                startedAtMs = startedAt,
                lastTranscriptEventAtMs = transcriptAt,
                finalizationMarkerReceived = false,
            ),
        )
    }

    @Test
    fun `build Deepgram request uses bearer auth and configured websocket URL`() {
        val manager = DeepgramRealtimeWebSocketManager(api, language = "multi")
        val request = manager.buildDeepgramRequest(deepgramConfig())

        assertEquals("wai.computer", request.url.host)
        assertEquals("/api/transcription/stream", request.url.encodedPath)
        assertEquals("Bearer deepgram-temporary-token", request.header("Authorization"))
    }

    @Test
    fun `build Deepgram request rejects removed live providers`() {
        val manager = DeepgramRealtimeWebSocketManager(api, language = "multi")

        assertThrows(IllegalArgumentException::class.java) {
            manager.buildDeepgramRequest(deepgramConfig(provider = "removed-provider"))
        }
    }

    @Test
    fun `Deepgram interim result emits interim segment`() = runTest {
        val manager = DeepgramRealtimeWebSocketManager(api, language = "en")
        manager.handleDeepgramMessage(
            """{"type":"Results","is_final":false,"speech_final":false,"start":0.25,"duration":0.5,"channel":{"alternatives":[{"transcript":"hello","confidence":0.82}]}}""",
        )

        val event = manager.events.replayCache.lastOrNull()
        assertTrue(event is WsEvent.Transcript)
        val segment = (event as WsEvent.Transcript).segment
        assertEquals("hello", segment.text)
        assertFalse(segment.isFinal)
        assertEquals(250, segment.startMs)
        assertEquals(750, segment.endMs)
        assertEquals(0.82, segment.confidence, 0.0001)
    }

    @Test
    fun `Deepgram final result emits final segment`() = runTest {
        val manager = DeepgramRealtimeWebSocketManager(api, language = "en")
        manager.handleDeepgramMessage(
            """{"type":"Results","is_final":true,"speech_final":true,"start":1.0,"duration":1.25,"channel":{"alternatives":[{"transcript":"hello world","confidence":0.97}]}}""",
        )

        val event = manager.events.replayCache.lastOrNull()
        assertTrue(event is WsEvent.Transcript)
        val segment = (event as WsEvent.Transcript).segment
        assertEquals("hello world", segment.text)
        assertTrue(segment.isFinal)
        assertEquals(1_000, segment.startMs)
        assertEquals(2_250, segment.endMs)
        assertEquals(1, manager.collectedSegments.size)
    }

    @Test
    fun `connect time Metadata does not mark provider finalization`() = runTest {
        val manager = DeepgramRealtimeWebSocketManager(api, language = "en")

        manager.handleDeepgramMessage("""{"type":"Metadata","request_id":"abc"}""")

        assertFalse(manager.testingProviderFinalizationReceived())
    }

    @Test
    fun `Metadata after Finalize marks provider finalization`() = runTest {
        val manager = DeepgramRealtimeWebSocketManager(api, language = "en")
        manager.testingSetEndOfStreamState(requested = true, sent = true)

        manager.handleDeepgramMessage("""{"type":"Metadata","request_id":"abc"}""")

        assertTrue(manager.testingProviderFinalizationReceived())
    }

    @Test
    fun `finishStreaming drains final result returned after CloseStream`() = runBlocking {
        val server = MockWebServer()
        val closeStreamReceived = CompletableDeferred<Unit>()
        val serverFinalSent = CompletableDeferred<Unit>()
        server.enqueue(
            MockResponse().withWebSocketUpgrade(
                object : WebSocketListener() {
                    override fun onMessage(webSocket: WebSocket, text: String) {
                        if (text.contains("CloseStream")) {
                            closeStreamReceived.complete(Unit)
                            Thread {
                                Thread.sleep(100)
                                webSocket.send(
                                    """{"type":"Results","is_final":true,"speech_final":true,"from_finalize":true,"start":0.0,"duration":1.1,"channel":{"alternatives":[{"transcript":"tail word retained","confidence":0.98}]}}""",
                                )
                                webSocket.send("""{"type":"Metadata","request_id":"abc","duration":1.1,"channels":1}""")
                                serverFinalSent.complete(Unit)
                                webSocket.close(1000, "done")
                            }.start()
                        }
                    }
                },
            ),
        )
        server.start()
        try {
            val websocketUrl = server.url("/api/transcription/stream")
                .toString()
                .replace("http://", "ws://")
            coEvery {
                api.createRealtimeTranscriptionSession(
                    language = "en",
                    channels = any(),
                    purpose = any(),
                )
            } returns deepgramConfig(language = "en", websocketUrl = websocketUrl)
            val manager = DeepgramRealtimeWebSocketManager(api, language = "en")

            manager.connect()
            manager.sendAudio(byteArrayOf(1, 2, 3, 4))
            val finalized = manager.finishStreaming(timeoutMillis = 800)

            closeStreamReceived.await()
            serverFinalSent.await()
            assertTrue(finalized)
            assertEquals("tail word retained", manager.collectedSegments.single().text)
        } finally {
            server.shutdown()
        }
    }

    private fun deepgramConfig(
        provider: String = "deepgram",
        language: String = "multi",
        model: String = "nova-3",
        websocketUrl: String = "wss://wai.computer/api/transcription/stream",
    ) = RealtimeTranscriptionSessionConfig(
        provider = provider,
        token = "deepgram-temporary-token",
        expiresInSeconds = 60,
        sampleRate = 16_000,
        audioFormat = "linear16",
        language = language,
        channels = 1,
        model = model,
        keepAliveIntervalSeconds = 4,
        websocketUrl = websocketUrl,
        authScheme = "bearer",
    )
}
