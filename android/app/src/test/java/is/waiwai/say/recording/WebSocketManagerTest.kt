package `is`.waiwai.say.recording

import `is`.waiwai.say.data.RealtimeTranscriptionSessionConfig
import `is`.waiwai.say.data.WaiApi
import io.mockk.mockk
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.jsonObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class WebSocketManagerTest {
    private val api = mockk<WaiApi>(relaxed = true)

    @Test
    fun `build url uses language detection for multi mode`() {
        val manager = ElevenLabsWebSocketManager(api, language = "multi")
        val url = manager.buildElevenLabsUrl(
            RealtimeTranscriptionSessionConfig(
                provider = "elevenlabs",
                token = "abc",
                expiresInSeconds = 60,
                sampleRate = 16_000,
                audioFormat = "pcm_16000",
                language = "multi",
                channels = 1,
                model = "scribe_v1",
                commitStrategy = "auto",
            ),
        )

        assertTrue(url.contains("include_language_detection=true"))
        assertTrue(url.contains("commit_strategy=auto"))
        assertFalse(url.contains("language_code="))
    }

    @Test
    fun `partial transcript emits non-final segment`() = runTest {
        val manager = ElevenLabsWebSocketManager(api, language = "en")
        manager.handleIncomingMessage("""{"message_type":"partial_transcript","text":"hello world"}""")

        val event = manager.events.replayCache.lastOrNull()
        assertTrue(event is WsEvent.Transcript)
        val segment = (event as WsEvent.Transcript).segment
        assertEquals("hello world", segment.text)
        assertFalse(segment.isFinal)
    }

    @Test
    fun `committed transcript parses timestamps and confidence`() {
        val manager = ElevenLabsWebSocketManager(api, language = "en")
        val segment = manager.buildCommittedSegment(
            kotlinx.serialization.json.Json.parseToJsonElement(
                """
                {
                  "message_type":"committed_transcript_with_timestamps",
                  "text":"hello world",
                  "words":[
                    {"start":0.1,"end":0.4,"logprob":-0.2,"type":"word"},
                    {"start":0.5,"end":0.9,"logprob":-0.3,"type":"word"}
                  ]
                }
                """.trimIndent(),
            ).jsonObject,
        )

        requireNotNull(segment)
        assertEquals("hello world", segment.text)
        assertTrue(segment.isFinal)
        assertEquals(100, segment.startMs)
        assertEquals(900, segment.endMs)
        assertTrue(segment.confidence > 0.9)
    }
}
