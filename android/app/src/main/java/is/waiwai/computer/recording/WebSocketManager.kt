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
        openAIUncommittedAudioBytes = 0
        openAIPendingCommitCount = 0
        openSocket(freshSession())
    }

    override suspend fun sendAudio(data: ByteArray) {
        bufferAudioChunk(data)
        val socket = webSocket ?: return
        if (currentConfig?.provider == "openai") {
            sendOpenAIAudio(socket, data)
        } else if (currentConfig?.provider == "deepgram" || currentConfig?.provider == "soniox") {
            socket.send(data.toByteString())
        } else {
            socket.send(makeAudioMessage(data, commit = false))
        }
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

    internal fun buildDeepgramRequest(config: RealtimeTranscriptionSessionConfig): Request {
        val url = requireNotNull(config.websocketUrl) { "Missing Deepgram realtime websocket URL" }
        return Request.Builder()
            .url(url)
            .header("Authorization", "Bearer ${config.token}")
            .build()
    }

    internal fun buildSonioxRequest(config: RealtimeTranscriptionSessionConfig): Request {
        val url = requireNotNull(config.websocketUrl) { "Missing Soniox realtime websocket URL" }
        return Request.Builder()
            .url(url)
            .build()
    }

    internal fun handleIncomingMessage(text: String) {
        when (currentConfig?.provider) {
            "openai" -> {
                handleOpenAIMessage(text)
                return
            }
            "deepgram" -> {
                handleDeepgramMessage(text)
                return
            }
            "soniox" -> {
                handleSonioxMessage(text)
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
                markTranscriptReceived(finalizationMarker = endOfStreamRequested)
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

    internal fun handleDeepgramMessage(text: String) {
        val payload = runCatching { json.parseToJsonElement(text).jsonObject }.getOrNull() ?: return
        val type = payload.string("type")
        if (type == "Results") {
            val alternative = payload["channel"]?.jsonObject
                ?.get("alternatives")?.jsonArray
                ?.mapNotNull { it as? JsonObject }
                ?.firstOrNull()
                ?: return
            handleDeepgramTranscript(
                alternative,
                isFinal = payload.boolean("is_final") ?: payload.boolean("speech_final") ?: false,
            )
            return
        }
        if (type == "Metadata") {
            providerFinalizationReceived = true
            return
        }
        if (type == "TurnInfo" || payload.string("transcript") != null) {
            handleDeepgramTranscript(payload, isFinal = true)
            return
        }
        if (type == "Error" || payload["error"] != null) {
            scheduleReconnect(IllegalStateException(payload.string("message") ?: payload.string("description") ?: "Deepgram realtime transcription error"))
        }
    }

    private fun handleDeepgramTranscript(payload: JsonObject, isFinal: Boolean) {
        val transcript = payload.string("transcript").orEmpty().trim()
        if (transcript.isBlank()) return
        val words = payload["words"]?.jsonArray?.mapNotNull { it as? JsonObject }.orEmpty()
        if (!isFinal) {
            events.tryEmit(
                WsEvent.Transcript(
                    LiveTranscriptSegment(
                        text = transcript,
                        isFinal = false,
                        startMs = collectedSegments.lastOrNull()?.endMs ?: 0,
                        endMs = collectedSegments.lastOrNull()?.endMs ?: 0,
                        confidence = payload.double("confidence") ?: 0.0,
                    ),
                ),
            )
            return
        }
        if (words.isNotEmpty()) {
            val segments = deepgramSegments(
                words = words,
                fallbackTranscript = transcript,
                fallbackConfidence = payload.double("confidence"),
                fallbackStartMs = collectedSegments.lastOrNull()?.endMs ?: 0,
            )
            if (segments.isNotEmpty()) {
                segments.forEach { segment ->
                    collectedSegments += segment
                    markTranscriptReceived(finalizationMarker = endOfStreamRequested)
                    events.tryEmit(WsEvent.Transcript(segment))
                }
                return
            }
        }
        val segment = LiveTranscriptSegment(
            text = transcript,
            speaker = speakerLabel(words.firstOrNull()?.get("speaker")),
            isFinal = true,
            startMs = secondsTimestampMs(words.firstOrNull()?.get("start")) ?: (collectedSegments.lastOrNull()?.endMs ?: 0),
            endMs = secondsTimestampMs(words.lastOrNull()?.get("end")) ?: (collectedSegments.lastOrNull()?.endMs ?: 0),
            confidence = payload.double("confidence") ?: averageConfidence(words) ?: 0.0,
        )
        collectedSegments += segment
        markTranscriptReceived(finalizationMarker = endOfStreamRequested)
        events.tryEmit(WsEvent.Transcript(segment))
    }

    internal fun handleSonioxMessage(text: String) {
        val payload = runCatching { json.parseToJsonElement(text).jsonObject }.getOrNull() ?: return
        val errorCode = payload.string("error_code")
        if (!errorCode.isNullOrBlank()) {
            scheduleReconnect(IllegalStateException(payload.string("error_message") ?: "Soniox realtime transcription error: $errorCode"))
            return
        }
        if (payload.boolean("finished") == true) {
            providerFinalizationReceived = true
        }
        val tokens = payload["tokens"]?.jsonArray?.mapNotNull { it as? JsonObject }.orEmpty()
        if (tokens.any { it.boolean("is_final") == true && it.string("text") == "<fin>" }) {
            providerFinalizationReceived = true
        }
        val finalSegments = sonioxSegments(tokens.filter { it.boolean("is_final") == true }, isFinal = true)
        finalSegments.forEach { segment ->
            collectedSegments += segment
            markTranscriptReceived()
            events.tryEmit(WsEvent.Transcript(segment))
        }
        val interimSegments = sonioxSegments(tokens.filter { it.boolean("is_final") != true }, isFinal = false)
        interimSegments.forEach { segment ->
            events.tryEmit(WsEvent.Transcript(segment))
        }
    }

    private fun sonioxSegments(tokens: List<JsonObject>, isFinal: Boolean): List<LiveTranscriptSegment> {
        val speechTokens = tokens.filter {
            it.string("translation_status") != "translation" && it.string("text")?.startsWith("<") != true
        }
        if (speechTokens.isEmpty()) return emptyList()

        val segments = mutableListOf<LiveTranscriptSegment>()
        val currentTokens = mutableListOf<JsonObject>()
        var currentSpeaker: String? = null

        fun flush() {
            if (currentTokens.isEmpty()) return
            val transcript = currentTokens.joinToString(separator = "") { it.string("text").orEmpty() }.trim()
            if (transcript.isBlank()) {
                currentTokens.clear()
                return
            }
            val fallbackStart = segments.lastOrNull()?.endMs ?: collectedSegments.lastOrNull()?.endMs ?: 0
            segments += LiveTranscriptSegment(
                text = transcript,
                speaker = currentSpeaker,
                isFinal = isFinal,
                startMs = integerTimestampMs(currentTokens.firstOrNull()?.get("start_ms")) ?: fallbackStart,
                endMs = integerTimestampMs(currentTokens.lastOrNull()?.get("end_ms")) ?: fallbackStart,
                confidence = averageConfidence(currentTokens) ?: 0.0,
            )
            currentTokens.clear()
        }

        speechTokens.forEach { token ->
            val speaker = speakerLabel(token["speaker"])
            if (currentTokens.isNotEmpty() && speaker != currentSpeaker) {
                flush()
            }
            currentSpeaker = speaker
            currentTokens += token
        }
        flush()
        return segments
    }

    private fun deepgramSegments(
        words: List<JsonObject>,
        fallbackTranscript: String,
        fallbackConfidence: Double?,
        fallbackStartMs: Int,
    ): List<LiveTranscriptSegment> {
        val segments = mutableListOf<LiveTranscriptSegment>()
        val currentWords = mutableListOf<JsonObject>()
        var currentSpeaker: String? = null

        fun flush() {
            if (currentWords.isEmpty()) return
            val text = joinDeepgramWords(currentWords)
            if (text.isBlank()) {
                currentWords.clear()
                return
            }
            val startMs = secondsTimestampMs(currentWords.firstOrNull()?.get("start"))
                ?: segments.lastOrNull()?.endMs
                ?: fallbackStartMs
            segments += LiveTranscriptSegment(
                text = text,
                speaker = currentSpeaker,
                isFinal = true,
                startMs = startMs,
                endMs = secondsTimestampMs(currentWords.lastOrNull()?.get("end")) ?: startMs,
                confidence = averageConfidence(currentWords) ?: fallbackConfidence ?: 0.0,
            )
            currentWords.clear()
        }

        words.forEach { word ->
            if (deepgramWordText(word) == null) return@forEach
            val speaker = speakerLabel(word["speaker"])
            if (currentWords.isNotEmpty() && speaker != currentSpeaker) {
                flush()
            }
            currentSpeaker = speaker
            currentWords += word
        }
        flush()

        if (segments.isNotEmpty()) return segments
        val startMs = secondsTimestampMs(words.firstOrNull()?.get("start")) ?: fallbackStartMs
        return listOf(
            LiveTranscriptSegment(
                text = fallbackTranscript,
                speaker = speakerLabel(words.firstOrNull()?.get("speaker")),
                isFinal = true,
                startMs = startMs,
                endMs = secondsTimestampMs(words.lastOrNull()?.get("end")) ?: startMs,
                confidence = fallbackConfidence ?: averageConfidence(words) ?: 0.0,
            ),
        )
    }

    private fun deepgramWordText(word: JsonObject): String? {
        val text = word.string("punctuated_word") ?: word.string("word")
        return text?.trim()?.takeIf { it.isNotBlank() }
    }

    private fun joinDeepgramWords(words: List<JsonObject>): String {
        return words.mapNotNull(::deepgramWordText).fold("") { acc, word ->
            when {
                acc.isEmpty() -> word
                word.firstOrNull() in setOf('.', ',', '?', '!', ';', ':', '%', ')', ']', '}') -> acc + word
                else -> "$acc $word"
            }
        }.trim()
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
            "deepgram" -> buildDeepgramRequest(config)
            "soniox" -> buildSonioxRequest(config)
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
                    if (config.provider == "soniox") {
                        webSocket.send(makeSonioxRealtimeConfigMessage(config))
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
            val chunk = audioBuffer.removeFirst()
            if (currentConfig?.provider == "openai") {
                sendOpenAIAudio(socket, chunk)
            } else if (currentConfig?.provider == "deepgram" || currentConfig?.provider == "soniox") {
                socket.send(chunk.toByteString())
            } else {
                socket.send(makeAudioMessage(chunk, commit = false))
            }
        }
    }

    private suspend fun sendCommitChunkIfNeeded() {
        if (!endOfStreamRequested || endOfStreamSent || !connected) return
        when (currentConfig?.provider) {
            "openai" -> {
                if (openAIUncommittedAudioBytes > 0) {
                    commitOpenAIAudioBuffer()
                } else if (openAIPendingCommitCount == 0) {
                    providerFinalizationReceived = true
                }
            }
            "deepgram" -> webSocket?.send("""{"type":"CloseStream"}""")
            "soniox" -> {
                val silenceBytes = ((currentConfig?.sampleRate ?: 16_000) / 5) * 2
                webSocket?.send(ByteArray(silenceBytes).toByteString())
                webSocket?.send("""{"type":"finalize"}""")
                webSocket?.send("")
            }
            else -> webSocket?.send(makeAudioMessage(ByteArray(640), commit = true))
        }
        endOfStreamSent = true
    }

    private fun sendOpenAIAudio(socket: WebSocket, data: ByteArray) {
        socket.send(makeOpenAIAudioAppendMessage(data))
        openAIUncommittedAudioBytes += openAI24kMonoPCM(data).size
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

    private fun makeAudioMessage(data: ByteArray, commit: Boolean): String {
        return if (currentConfig?.provider == "openai") {
            if (commit) {
                """{"type":"input_audio_buffer.commit"}"""
            } else {
                makeOpenAIAudioAppendMessage(data)
            }
        } else if (currentConfig?.provider == "deepgram" || currentConfig?.provider == "soniox") {
            error("Binary audio path must be used for ${currentConfig?.provider}")
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

    internal fun makeSonioxRealtimeConfigMessage(config: RealtimeTranscriptionSessionConfig): String {
        val normalizedLanguage = config.language.trim().lowercase()
        val autoLanguage = normalizedLanguage.isBlank() ||
            normalizedLanguage == "multi" ||
            normalizedLanguage == "auto" ||
            normalizedLanguage == "und"
        return buildString {
            append("{")
            append("\"api_key\":\"").append(config.token).append("\",")
            append("\"model\":\"").append(config.model).append("\",")
            append("\"audio_format\":\"pcm_s16le\",")
            append("\"sample_rate\":").append(config.sampleRate).append(",")
            append("\"num_channels\":").append(config.channels).append(",")
            append("\"enable_speaker_diarization\":true,")
            append("\"enable_language_identification\":").append(autoLanguage).append(",")
            append("\"enable_endpoint_detection\":true,")
            append("\"max_endpoint_delay_ms\":500")
            if (!autoLanguage) {
                append(",\"language_hints\":[\"").append(normalizedLanguage).append("\"]")
            }
            append("}")
        }
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

    private fun secondsTimestampMs(value: JsonElement?): Int? {
        val primitive = value as? JsonPrimitive ?: return null
        val numeric = primitive.doubleOrNull ?: primitive.contentOrNull?.toDoubleOrNull() ?: return null
        return (numeric * 1_000).toInt()
    }

    private fun integerTimestampMs(value: JsonElement?): Int? {
        val primitive = value as? JsonPrimitive ?: return null
        return primitive.intOrNull ?: primitive.contentOrNull?.toIntOrNull()
    }

    private fun averageConfidence(words: List<JsonObject>): Double? {
        val values = words.mapNotNull { it.double("confidence") }
        if (values.isEmpty()) return null
        return values.average()
    }

    private fun speakerLabel(value: JsonElement?): String? {
        val primitive = value as? JsonPrimitive ?: return null
        val raw = primitive.contentOrNull ?: primitive.intOrNull?.toString() ?: return null
        if (raw.startsWith("Speaker", ignoreCase = true)) return raw
        return "Speaker $raw"
    }

    companion object {
        private const val MAX_RECONNECT_ATTEMPTS = 10
        private const val MINIMUM_CLOSE_WAIT_MS = 650L
        private const val NO_TRANSCRIPT_CLOSE_WAIT_MS = 2_500L
        private const val TRANSCRIPT_QUIET_WINDOW_MS = 900L
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
