package `is`.waiwai.computer.recording

import `is`.waiwai.computer.data.LiveTranscriptSegment
import `is`.waiwai.computer.data.RealtimeTranscriptionSessionConfig
import `is`.waiwai.computer.data.WaiApi
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
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
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

class DeepgramRealtimeWebSocketManager(
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
    private var keepAliveJob: Job? = null
    private var reconnectAttempt = 0
    private val audioBuffer = ArrayDeque<ByteArray>()
    private var endOfStreamRequested = false
    private var endOfStreamSent = false
    private var providerFinalizationReceived = false
    private var lastTranscriptReceivedAtMs: Long? = null
    private var connected = false
    private var currentConfig: RealtimeTranscriptionSessionConfig? = null
    private var hasSentAudioSinceLastFinalize = false

    override suspend fun connect() {
        collectedSegments.clear()
        reconnectAttempt = 0
        endOfStreamRequested = false
        endOfStreamSent = false
        providerFinalizationReceived = false
        lastTranscriptReceivedAtMs = null
        hasSentAudioSinceLastFinalize = false
        openSocket(freshSession())
    }

    override suspend fun sendAudio(data: ByteArray) {
        bufferAudioChunk(data)
        val socket = webSocket ?: return
        sendDeepgramAudio(socket, data)
    }

    override suspend fun finishStreaming(timeoutMillis: Long): Boolean {
        endOfStreamRequested = true
        sendFinalizeIfNeeded()
        val startedAt = System.currentTimeMillis()
        val deadline = startedAt + timeoutMillis
        while (System.currentTimeMillis() < deadline) {
            if (endOfStreamRequested && !endOfStreamSent && connected) {
                sendFinalizeIfNeeded()
            }
            if (!shouldKeepWaitingForCloseDrain(
                    nowMs = System.currentTimeMillis(),
                    deadlineMs = deadline,
                    startedAtMs = startedAt,
                    lastTranscriptEventAtMs = lastTranscriptReceivedAtMs,
                    finalizationMarkerReceived = providerFinalizationReceived,
                )
            ) {
                break
            }
            delay(100)
        }
        webSocket?.send("""{"type":"CloseStream"}""")
        disconnect()
        return endOfStreamSent && providerFinalizationReceived
    }

    override suspend fun disconnect() {
        reconnectJob?.cancel()
        reconnectJob = null
        keepAliveJob?.cancel()
        keepAliveJob = null
        webSocket?.close(1000, "done")
        webSocket = null
        connected = false
    }

    internal fun buildDeepgramRequest(config: RealtimeTranscriptionSessionConfig): Request {
        require(config.provider == "deepgram") {
            "Unsupported realtime transcription provider: ${config.provider}"
        }
        require(config.model == "nova-3") {
            "Unsupported realtime transcription model: ${config.model}"
        }
        require(config.authScheme == "bearer") {
            "Unsupported Deepgram auth scheme: ${config.authScheme}"
        }
        val url = requireNotNull(config.websocketUrl) { "Missing Deepgram realtime websocket URL" }
        require(config.token.isNotBlank()) { "Missing Deepgram realtime token" }
        return Request.Builder()
            .url(url)
            .header("Authorization", "Bearer ${config.token}")
            .build()
    }

    internal fun handleIncomingMessage(text: String) {
        handleDeepgramMessage(text)
    }

    internal fun handleDeepgramMessage(text: String) {
        val payload = runCatching { json.parseToJsonElement(text).jsonObject }.getOrNull() ?: return
        when (payload.string("type")) {
            "Results" -> handleDeepgramResults(payload)
            "UtteranceEnd" -> markTranscriptReceived()
            "Metadata" -> markTranscriptReceived(finalizationMarker = true)
            "Error",
            "error",
            -> {
                val message = payload.string("message")
                    ?: payload.string("description")
                    ?: payload.string("reason")
                    ?: "Deepgram realtime transcription error"
                scheduleReconnect(IllegalStateException(message))
            }
        }
    }

    private fun handleDeepgramResults(payload: JsonObject) {
        val alternative = payload["channel"]?.jsonObject
            ?.get("alternatives")?.jsonArray
            ?.firstOrNull()?.jsonObject
            ?: return
        val transcript = alternative.string("transcript").orEmpty().trim()
        if (transcript.isBlank()) return

        val isFinal = payload.boolean("is_final")
        val fromFinalize = payload.boolean("from_finalize")
        val startMs = payload.double("start").toMilliseconds()
        val durationMs = payload.double("duration").toMilliseconds()
        val confidence = alternative.double("confidence") ?: 0.0
        if (fromFinalize || (endOfStreamRequested && endOfStreamSent && isFinal)) {
            providerFinalizationReceived = true
        }
        markTranscriptReceived()

        val segment = LiveTranscriptSegment(
            text = transcript,
            speaker = DeepgramSpeakerLabel.dominant(alternative),
            isFinal = isFinal,
            startMs = startMs,
            endMs = startMs + durationMs,
            confidence = confidence,
        )
        if (isFinal) {
            val previous = collectedSegments.lastOrNull()?.text?.normalizedTranscript()
            if (previous == segment.text.normalizedTranscript()) return
            collectedSegments += segment
        }
        events.tryEmit(WsEvent.Transcript(segment))
    }

    private suspend fun freshSession(): RealtimeTranscriptionSessionConfig {
        return waiApi.createRealtimeTranscriptionSession(language = language)
    }

    private suspend fun openSocket(config: RealtimeTranscriptionSessionConfig) {
        currentConfig = config
        val request = buildDeepgramRequest(config)
        webSocket = okHttpClient.newWebSocket(
            request,
            object : WebSocketListener() {
                override fun onOpen(webSocket: WebSocket, response: Response) {
                    connected = true
                    startKeepAlive(config.keepAliveIntervalSeconds)
                    events.tryEmit(if (reconnectAttempt > 0) WsEvent.Reconnected else WsEvent.Connected)
                    scope.launch {
                        replayBufferedAudio()
                        sendFinalizeIfNeeded()
                    }
                }

                override fun onMessage(webSocket: WebSocket, text: String) {
                    handleIncomingMessage(text)
                }

                override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                    connected = false
                    keepAliveJob?.cancel()
                    events.tryEmit(WsEvent.Disconnected(t))
                    scheduleReconnect(t)
                }

                override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                    connected = false
                    keepAliveJob?.cancel()
                }
            },
        )
    }

    private fun startKeepAlive(intervalSeconds: Int?) {
        keepAliveJob?.cancel()
        val seconds = intervalSeconds ?: return
        if (seconds <= 0) return
        keepAliveJob = scope.launch {
            while (true) {
                delay(seconds * 1_000L)
                webSocket?.send("""{"type":"KeepAlive"}""")
            }
        }
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
            sendDeepgramAudio(socket, audioBuffer.removeFirst())
        }
    }

    private suspend fun sendFinalizeIfNeeded() {
        if (!endOfStreamRequested || endOfStreamSent || !connected) return
        if (hasSentAudioSinceLastFinalize) {
            webSocket?.send("""{"type":"Finalize"}""")
        } else {
            providerFinalizationReceived = true
        }
        endOfStreamSent = true
    }

    private fun sendDeepgramAudio(socket: WebSocket, data: ByteArray) {
        if (data.isEmpty()) return
        socket.send(data.toByteString())
        hasSentAudioSinceLastFinalize = true
    }

    private fun markTranscriptReceived(finalizationMarker: Boolean = false) {
        lastTranscriptReceivedAtMs = System.currentTimeMillis()
        if (finalizationMarker) {
            providerFinalizationReceived = true
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
    private fun JsonObject.boolean(key: String): Boolean = this[key]?.jsonPrimitive?.booleanOrNull == true
    private fun JsonObject.double(key: String): Double? = this[key]?.jsonPrimitive?.doubleOrNull
    private fun Double?.toMilliseconds(): Int = ((this ?: 0.0) * 1_000.0).toInt()
    private fun String.normalizedTranscript(): String = trim().split(Regex("\\s+")).joinToString(" ")

    companion object {
        private const val MAX_RECONNECT_ATTEMPTS = 10
        private const val MINIMUM_CLOSE_WAIT_MS = 650L
        private const val NO_TRANSCRIPT_CLOSE_WAIT_MS = 2_500L
        private const val TRANSCRIPT_QUIET_WINDOW_MS = 900L

        internal fun shouldKeepWaitingForCloseDrain(
            nowMs: Long,
            deadlineMs: Long,
            startedAtMs: Long,
            lastTranscriptEventAtMs: Long?,
            finalizationMarkerReceived: Boolean,
        ): Boolean {
            if (nowMs >= deadlineMs) return false
            val minimumWaitUntil = startedAtMs + MINIMUM_CLOSE_WAIT_MS
            if (finalizationMarkerReceived && nowMs >= minimumWaitUntil) return false
            if (lastTranscriptEventAtMs != null) {
                return !(nowMs >= minimumWaitUntil &&
                    nowMs - lastTranscriptEventAtMs >= TRANSCRIPT_QUIET_WINDOW_MS)
            }
            return nowMs < startedAtMs + NO_TRANSCRIPT_CLOSE_WAIT_MS
        }
    }
}
