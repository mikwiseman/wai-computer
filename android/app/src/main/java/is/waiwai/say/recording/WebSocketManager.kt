package `is`.waiwai.say.recording

import `is`.waiwai.say.data.LiveTranscriptSegment
import `is`.waiwai.say.data.RealtimeTranscriptionSessionConfig
import `is`.waiwai.say.data.WaiApi
import java.util.concurrent.TimeUnit
import kotlin.math.min
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.launch
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString.Companion.toByteString

sealed interface WsEvent {
    data object Connected : WsEvent
    data class Transcript(val segment: LiveTranscriptSegment) : WsEvent
    data class Disconnected(val cause: Throwable?) : WsEvent
    data class Reconnecting(val attempt: Int, val max: Int) : WsEvent
    data object Reconnected : WsEvent
    data class ReconnectionFailed(val cause: Throwable?) : WsEvent
}

interface RealtimeWebSocketManager {
    val events: SharedFlow<WsEvent>
    val collectedSegments: List<LiveTranscriptSegment>
    suspend fun connect()
    suspend fun sendAudio(data: ByteArray)
    suspend fun finishStreaming(timeoutMillis: Long = 5_000): Boolean
    suspend fun disconnect()
}

class ElevenLabsWebSocketManager(
    private val waiApi: WaiApi,
    private val language: String,
    private val okHttpClient: OkHttpClient = OkHttpClient.Builder()
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .build(),
) : RealtimeWebSocketManager {
    override val events: MutableSharedFlow<WsEvent> = MutableSharedFlow(replay = 1, extraBufferCapacity = 64)
    override val collectedSegments: MutableList<LiveTranscriptSegment> = mutableListOf()

    private val json = Json { ignoreUnknownKeys = true }
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var webSocket: WebSocket? = null
    private var reconnectJob: Job? = null
    private var reconnectAttempt = 0
    private val audioBuffer = ArrayDeque<ByteArray>()
    private var endOfStreamRequested = false
    private var endOfStreamSent = false
    private var connected = false
    private var currentConfig: RealtimeTranscriptionSessionConfig? = null
    private val openAIInterimByItem = mutableMapOf<String, String>()

    override suspend fun connect() {
        collectedSegments.clear()
        reconnectAttempt = 0
        openSocket(freshSession())
    }

    override suspend fun sendAudio(data: ByteArray) {
        bufferAudioChunk(data)
        val socket = webSocket ?: return
        socket.send(makeAudioMessage(data, commit = false))
    }

    override suspend fun finishStreaming(timeoutMillis: Long): Boolean {
        endOfStreamRequested = true
        sendCommitChunkIfNeeded()
        delay(min(timeoutMillis, 750))
        disconnect()
        return endOfStreamSent
    }

    override suspend fun disconnect() {
        reconnectJob?.cancel()
        reconnectJob = null
        webSocket?.close(1000, "done")
        webSocket = null
        connected = false
    }

    internal fun buildElevenLabsUrl(config: RealtimeTranscriptionSessionConfig): String {
        val base = StringBuilder(
            "wss://api.elevenlabs.io/v1/speech-to-text/realtime" +
                "?model_id=${config.model}" +
                "&token=${config.token}" +
                "&include_timestamps=true" +
                "&audio_format=pcm_16000",
        )
        if (language == "multi") {
            base.append("&include_language_detection=true")
        } else {
            base.append("&language_code=").append(language)
        }
        if (!config.commitStrategy.isNullOrBlank()) {
            base.append("&commit_strategy=").append(config.commitStrategy)
        }
        if (config.noVerbatim) {
            base.append("&no_verbatim=true")
        }
        return base.toString()
    }

    internal fun buildOpenAIRequest(config: RealtimeTranscriptionSessionConfig): Request {
        val url = requireNotNull(config.websocketUrl) { "Missing OpenAI realtime websocket URL" }
        return Request.Builder()
            .url(url)
            .header("Authorization", "Bearer ${config.token}")
            .build()
    }

    internal fun buildInworldRequest(config: RealtimeTranscriptionSessionConfig): Request {
        val url = requireNotNull(config.websocketUrl) { "Missing Inworld realtime websocket URL" }
        return Request.Builder()
            .url(url)
            .header("Authorization", config.token)
            .build()
    }

    internal fun handleIncomingMessage(text: String) {
        when (currentConfig?.provider) {
            "openai" -> {
                handleOpenAIMessage(text)
                return
            }
            "inworld" -> {
                handleInworldMessage(text)
                return
            }
        }
        handleElevenLabsMessage(text)
    }

    internal fun handleElevenLabsMessage(text: String) {
        val payload = runCatching { json.parseToJsonElement(text).jsonObject }.getOrNull() ?: return
        val type = payload.string("message_type") ?: payload.string("type") ?: return
        when (type) {
            "session_started" -> {
                reconnectAttempt = 0
            }
            "partial_transcript" -> {
                val transcript = payload.string("text").orEmpty().trim()
                if (transcript.isBlank()) return
                events.tryEmit(
                    WsEvent.Transcript(
                        LiveTranscriptSegment(
                            text = transcript,
                            isFinal = false,
                            startMs = collectedSegments.lastOrNull()?.endMs ?: 0,
                            endMs = collectedSegments.lastOrNull()?.endMs ?: 0,
                            confidence = 0.0,
                        ),
                    ),
                )
            }
            "committed_transcript_with_timestamps",
            "committed_transcript",
            -> {
                val segment = buildCommittedSegment(payload) ?: return
                collectedSegments += segment
                events.tryEmit(WsEvent.Transcript(segment))
            }
            else -> if (type in DOCUMENTED_ERRORS || type.endsWith("error") || type.contains("_error")) {
                scheduleReconnect(IllegalStateException(payload.string("message") ?: type))
            }
        }
    }

    internal fun handleOpenAIMessage(text: String) {
        val payload = runCatching { json.parseToJsonElement(text).jsonObject }.getOrNull() ?: return
        when (payload.string("type")) {
            "conversation.item.input_audio_transcription.delta" -> {
                val itemId = payload.string("item_id") ?: "unknown"
                val delta = payload.string("delta").orEmpty()
                if (delta.isBlank()) return
                val current = (openAIInterimByItem[itemId].orEmpty() + delta)
                openAIInterimByItem[itemId] = current
                events.tryEmit(
                    WsEvent.Transcript(
                        LiveTranscriptSegment(
                            text = current,
                            isFinal = false,
                            startMs = collectedSegments.lastOrNull()?.endMs ?: 0,
                            endMs = collectedSegments.lastOrNull()?.endMs ?: 0,
                            confidence = 0.0,
                        ),
                    ),
                )
            }
            "conversation.item.input_audio_transcription.completed" -> {
                val itemId = payload.string("item_id") ?: "unknown"
                val transcript = (payload.string("transcript") ?: openAIInterimByItem[itemId]).orEmpty().trim()
                openAIInterimByItem.remove(itemId)
                if (transcript.isBlank()) return
                val endMs = collectedSegments.lastOrNull()?.endMs ?: 0
                val segment = LiveTranscriptSegment(
                    text = transcript,
                    speaker = null,
                    isFinal = true,
                    startMs = endMs,
                    endMs = endMs,
                    confidence = 0.0,
                )
                collectedSegments += segment
                events.tryEmit(WsEvent.Transcript(segment))
            }
            "error" -> {
                val message = payload["error"]?.jsonObject?.string("message")
                    ?: "OpenAI realtime transcription error"
                scheduleReconnect(IllegalStateException(message))
            }
        }
    }

    internal fun handleInworldMessage(text: String) {
        val payload = runCatching { json.parseToJsonElement(text).jsonObject }.getOrNull() ?: return
        val transcription = payload["transcription"]?.jsonObject
            ?: payload["result"]?.jsonObject?.get("transcription")?.jsonObject
        if (transcription != null) {
            handleInworldTranscription(transcription)
            return
        }
        val error = payload["error"]?.jsonObject
        if (error != null) {
            scheduleReconnect(
                IllegalStateException(
                    error.string("message")
                        ?: error.string("error_message")
                        ?: "Inworld realtime transcription error",
                ),
            )
        }
    }

    private fun handleInworldTranscription(payload: JsonObject) {
        val transcript = (payload.string("text") ?: payload.string("transcript")).orEmpty().trim()
        if (transcript.isBlank()) return
        val isFinal = payload.boolean("is_final") ?: payload.boolean("isFinal") ?: false
        val confidence = payload.double("confidence") ?: 0.0
        if (isFinal) {
            val words = payload["words"]?.jsonArray?.mapNotNull { it as? JsonObject }
                ?: payload["word_timestamps"]?.jsonArray?.mapNotNull { it as? JsonObject }
                ?: payload["wordTimestamps"]?.jsonArray?.mapNotNull { it as? JsonObject }
                ?: emptyList()
            val startMs = inworldTimestampMs(
                words.firstOrNull()?.get("start_ms")
                    ?: words.firstOrNull()?.get("startMs")
                    ?: words.firstOrNull()?.get("start_time_ms")
                    ?: words.firstOrNull()?.get("start"),
            ) ?: (collectedSegments.lastOrNull()?.endMs ?: 0)
            val endMs = inworldTimestampMs(
                words.lastOrNull()?.get("end_ms")
                    ?: words.lastOrNull()?.get("endMs")
                    ?: words.lastOrNull()?.get("end_time_ms")
                    ?: words.lastOrNull()?.get("end"),
            ) ?: startMs
            val segment = LiveTranscriptSegment(
                text = transcript,
                speaker = words.firstOrNull()?.string("speaker") ?: words.firstOrNull()?.string("speaker_id"),
                isFinal = true,
                startMs = startMs,
                endMs = endMs,
                confidence = confidence,
            )
            collectedSegments += segment
            events.tryEmit(WsEvent.Transcript(segment))
        } else {
            events.tryEmit(
                WsEvent.Transcript(
                    LiveTranscriptSegment(
                        text = transcript,
                        speaker = null,
                        isFinal = false,
                        startMs = collectedSegments.lastOrNull()?.endMs ?: 0,
                        endMs = collectedSegments.lastOrNull()?.endMs ?: 0,
                        confidence = confidence,
                    ),
                ),
            )
        }
    }

    internal fun buildCommittedSegment(payload: JsonObject): LiveTranscriptSegment? {
        val transcript = payload.string("text").orEmpty().trim()
        if (transcript.isBlank()) return null
        val words = payload["words"]?.jsonArray?.mapNotNull { it as? JsonObject }.orEmpty()
        val startMs = ((words.firstOrNull()?.double("start") ?: 0.0) * 1000).toInt()
        val endMs = ((words.lastOrNull()?.double("end") ?: startMs.toDouble()) * 1000).toInt()
        val logProbs = words.mapNotNull { it.double("logprob") }
        val confidence = if (logProbs.isEmpty()) 0.0 else (1.0 + logProbs.average() / 10.0).coerceIn(0.0, 1.0)
        return LiveTranscriptSegment(
            text = transcript,
            speaker = null,
            isFinal = true,
            startMs = startMs,
            endMs = endMs,
            confidence = confidence,
        )
    }

    private suspend fun freshSession(): RealtimeTranscriptionSessionConfig {
        return waiApi.createRealtimeTranscriptionSession(language = language)
    }

    private suspend fun openSocket(config: RealtimeTranscriptionSessionConfig) {
        currentConfig = config
        val request = when (config.provider) {
            "openai" -> buildOpenAIRequest(config)
            "inworld" -> buildInworldRequest(config)
            else -> Request.Builder().url(buildElevenLabsUrl(config)).build()
        }
        webSocket = okHttpClient.newWebSocket(
            request,
            object : WebSocketListener() {
                override fun onOpen(webSocket: WebSocket, response: Response) {
                    connected = true
                    if (config.provider == "openai") {
                        webSocket.send(makeOpenAISessionUpdateMessage(config))
                    }
                    if (config.provider == "inworld") {
                        webSocket.send(makeInworldTranscribeConfigMessage(config))
                    }
                    events.tryEmit(if (reconnectAttempt > 0) WsEvent.Reconnected else WsEvent.Connected)
                    scope.launch {
                        replayBufferedAudio()
                        sendCommitChunkIfNeeded()
                    }
                }

                override fun onMessage(webSocket: WebSocket, text: String) {
                    handleIncomingMessage(text)
                }

                override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                    connected = false
                    events.tryEmit(WsEvent.Disconnected(t))
                    scheduleReconnect(t)
                }

                override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                    connected = false
                }
            },
        )
    }

    private fun scheduleReconnect(cause: Throwable) {
        if (reconnectJob?.isActive == true || endOfStreamSent) return
        reconnectJob = scope.launch {
            while (reconnectAttempt < MAX_RECONNECT_ATTEMPTS) {
                reconnectAttempt += 1
                events.emit(WsEvent.Reconnecting(reconnectAttempt, MAX_RECONNECT_ATTEMPTS))
                delay(reconnectDelay(reconnectAttempt))
                runCatching { openSocket(freshSession()) }
                    .onSuccess { return@launch }
            }
            events.emit(WsEvent.ReconnectionFailed(cause))
        }
    }

    private suspend fun replayBufferedAudio() {
        if (!connected) return
        val socket = webSocket ?: return
        while (audioBuffer.isNotEmpty()) {
            socket.send(makeAudioMessage(audioBuffer.removeFirst(), commit = false))
        }
    }

    private suspend fun sendCommitChunkIfNeeded() {
        if (!endOfStreamRequested || endOfStreamSent || !connected) return
        if (currentConfig?.provider == "inworld") {
            webSocket?.send("""{"end_turn":{}}""")
            webSocket?.send("""{"close_stream":{}}""")
        } else {
            webSocket?.send(makeAudioMessage(ByteArray(640), commit = true))
        }
        endOfStreamSent = true
    }

    private fun makeAudioMessage(data: ByteArray, commit: Boolean): String {
        return if (currentConfig?.provider == "openai") {
            if (commit) {
                """{"type":"input_audio_buffer.commit"}"""
            } else {
                makeOpenAIAudioAppendMessage(data)
            }
        } else if (currentConfig?.provider == "inworld") {
            makeInworldAudioChunkMessage(data)
        } else {
            makeAudioChunkMessage(data, commit)
        }
    }

    internal fun makeOpenAIAudioAppendMessage(data: ByteArray): String {
        val audioBase64 = java.util.Base64.getEncoder().encodeToString(openAI24kMonoPCM(data))
        return """{"type":"input_audio_buffer.append","audio":"$audioBase64"}"""
    }

    private fun makeOpenAISessionUpdateMessage(config: RealtimeTranscriptionSessionConfig): String {
        val transcription = if (config.language.isNotBlank() && config.language != "multi") {
            """"model":"${config.model}","language":"${config.language}""""
        } else {
            """"model":"${config.model}""""
        }
        return """{"type":"session.update","session":{"type":"transcription","audio":{"input":{"format":{"type":"audio/pcm","rate":${config.sampleRate}},"transcription":{$transcription},"turn_detection":null}}}}"""
    }

    private fun makeInworldTranscribeConfigMessage(config: RealtimeTranscriptionSessionConfig): String {
        val languageValue = when {
            config.language == "multi" || config.language == "und" -> ""
            "-" in config.language -> config.language.substringBefore("-")
            else -> config.language
        }
        return buildString {
            append("{\"transcribe_config\":{")
            append("\"model_id\":\"").append(config.model).append("\",")
            append("\"language\":\"").append(languageValue).append("\",")
            append("\"audio_encoding\":\"LINEAR16\",")
            append("\"sample_rate_hertz\":").append(config.sampleRate).append(",")
            append("\"number_of_channels\":").append(config.channels).append(",")
            append("\"inactivity_timeout_seconds\":60")
            append("}}")
        }
    }

    internal fun makeInworldAudioChunkMessage(data: ByteArray): String {
        val audioBase64 = java.util.Base64.getEncoder().encodeToString(data)
        return """{"audio_chunk":{"content":"$audioBase64"}}"""
    }

    private fun makeAudioChunkMessage(data: ByteArray, commit: Boolean): String {
        val audioBase64 = java.util.Base64.getEncoder().encodeToString(data)
        return buildString {
            append("{")
            append("\"message_type\":\"input_audio_chunk\",")
            append("\"audio_base_64\":\"").append(audioBase64).append("\",")
            append("\"sample_rate\":16000,")
            append("\"commit\":").append(commit)
            append("}")
        }
    }

    internal fun openAI24kMonoPCM(data: ByteArray): ByteArray {
        if (data.size < 4) return data
        val sourceSamples = ShortArray(data.size / 2)
        for (index in sourceSamples.indices) {
            val low = data[index * 2].toInt() and 0xff
            val high = data[index * 2 + 1].toInt()
            sourceSamples[index] = ((high shl 8) or low).toShort()
        }
        val outputCount = (sourceSamples.size * 24_000 / 16_000)
        val output = ByteArray(outputCount * 2)
        for (index in 0 until outputCount) {
            val sourcePosition = index * 16_000.0 / 24_000.0
            val lower = sourcePosition.toInt().coerceAtMost(sourceSamples.lastIndex)
            val upper = (lower + 1).coerceAtMost(sourceSamples.lastIndex)
            val fraction = sourcePosition - lower
            val interpolated = sourceSamples[lower] + (sourceSamples[upper] - sourceSamples[lower]) * fraction
            val sample = interpolated.toInt().coerceIn(Short.MIN_VALUE.toInt(), Short.MAX_VALUE.toInt()).toShort()
            output[index * 2] = (sample.toInt() and 0xff).toByte()
            output[index * 2 + 1] = ((sample.toInt() shr 8) and 0xff).toByte()
        }
        return output
    }

    private fun bufferAudioChunk(data: ByteArray) {
        audioBuffer.addLast(data)
        while (audioBuffer.size > 300) {
            audioBuffer.removeFirst()
        }
    }

    private fun reconnectDelay(attempt: Int): Long {
        val base = min(500L * (1 shl (attempt - 1)), 30_000L)
        val jitter = (base * 0.5 * Math.random()).toLong()
        return base + jitter
    }

    private fun JsonObject.string(key: String): String? = (this[key] as? JsonPrimitive)?.contentOrNull

    private fun JsonObject.double(key: String): Double? = (this[key] as? JsonPrimitive)?.doubleOrNull

    private fun JsonObject.boolean(key: String): Boolean? = (this[key] as? JsonPrimitive)?.booleanOrNull

    private fun inworldTimestampMs(value: JsonElement?): Int? {
        val primitive = value as? JsonPrimitive ?: return null
        var numeric = primitive.doubleOrNull ?: primitive.contentOrNull?.toDoubleOrNull() ?: return null
        if (numeric >= 0 && numeric < 10_000 && numeric % 1.0 != 0.0) {
            numeric *= 1_000
        }
        return numeric.toInt()
    }

    companion object {
        private const val MAX_RECONNECT_ATTEMPTS = 10
        private val DOCUMENTED_ERRORS = setOf(
            "error",
            "auth_error",
            "quota_exceeded",
            "commit_throttled",
            "unaccepted_terms",
            "rate_limited",
            "queue_overflow",
            "resource_exhausted",
            "session_time_limit_exceeded",
            "input_error",
            "chunk_size_exceeded",
            "insufficient_audio_activity",
            "transcriber_error",
        )
    }
}
