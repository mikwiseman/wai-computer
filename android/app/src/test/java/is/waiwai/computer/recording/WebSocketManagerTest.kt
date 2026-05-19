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
                model = "gpt-4o-mini-transcribe-2025-12-15",
                websocketUrl = "wss://api.openai.com/v1/realtime?model=gpt-4o-mini-transcribe-2025-12-15",
                authScheme = "bearer",
            ),
        )

        assertEquals("api.openai.com", request.url.host)
        assertEquals("/v1/realtime", request.url.encodedPath)
        assertEquals("gpt-4o-mini-transcribe-2025-12-15", request.url.queryParameter("model"))
        assertEquals("Bearer eph_secret", request.header("Authorization"))
    }

    @Test
    fun `build Inworld request uses bearer auth and configured websocket URL`() {
        val manager = ElevenLabsWebSocketManager(api, language = "multi")
        val request = manager.buildInworldRequest(
            RealtimeTranscriptionSessionConfig(
                provider = "inworld",
                token = "iw-jwt",
                expiresInSeconds = 60,
                sampleRate = 16_000,
                audioFormat = "linear16_16000",
                language = "multi",
                channels = 1,
                model = "inworld/inworld-stt-1",
                websocketUrl = "wss://api.inworld.ai/stt/v1/transcribe:streamBidirectional",
                authScheme = "bearer",
            ),
        )

        assertEquals("api.inworld.ai", request.url.host)
        assertEquals("/stt/v1/transcribe:streamBidirectional", request.url.encodedPath)
        assertEquals("Bearer iw-jwt", request.header("Authorization"))
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
    fun `Inworld audio chunk uses provider payload shape`() {
        val manager = ElevenLabsWebSocketManager(api, language = "multi")
        val message = manager.makeInworldAudioChunkMessage(byteArrayOf(1, 2, 3))
        val payload = Json.parseToJsonElement(message).jsonObject
        val audio = payload["audioChunk"]?.jsonObject?.get("content")?.jsonPrimitive?.contentOrNull.orEmpty()

        assertEquals("AQID", audio)
    }

    @Test
    fun `Inworld transcribe config uses current camelCase wire shape`() {
        val manager = ElevenLabsWebSocketManager(api, language = "multi")
        val message = manager.makeInworldTranscribeConfigMessage(
            RealtimeTranscriptionSessionConfig(
                provider = "inworld",
                token = "iw-jwt",
                expiresInSeconds = 60,
                sampleRate = 16_000,
                audioFormat = "linear16_16000",
                language = "multi",
                channels = 1,
                model = "inworld/inworld-stt-1",
                websocketUrl = "wss://api.inworld.ai/stt/v1/transcribe:streamBidirectional",
                authScheme = "bearer",
            ),
        )
        val payload = Json.parseToJsonElement(message).jsonObject
        val config = payload["transcribeConfig"]!!.jsonObject

        assertEquals("inworld/inworld-stt-1", config["modelId"]?.jsonPrimitive?.contentOrNull)
        assertEquals("LINEAR16", config["audioEncoding"]?.jsonPrimitive?.contentOrNull)
        assertEquals("", config["language"]?.jsonPrimitive?.contentOrNull)
        assertFalse(payload.containsKey("transcribe_config"))
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
    fun `Inworld final transcript emits final segment`() = runTest {
        val manager = ElevenLabsWebSocketManager(api, language = "en")
        manager.handleInworldMessage(
            """
            {
              "transcription":{
                "text":"hello world",
                "is_final":true,
                "confidence":0.92,
                "words":[
                  {"start_ms":100,"end_ms":400,"speaker":"Speaker 1"},
                  {"start_ms":450,"end_ms":900,"speaker":"Speaker 1"}
                ]
              }
            }
            """.trimIndent(),
        )

        val event = manager.events.replayCache.lastOrNull()
        assertTrue(event is WsEvent.Transcript)
        val segment = (event as WsEvent.Transcript).segment
        assertEquals("hello world", segment.text)
        assertEquals("Speaker 1", segment.speaker)
        assertTrue(segment.isFinal)
        assertEquals(100, segment.startMs)
        assertEquals(900, segment.endMs)
        assertEquals(1, manager.collectedSegments.size)
    }

    @Test
    fun `Inworld wrapped result transcript emits final segment`() = runTest {
        val manager = ElevenLabsWebSocketManager(api, language = "en")
        manager.handleInworldMessage(
            """
            {
              "result":{
                "transcription":{
                  "transcript":"This is an in-world real-time smoke test.",
                  "isFinal":true,
                  "wordTimestamps":[]
                }
              }
            }
            """.trimIndent(),
        )

        val event = manager.events.replayCache.lastOrNull()
        assertTrue(event is WsEvent.Transcript)
        val segment = (event as WsEvent.Transcript).segment
        assertEquals("This is an in-world real-time smoke test.", segment.text)
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
