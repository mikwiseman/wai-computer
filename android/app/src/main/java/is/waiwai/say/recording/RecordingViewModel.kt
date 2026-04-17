package `is`.waiwai.say.recording

import android.app.Application
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import `is`.waiwai.say.auth.AuthState
import `is`.waiwai.say.auth.AuthStore
import `is`.waiwai.say.data.LiveTranscriptSegment
import `is`.waiwai.say.data.RecordingType
import `is`.waiwai.say.data.SettingsStore
import `is`.waiwai.say.data.WaiApi
import `is`.waiwai.say.sync.LocalRecordingManifest
import `is`.waiwai.say.sync.LocalRecordingStore
import `is`.waiwai.say.sync.PendingSyncWorkerScheduler
import java.util.UUID
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

enum class Phase {
    Idle,
    Preparing,
    Recording,
    Finalizing,
}

sealed interface ConnectionState {
    data object Connected : ConnectionState
    data class Reconnecting(val attempt: Int, val max: Int) : ConnectionState
}

data class RecordingUiState(
    val phase: Phase = Phase.Idle,
    val durationSeconds: Long = 0,
    val transcript: String = "",
    val connectionState: ConnectionState = ConnectionState.Connected,
    val liveTranscriptionOffline: Boolean = false,
    val isServerComplete: Boolean = false,
    val recordingType: RecordingType = RecordingType.note,
    val error: String? = null,
)

