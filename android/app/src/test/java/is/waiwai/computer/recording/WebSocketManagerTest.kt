package `is`.waiwai.computer.recording

import `is`.waiwai.computer.data.RealtimeTranscriptionSessionConfig
import `is`.waiwai.computer.data.WaiApi
import io.mockk.mockk
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class WebSocketManagerTest {
    private val api = mockk<WaiApi>(relaxed = true)

    @Test
    fun `close drain waits for provider finalization marker after client close`() {
        val startedAt = 1_000L
        assertTrue(
            ElevenLabsWebSocketManager.shouldKeepWaitingForCloseDrain(
                nowMs = startedAt + 2_499,
                deadlineMs = startedAt + 5_000,
                startedAtMs = startedAt,
                lastTranscriptEventAtMs = null,
                finalizationMarkerReceived = false,
            ),
        )
        assertFalse(
            ElevenLabsWebSocketManager.shouldKeepWaitingForCloseDrain(
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
            ElevenLabsWebSocketManager.shouldKeepWaitingForCloseDrain(
                nowMs = transcriptAt + 899,
                deadlineMs = startedAt + 5_000,
                startedAtMs = startedAt,
                lastTranscriptEventAtMs = transcriptAt,
                finalizationMarkerReceived = false,
            ),
        )
        assertFalse(
            ElevenLabsWebSocketManager.shouldKeepWaitingForCloseDrain(
                nowMs = transcriptAt + 900,
                deadlineMs = startedAt + 5_000,
                startedAtMs = startedAt,
                lastTranscriptEventAtMs = transcriptAt,
                finalizationMarkerReceived = false,
            ),
        )
    }

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
                noVerbatim = true,
            ),
        )

        assertTrue(url.contains("include_language_detection=true"))
        assertTrue(url.contains("commit_strategy=auto"))
        assertTrue(url.contains("no_verbatim=true"))
        assertFalse(url.contains("language_code="))
    }

    @Test
    fun `build OpenAI request uses bearer auth and configured websocket URL`() {
        val manager = ElevenLabsWebSocketManager(api, language = "multi")
        val request = manager.buildOpenAIRequest(
            RealtimeTranscriptionSessionConfig(
                provider = "openai",
                token = "eph_secret",
                expiresInSeconds = 60,
                sampleRate = 24_000,
                audioFormat = "pcm_24000",
                language = "multi",
                channels = 1,
                model = "gpt-realtime-whisper",
                websocketUrl = "wss://api.openai.com/v1/realtime?model=gpt-realtime-whisper",
                authScheme = "bearer",
            ),
        )

        assertEquals("api.openai.com", request.url.host)
        assertEquals("/v1/realtime", request.url.encodedPath)
        assertEquals("gpt-realtime-whisper", request.url.queryParameter("model"))
        assertEquals("Bearer eph_secret", request.header("Authorization"))
    }

    @Test
    fun `build Deepgram request uses bearer auth and configured websocket URL`() {
        val manager = ElevenLabsWebSocketManager(api, language = "multi")
        val request = manager.buildDeepgramRequest(
            RealtimeTranscriptionSessionConfig(
                provider = "deepgram",
                token = "dg-token",
                expiresInSeconds = 60,
                sampleRate = 16_000,
                audioFormat = "linear16_16000",
                language = "multi",
                channels = 1,
                model = "nova-3",
                keepAliveIntervalSeconds = 8,
                websocketUrl = "wss://api.deepgram.com/v1/listen?model=nova-3&encoding=linear16",
                authScheme = "bearer",
            ),
        )

        assertEquals("api.deepgram.com", request.url.host)
        assertEquals("/v1/listen", request.url.encodedPath)
        assertEquals("Bearer dg-token", request.header("Authorization"))
    }

    @Test
    fun `build Soniox request uses configured websocket URL without auth header`() {
        val manager = ElevenLabsWebSocketManager(api, language = "multi")
        val request = manager.buildSonioxRequest(
            RealtimeTranscriptionSessionConfig(
                provider = "soniox",
                token = "sx-temp",
                expiresInSeconds = 60,
                sampleRate = 16_000,
                audioFormat = "linear16_16000",
                language = "ru",
                channels = 1,
                model = "stt-rt-v4",
                websocketUrl = "wss://stt-rt.soniox.com/transcribe-websocket",
                authScheme = "message_api_key",
            ),
        )

        assertEquals("stt-rt.soniox.com", request.url.host)
        assertEquals(null, request.header("Authorization"))
    }

    @Test
    fun `OpenAI append message upsamples 16k PCM to 24k PCM`() {
        val manager = ElevenLabsWebSocketManager(api, language = "multi")
        val message = manager.makeOpenAIAudioAppendMessage(byteArrayOf(0, 0, 100, 0, -56, 0, 44, 1))
        val payload = Json.parseToJsonElement(message).jsonObject
        val audio = payload["audio"]?.jsonPrimitive?.contentOrNull.orEmpty()
        val decoded = java.util.Base64.getDecoder().decode(audio)

        assertEquals("input_audio_buffer.append", payload["type"]?.jsonPrimitive?.contentOrNull)
        assertEquals(12, decoded.size)
    }

    @Test
    fun `Soniox realtime config uses temporary key message shape`() {
        val manager = ElevenLabsWebSocketManager(api, language = "multi")
        val message = manager.makeSonioxRealtimeConfigMessage(
            RealtimeTranscriptionSessionConfig(
                provider = "soniox",
                token = "sx-temp",
                expiresInSeconds = 60,
                sampleRate = 16_000,
                audioFormat = "linear16_16000",
                language = "ru",
                channels = 2,
                model = "stt-rt-v4",
                websocketUrl = "wss://stt-rt.soniox.com/transcribe-websocket",
                authScheme = "message_api_key",
            ),
        )
        val payload = Json.parseToJsonElement(message).jsonObject

        assertEquals("sx-temp", payload["api_key"]?.jsonPrimitive?.contentOrNull)
        assertEquals("stt-rt-v4", payload["model"]?.jsonPrimitive?.contentOrNull)
        assertEquals("pcm_s16le", payload["audio_format"]?.jsonPrimitive?.contentOrNull)
        assertEquals(2, payload["num_channels"]?.jsonPrimitive?.intOrNull)
        assertEquals("ru", payload["language_hints"]?.jsonArray?.first()?.jsonPrimitive?.contentOrNull)
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
    fun `OpenAI completed transcript emits final segment`() = runTest {
        val manager = ElevenLabsWebSocketManager(api, language = "en")
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

    @Test
    fun `Deepgram final transcript emits final segment`() = runTest {
        val manager = ElevenLabsWebSocketManager(api, language = "en")
        manager.handleDeepgramMessage(
            """
            {
              "type":"Results",
              "is_final":true,
              "channel":{
                "alternatives":[{
                  "transcript":"hello world",
                  "confidence":0.91,
                  "words":[
                    {"word":"hello","start":0.1,"end":0.4,"confidence":0.9,"speaker":0},
                    {"punctuated_word":"world","start":0.5,"end":0.9,"confidence":0.92,"speaker":0}
                  ]
                }]
              }
            }
            """.trimIndent(),
        )

        val event = manager.events.replayCache.lastOrNull()
        assertTrue(event is WsEvent.Transcript)
        val segment = (event as WsEvent.Transcript).segment
        assertEquals("hello world", segment.text)
        assertEquals("Speaker 0", segment.speaker)
        assertTrue(segment.isFinal)
        assertEquals(100, segment.startMs)
        assertEquals(900, segment.endMs)
        assertEquals(1, manager.collectedSegments.size)
    }

    @Test
    fun `Deepgram final transcript splits mixed speaker words`() = runTest {
        val manager = ElevenLabsWebSocketManager(api, language = "en")
        manager.handleDeepgramMessage(
            """
            {
              "type":"Results",
              "is_final":true,
              "channel":{
                "alternatives":[{
                  "transcript":"Alice starts. Bob answers.",
                  "confidence":0.91,
                  "words":[
                    {"word":"Alice","start":0.0,"end":0.3,"confidence":0.9,"speaker":0},
                    {"punctuated_word":"starts.","start":0.3,"end":0.7,"confidence":0.92,"speaker":0},
                    {"word":"Bob","start":0.8,"end":1.0,"confidence":0.89,"speaker":1},
                    {"punctuated_word":"answers.","start":1.0,"end":1.4,"confidence":0.9,"speaker":1}
                  ]
                }]
              }
            }
            """.trimIndent(),
        )

        assertEquals(listOf("Alice starts.", "Bob answers."), manager.collectedSegments.map { it.text })
        assertEquals(listOf("Speaker 0", "Speaker 1"), manager.collectedSegments.map { it.speaker })
        assertEquals(listOf(0, 800), manager.collectedSegments.map { it.startMs })
        assertEquals(listOf(700, 1400), manager.collectedSegments.map { it.endMs })
    }

    @Test
    fun `Soniox final tokens emit final segment`() = runTest {
        val manager = ElevenLabsWebSocketManager(api, language = "ru")
        manager.handleSonioxMessage(
            """
            {
              "tokens":[
                {"text":"привет","is_final":true,"start_ms":0,"end_ms":400,"confidence":0.93,"speaker":1},
                {"text":" мир","is_final":true,"start_ms":400,"end_ms":800,"confidence":0.95,"speaker":1},
                {"text":"<fin>","is_final":true,"start_ms":800,"end_ms":800,"confidence":1.0,"speaker":1}
              ]
            }
            """.trimIndent(),
        )

        val event = manager.events.replayCache.lastOrNull()
        assertTrue(event is WsEvent.Transcript)
        val segment = (event as WsEvent.Transcript).segment
        assertEquals("привет мир", segment.text)
        assertEquals("Speaker 1", segment.speaker)
        assertTrue(segment.isFinal)
        assertEquals(800, segment.endMs)
        assertEquals(1, manager.collectedSegments.size)
    }

    @Test
    fun `Soniox final tokens split mixed speakers`() = runTest {
        val manager = ElevenLabsWebSocketManager(api, language = "ru")
        manager.handleSonioxMessage(
            """
            {
              "tokens":[
                {"text":"Алиса","is_final":true,"start_ms":0,"end_ms":300,"confidence":0.93,"speaker":1},
                {"text":" начала.","is_final":true,"start_ms":300,"end_ms":700,"confidence":0.95,"speaker":1},
                {"text":" Боб","is_final":true,"start_ms":800,"end_ms":1000,"confidence":0.91,"speaker":2},
                {"text":" ответил.","is_final":true,"start_ms":1000,"end_ms":1400,"confidence":0.9,"speaker":2},
                {"text":"<fin>","is_final":true,"start_ms":1400,"end_ms":1400,"confidence":1.0,"speaker":2}
              ]
            }
            """.trimIndent(),
        )

        assertEquals(listOf("Алиса начала.", "Боб ответил."), manager.collectedSegments.map { it.text })
        assertEquals(listOf("Speaker 1", "Speaker 2"), manager.collectedSegments.map { it.speaker })
        assertEquals(listOf(0, 800), manager.collectedSegments.map { it.startMs })
        assertEquals(listOf(700, 1400), manager.collectedSegments.map { it.endMs })
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
