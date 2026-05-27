package `is`.waiwai.computer.recording

import `is`.waiwai.computer.data.RealtimeTranscriptionSessionConfig
import `is`.waiwai.computer.data.WaiApi
import io.mockk.mockk
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
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
            OpenAIRealtimeWebSocketManager.shouldKeepWaitingForCloseDrain(
                nowMs = startedAt + 2_499,
                deadlineMs = startedAt + 5_000,
                startedAtMs = startedAt,
                lastTranscriptEventAtMs = null,
                finalizationMarkerReceived = false,
            ),
        )
        assertFalse(
            OpenAIRealtimeWebSocketManager.shouldKeepWaitingForCloseDrain(
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
            OpenAIRealtimeWebSocketManager.shouldKeepWaitingForCloseDrain(
                nowMs = transcriptAt + 899,
                deadlineMs = startedAt + 5_000,
                startedAtMs = startedAt,
                lastTranscriptEventAtMs = transcriptAt,
                finalizationMarkerReceived = false,
            ),
        )
        assertFalse(
            OpenAIRealtimeWebSocketManager.shouldKeepWaitingForCloseDrain(
                nowMs = transcriptAt + 900,
                deadlineMs = startedAt + 5_000,
                startedAtMs = startedAt,
                lastTranscriptEventAtMs = transcriptAt,
                finalizationMarkerReceived = false,
            ),
        )
    }

    @Test
    fun `build OpenAI request uses bearer auth and configured websocket URL`() {
        val manager = OpenAIRealtimeWebSocketManager(api, language = "multi")
        val request = manager.buildOpenAIRequest(openAIConfig())

        assertEquals("api.openai.com", request.url.host)
        assertEquals("/v1/realtime", request.url.encodedPath)
        assertEquals("transcription", request.url.queryParameter("intent"))
        assertEquals("Bearer eph_secret", request.header("Authorization"))
    }

    @Test
    fun `build OpenAI request rejects removed live providers`() {
        val manager = OpenAIRealtimeWebSocketManager(api, language = "multi")

        assertThrows(IllegalArgumentException::class.java) {
            manager.buildOpenAIRequest(openAIConfig(provider = "removed-provider"))
        }
    }

    @Test
    fun `OpenAI session update uses realtime transcription shape and language hint`() {
        val manager = OpenAIRealtimeWebSocketManager(api, language = "en")
        val payload = Json.parseToJsonElement(
            manager.makeOpenAISessionUpdateMessage(openAIConfig(language = "ru-RU")),
        ).jsonObject

        val input = payload["session"]?.jsonObject
            ?.get("audio")?.jsonObject
            ?.get("input")?.jsonObject
        val transcription = input
            ?.get("transcription")?.jsonObject

        assertEquals("session.update", payload["type"]?.jsonPrimitive?.contentOrNull)
        assertEquals("audio/pcm", input?.get("format")?.jsonObject?.get("type")?.jsonPrimitive?.contentOrNull)
        assertEquals("gpt-realtime-whisper", transcription?.get("model")?.jsonPrimitive?.contentOrNull)
        assertEquals("ru", transcription?.get("language")?.jsonPrimitive?.contentOrNull)
    }

    @Test
    fun `OpenAI session update omits language hint in auto mode`() {
        val manager = OpenAIRealtimeWebSocketManager(api, language = "multi")
        val payload = Json.parseToJsonElement(
            manager.makeOpenAISessionUpdateMessage(openAIConfig(language = "multi")),
        ).jsonObject
        val transcription = payload["session"]?.jsonObject
            ?.get("audio")?.jsonObject
            ?.get("input")?.jsonObject
            ?.get("transcription")?.jsonObject

        assertFalse(transcription?.containsKey("language") == true)
    }

    @Test
    fun `OpenAI append message upsamples 16k PCM to 24k PCM`() {
        val manager = OpenAIRealtimeWebSocketManager(api, language = "multi")
        val message = manager.makeOpenAIAudioAppendMessage(byteArrayOf(0, 0, 100, 0, -56, 0, 44, 1))
        val payload = Json.parseToJsonElement(message).jsonObject
        val audio = payload["audio"]?.jsonPrimitive?.contentOrNull.orEmpty()
        val decoded = java.util.Base64.getDecoder().decode(audio)

        assertEquals("input_audio_buffer.append", payload["type"]?.jsonPrimitive?.contentOrNull)
        assertEquals(12, decoded.size)
    }

    @Test
    fun `OpenAI delta emits interim segment`() = runTest {
        val manager = OpenAIRealtimeWebSocketManager(api, language = "en")
        manager.handleOpenAIMessage(
            """{"type":"conversation.item.input_audio_transcription.delta","item_id":"item_1","delta":"hello"}""",
        )

        val event = manager.events.replayCache.lastOrNull()
        assertTrue(event is WsEvent.Transcript)
        val segment = (event as WsEvent.Transcript).segment
        assertEquals("hello", segment.text)
        assertFalse(segment.isFinal)
    }

    @Test
    fun `OpenAI completed transcript emits final segment`() = runTest {
        val manager = OpenAIRealtimeWebSocketManager(api, language = "en")
        manager.handleOpenAIMessage(
            """{"type":"conversation.item.input_audio_transcription.completed","item_id":"item_1","transcript":"hello world"}""",
        )

        val event = manager.events.replayCache.lastOrNull()
        assertTrue(event is WsEvent.Transcript)
        val segment = (event as WsEvent.Transcript).segment
        assertEquals("hello world", segment.text)
        assertTrue(segment.isFinal)
        assertEquals(1, manager.collectedSegments.size)
    }

    private fun openAIConfig(
        provider: String = "openai",
        language: String = "multi",
        model: String = "gpt-realtime-whisper",
    ) = RealtimeTranscriptionSessionConfig(
        provider = provider,
        token = "eph_secret",
        expiresInSeconds = 60,
        sampleRate = 24_000,
        audioFormat = "pcm_24000",
        language = language,
        channels = 1,
        model = model,
        websocketUrl = "wss://api.openai.com/v1/realtime?intent=transcription",
        authScheme = "bearer",
    )
}