class RecordingViewModel(
    private val application: Application,
    private val authStore: AuthStore,
    private val settingsStore: SettingsStore,
    private val waiApi: WaiApi,
    private val localRecordingStore: LocalRecordingStore,
    private val syncScheduler: PendingSyncWorkerScheduler,
    private val audioRecorderFactory: () -> AudioRecorder = { AndroidAudioRecorder(application) },
    private val webSocketFactory: (String) -> RealtimeWebSocketManager = { language ->
        ElevenLabsWebSocketManager(waiApi, language)
    },
) : ViewModel() {
    private val _uiState = MutableStateFlow(RecordingUiState())
    val uiState: StateFlow<RecordingUiState> = _uiState.asStateFlow()

    private var audioRecorder: AudioRecorder? = null
    private var audioWriter: AudioFileWriter? = null
    private var audioJob: Job? = null
    private var wsJob: Job? = null
    private var webSocket: RealtimeWebSocketManager? = null
    private val audioEncoder = AudioEncoder()
    private var currentRecordingId: String? = null
    private var currentServerRecordingId: String? = null
    private var committedTranscript = ""
    private var interimTranscript = ""

    fun updateRecordingType(type: RecordingType) {
        _uiState.value = _uiState.value.copy(recordingType = type)
    }

    fun clearError() {
        _uiState.value = _uiState.value.copy(error = null)
    }

    fun startRecording(permissionGranted: Boolean) {
        if (!permissionGranted) {
            _uiState.value = _uiState.value.copy(
                error = application.getString(`is`.waiwai.say.R.string.record_permission_denied),
            )
            return
        }
        if (_uiState.value.phase != Phase.Idle) return

        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(
                phase = Phase.Preparing,
                error = null,
                transcript = "",
                durationSeconds = 0,
                liveTranscriptionOffline = false,
                isServerComplete = false,
                connectionState = ConnectionState.Connected,
            )
            committedTranscript = ""
            interimTranscript = ""

            val settings = settingsStore.snapshot()
            val authState = authStore.state.value
            val isGuest = authState is AuthState.Guest
            val language = settings.transcriptionLanguage
            val recordingId = if (isGuest) {
                UUID.randomUUID().toString()
            } else {
                waiApi.createRecording(type = _uiState.value.recordingType, language = language).id
            }

            currentRecordingId = recordingId
            currentServerRecordingId = if (isGuest) null else recordingId
            val audioFile = localRecordingStore.audioFile(recordingId)
            audioWriter = AudioFileWriter(audioFile)
            audioRecorder = audioRecorderFactory()
            RecordingForegroundService.start(application)

            if (!isGuest) {
                val ws = webSocketFactory(language)
                webSocket = ws
                runCatching { ws.connect() }
                    .onFailure {
                        _uiState.value = _uiState.value.copy(liveTranscriptionOffline = true)
                    }
                wsJob = viewModelScope.launch {
                    ws.events.collect { event ->
                        when (event) {
                            WsEvent.Connected,
                            WsEvent.Reconnected,
                            -> _uiState.value = _uiState.value.copy(connectionState = ConnectionState.Connected)
                            is WsEvent.Reconnecting -> {
                                _uiState.value = _uiState.value.copy(
                                    connectionState = ConnectionState.Reconnecting(event.attempt, event.max),
                                )
                            }
                            is WsEvent.ReconnectionFailed,
                            is WsEvent.Disconnected,
                            -> _uiState.value = _uiState.value.copy(liveTranscriptionOffline = true)
                            is WsEvent.Transcript -> applyTranscript(event.segment)
                        }
                    }
                }
            }

            audioJob = viewModelScope.launch {
                audioRecorder?.start()?.collect { frame ->
                    audioWriter?.write(frame)
                    val duration = (audioWriter?.durationSeconds() ?: 0L)
                    _uiState.value = _uiState.value.copy(durationSeconds = duration)
                    val encoded = audioEncoder.encode(frame)
                    runCatching { webSocket?.sendAudio(encoded) }
                        .onFailure {
                            _uiState.value = _uiState.value.copy(liveTranscriptionOffline = true)
                        }
                }
            }

            _uiState.value = _uiState.value.copy(phase = Phase.Recording)
        }
    }

    fun stopRecording() {
        if (_uiState.value.phase != Phase.Recording) return

        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(phase = Phase.Finalizing)
            audioRecorder?.stop()
            audioJob?.join()
            audioWriter?.finalizeFile()
            val didFinalize = webSocket?.finishStreaming() ?: false
            wsJob?.cancel()
            val recordingId = currentRecordingId ?: return@launch reset()
            val segments = webSocket?.collectedSegments.orEmpty()
            val duration = _uiState.value.durationSeconds

            val isGuest = authStore.state.value is AuthState.Guest
            if (isGuest) {
                localRecordingStore.save(
                    LocalRecordingManifest(
                        recordingId = recordingId,
                        title = null,
                        recordingType = _uiState.value.recordingType,
                        durationSeconds = duration,
                        transcript = null,
                        hasAudioFile = true,
                        localOnly = true,
                        requiresAuthentication = true,
                    ),
                    segments = segments,
                )
                reset()
                return@launch
            }

            val serverRecordingId = currentServerRecordingId ?: recordingId
            runCatching {
                if (segments.isNotEmpty() && didFinalize) {
                    waiApi.saveLiveTranscript(serverRecordingId, segments, duration.toInt())
                } else {
                    waiApi.uploadAudio(serverRecordingId, localRecordingStore.audioFile(recordingId))
                }
            }.onSuccess {
                localRecordingStore.remove(recordingId)
                _uiState.value = _uiState.value.copy(isServerComplete = true)
            }.onFailure { error ->
                localRecordingStore.save(
                    LocalRecordingManifest(
                        recordingId = recordingId,
                        serverRecordingId = serverRecordingId,
                        title = null,
                        recordingType = _uiState.value.recordingType,
                        durationSeconds = duration,
                        transcript = segments.joinToString(" ") { it.text }.ifBlank { null },
                        hasAudioFile = true,
                        failureMessage = error.message,
                        localOnly = false,
                    ),
                    segments = segments,
                )
                syncScheduler.enqueue()
                _uiState.value = _uiState.value.copy(error = error.message)
            }

            reset()
        }
    }

    private fun applyTranscript(segment: LiveTranscriptSegment) {
        if (segment.isFinal) {
            committedTranscript = listOf(committedTranscript, segment.text)
                .filter { it.isNotBlank() }
                .joinToString(" ")
            interimTranscript = ""
        } else {
            interimTranscript = segment.text
        }
        _uiState.value = _uiState.value.copy(
            transcript = listOf(committedTranscript, interimTranscript)
                .filter { it.isNotBlank() }
                .joinToString(" "),
        )
    }

    private suspend fun reset() {
        RecordingForegroundService.stop(application)
        audioRecorder = null
        audioWriter = null
        webSocket = null
        audioJob = null
        wsJob = null
        currentRecordingId = null
        currentServerRecordingId = null
        committedTranscript = ""
        interimTranscript = ""
        _uiState.value = _uiState.value.copy(
            phase = Phase.Idle,
            durationSeconds = 0,
            transcript = "",
            connectionState = ConnectionState.Connected,
            liveTranscriptionOffline = false,
        )
    }
}
