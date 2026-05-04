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
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
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

    override suspend fun connect() {
        collectedSegments.clear()
        reconnectAttempt = 0
        openSocket(freshSession())
    }

    override suspend fun sendAudio(data: ByteArray) {
        bufferAudioChunk(data)
        val socket = webSocket ?: return
        socket.send(makeAudioChunkMessage(data, commit = false))
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

    internal fun handleIncomingMessage(text: String) {
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
        val request = Request.Builder().url(buildElevenLabsUrl(config)).build()
        webSocket = okHttpClient.newWebSocket(
            request,
            object : WebSocketListener() {
                override fun onOpen(webSocket: WebSocket, response: Response) {
                    connected = true
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
            socket.send(makeAudioChunkMessage(audioBuffer.removeFirst(), commit = false))
        }
    }

    private suspend fun sendCommitChunkIfNeeded() {
        if (!endOfStreamRequested || endOfStreamSent || !connected) return
        webSocket?.send(makeAudioChunkMessage(ByteArray(640), commit = true))
        endOfStreamSent = true
    }

    private fun makeAudioChunkMessage(data: ByteArray, commit: Boolean): String {
        val audioBase64 = android.util.Base64.encodeToString(data, android.util.Base64.NO_WRAP)
        return buildString {
            append("{")
            append("\"message_type\":\"input_audio_chunk\",")
            append("\"audio_base_64\":\"").append(audioBase64).append("\",")
            append("\"sample_rate\":16000,")
            append("\"commit\":").append(commit)
            append("}")
        }
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
