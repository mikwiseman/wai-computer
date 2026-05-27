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
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener

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

class OpenAIRealtimeWebSocketManager(
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
    private var providerFinalizationReceived = false
    private var lastTranscriptReceivedAtMs: Long? = null
    private var connected = false
    private var currentConfig: RealtimeTranscriptionSessionConfig? = null
    private val openAIInterimByItem = mutableMapOf<String, String>()
    private var openAIUncommittedAudioBytes = 0
    private var openAIPendingCommitCount = 0

    override suspend fun connect() {
        collectedSegments.clear()
        reconnectAttempt = 0
        endOfStreamRequested = false
        endOfStreamSent = false
        providerFinalizationReceived = false
        lastTranscriptReceivedAtMs = null
        openAIInterimByItem.clear()
        openAIUncommittedAudioBytes = 0
        openAIPendingCommitCount = 0
        openSocket(freshSession())
    }

    override suspend fun sendAudio(data: ByteArray) {
        bufferAudioChunk(data)
        val socket = webSocket ?: return
        sendOpenAIAudio(socket, data)
    }

    override suspend fun finishStreaming(timeoutMillis: Long): Boolean {
        endOfStreamRequested = true
        sendCommitChunkIfNeeded()
        val startedAt = System.currentTimeMillis()
        val deadline = startedAt + timeoutMillis
        while (System.currentTimeMillis() < deadline) {
            if (endOfStreamRequested && !endOfStreamSent && connected) {
                sendCommitChunkIfNeeded()
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
        disconnect()
        return endOfStreamSent && providerFinalizationReceived
    }

    override suspend fun disconnect() {
        reconnectJob?.cancel()
        reconnectJob = null
        webSocket?.close(1000, "done")
        webSocket = null
        connected = false
    }

    internal fun buildOpenAIRequest(config: RealtimeTranscriptionSessionConfig): Request {
        require(config.provider == "openai") {
            "Unsupported realtime transcription provider: ${config.provider}"
        }
        require(config.model == "gpt-realtime-whisper") {
            "Unsupported realtime transcription model: ${config.model}"
        }
        require(config.authScheme == "bearer") {
            "Unsupported OpenAI auth scheme: ${config.authScheme}"
        }
        val url = requireNotNull(config.websocketUrl) { "Missing OpenAI realtime websocket URL" }
        require(config.token.isNotBlank()) { "Missing OpenAI realtime token" }
        return Request.Builder()
            .url(url)
            .header("Authorization", "Bearer ${config.token}")
            .build()
    }

    internal fun handleIncomingMessage(text: String) {
        handleOpenAIMessage(text)
    }

    internal fun handleOpenAIMessage(text: String) {
        val payload = runCatching { json.parseToJsonElement(text).jsonObject }.getOrNull() ?: return
        when (payload.string("type")) {
            "conversation.item.input_audio_transcription.delta" -> {
                val itemId = payload.string("item_id") ?: "unknown"
                val delta = payload.string("delta").orEmpty()
                if (delta.isBlank()) return
                val current = openAIInterimByItem[itemId].orEmpty() + delta
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
                if (openAIPendingCommitCount > 0) {
                    openAIPendingCommitCount -= 1
                }
                if (endOfStreamRequested && endOfStreamSent && openAIPendingCommitCount == 0) {
                    providerFinalizationReceived = true
                }
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
                markTranscriptReceived(finalizationMarker = endOfStreamRequested)
                events.tryEmit(WsEvent.Transcript(segment))
            }
            "error" -> {
                val message = payload["error"]?.jsonObject?.string("message")
                    ?: "OpenAI realtime transcription error"
                scheduleReconnect(IllegalStateException(message))
            }
        }
    }

    private suspend fun freshSession(): RealtimeTranscriptionSessionConfig {
        return waiApi.createRealtimeTranscriptionSession(language = language)
    }

    private suspend fun openSocket(config: RealtimeTranscriptionSessionConfig) {
        currentConfig = config
        val request = buildOpenAIRequest(config)
        webSocket = okHttpClient.newWebSocket(
            request,
            object : WebSocketListener() {
                override fun onOpen(webSocket: WebSocket, response: Response) {
                    connected = true
                    webSocket.send(makeOpenAISessionUpdateMessage(config))
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
            sendOpenAIAudio(socket, audioBuffer.removeFirst())
        }
    }

    private suspend fun sendCommitChunkIfNeeded() {
        if (!endOfStreamRequested || endOfStreamSent || !connected) return
        if (openAIUncommittedAudioBytes > 0) {
            commitOpenAIAudioBuffer()
        } else if (openAIPendingCommitCount == 0) {
            providerFinalizationReceived = true
        }
        endOfStreamSent = true
    }

    private fun sendOpenAIAudio(socket: WebSocket, data: ByteArray) {
        val pcm24k = openAI24kMonoPCM(data)
        socket.send(makeOpenAIAudioAppendMessage(pcm24k, already24k = true))
        openAIUncommittedAudioBytes += pcm24k.size
        if (openAIUncommittedAudioBytes >= openAIAutoCommitBytes()) {
            commitOpenAIAudioBuffer(socket)
        }
    }

    private fun openAIAutoCommitBytes(): Int {
        val config = currentConfig
        return (config?.sampleRate ?: 24_000).coerceAtLeast(1) *
            (config?.channels ?: 1).coerceAtLeast(1) *
            2
    }

    private fun commitOpenAIAudioBuffer(socket: WebSocket? = webSocket) {
        if (openAIUncommittedAudioBytes <= 0) return
        socket?.send("""{"type":"input_audio_buffer.commit"}""")
        openAIUncommittedAudioBytes = 0
        openAIPendingCommitCount += 1
    }

    private fun markTranscriptReceived(finalizationMarker: Boolean = false) {
        lastTranscriptReceivedAtMs = System.currentTimeMillis()
        if (finalizationMarker) {
            providerFinalizationReceived = true
        }
    }

    internal fun makeOpenAIAudioAppendMessage(data: ByteArray): String {
        return makeOpenAIAudioAppendMessage(data, already24k = false)
    }

    private fun makeOpenAIAudioAppendMessage(data: ByteArray, already24k: Boolean): String {
        val pcm = if (already24k) data else openAI24kMonoPCM(data)
        val audioBase64 = java.util.Base64.getEncoder().encodeToString(pcm)
        return """{"type":"input_audio_buffer.append","audio":"$audioBase64"}"""
    }

    internal fun makeOpenAISessionUpdateMessage(config: RealtimeTranscriptionSessionConfig): String {
        val language = normalizedProviderLanguage(config.language)
        val transcription = if (language != null) {
            """"model":"${config.model}","delay":"$OPENAI_TRANSCRIPTION_DELAY","language":"$language""""
        } else {
            """"model":"${config.model}","delay":"$OPENAI_TRANSCRIPTION_DELAY""""
        }
        return """{"type":"session.update","session":{"type":"transcription","audio":{"input":{"format":{"type":"audio/pcm","rate":${config.sampleRate}},"transcription":{$transcription},"turn_detection":null}}}}"""
    }

    private fun normalizedProviderLanguage(raw: String): String? {
        val normalized = raw.trim().lowercase().replace("_", "-")
        if (normalized.isBlank() || normalized == "multi" || normalized == "auto" || normalized == "und") {
            return null
        }
        return normalized.substringBefore("-")
    }

    internal fun openAI24kMonoPCM(data: ByteArray): ByteArray {
        if (data.size < 4) return data
        val sourceSamples = ShortArray(data.size / 2)
        for (index in sourceSamples.indices) {
            val low = data[index * 2].toInt() and 0xff
            val high = data[index * 2 + 1].toInt()
            sourceSamples[index] = ((high shl 8) or low).toShort()
        }
        val outputCount = sourceSamples.size * 24_000 / 16_000
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

    companion object {
        private const val MAX_RECONNECT_ATTEMPTS = 10
        private const val MINIMUM_CLOSE_WAIT_MS = 650L
        private const val NO_TRANSCRIPT_CLOSE_WAIT_MS = 2_500L
        private const val TRANSCRIPT_QUIET_WINDOW_MS = 900L
        private const val OPENAI_TRANSCRIPTION_DELAY = "low"

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
