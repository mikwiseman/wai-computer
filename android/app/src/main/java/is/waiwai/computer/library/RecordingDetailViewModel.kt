package `is`.waiwai.computer.library

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import `is`.waiwai.computer.data.ActionItemStatus
import `is`.waiwai.computer.data.Folder
import `is`.waiwai.computer.data.RecordingDetail
import `is`.waiwai.computer.data.RecordingStatus
import `is`.waiwai.computer.data.WaiApi
import `is`.waiwai.computer.sync.LocalRecordingManifest
import `is`.waiwai.computer.sync.LocalRecordingStore
import java.io.File
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class RecordingDetailUiState(
    val isLoading: Boolean = true,
    val detail: RecordingDetail? = null,
    val localManifest: LocalRecordingManifest? = null,
    val folders: List<Folder> = emptyList(),
    val isRetryingUpload: Boolean = false,
    val error: String? = null,
)

class RecordingDetailViewModel(
    private val waiApi: WaiApi,
    private val localRecordingStore: LocalRecordingStore,
    private val recordingId: String,
    private val localOnly: Boolean,
) : ViewModel() {
    private val _uiState = MutableStateFlow(RecordingDetailUiState())
    val uiState: StateFlow<RecordingDetailUiState> = _uiState.asStateFlow()

    private var pollJob: Job? = null

    init {
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isLoading = true, error = null)
            runCatching {
                val localManifest = localRecordingStore.manifest(recordingId)
                if (localOnly) {
                    RecordingDetailUiState(
                        isLoading = false,
                        localManifest = localManifest,
                    )
                } else {
                    val detail = waiApi.getRecording(recordingId)
                    RecordingDetailUiState(
                        isLoading = false,
                        detail = detail,
                        localManifest = localManifest,
                        folders = waiApi.listFolders(),
                    )
                }
            }.onSuccess {
                _uiState.value = it
                schedulePollingIfNeeded(it.detail)
            }.onFailure { error ->
                _uiState.value = RecordingDetailUiState(
                    isLoading = false,
                    error = error.message,
                )
            }
        }
    }

    fun updateTitle(title: String) {
        if (localOnly) return
        viewModelScope.launch {
            runCatching { waiApi.updateRecordingTitle(recordingId, title.trim().ifBlank { null }) }
                .onSuccess { refresh() }
                .onFailure { error ->
                    _uiState.value = _uiState.value.copy(error = error.message)
                }
        }
    }

    fun assignSpeaker(rawLabel: String, personId: String? = null, newDisplayName: String? = null) {
        if (localOnly) return
        viewModelScope.launch {
            runCatching {
                waiApi.assignSpeaker(
                    recordingId = recordingId,
                    rawLabel = rawLabel,
                    personId = personId,
                    newDisplayName = newDisplayName,
                )
            }.onSuccess { updated ->
                _uiState.value = _uiState.value.copy(detail = updated, error = null)
            }.onFailure { error ->
                _uiState.value = _uiState.value.copy(error = error.message)
            }
        }
    }

    suspend fun listPeople(): List<`is`.waiwai.computer.data.Person> =
        runCatching { waiApi.listPeople() }.getOrElse { emptyList() }

    fun moveToFolder(folderId: String?) {
        if (localOnly) return
        viewModelScope.launch {
            runCatching { waiApi.moveRecording(recordingId, folderId) }
                .onSuccess { refresh() }
                .onFailure { error ->
                    _uiState.value = _uiState.value.copy(error = error.message)
                }
        }
    }

    fun deleteRecording(onDeleted: () -> Unit) {
        viewModelScope.launch {
            runCatching {
                if (_uiState.value.localManifest != null) {
                    localRecordingStore.remove(recordingId)
                }
                if (!localOnly) {
                    waiApi.deleteRecording(recordingId)
                }
            }.onSuccess {
                onDeleted()
            }.onFailure { error ->
                _uiState.value = _uiState.value.copy(error = error.message)
            }
        }
    }

    fun toggleActionItem(id: String, current: ActionItemStatus) {
        if (localOnly) return
        val next = if (current == ActionItemStatus.Completed) ActionItemStatus.Pending else ActionItemStatus.Completed
        viewModelScope.launch {
            runCatching { waiApi.updateActionItem(id, next) }
                .onSuccess { refresh() }
                .onFailure { error ->
                    _uiState.value = _uiState.value.copy(error = error.message)
                }
        }
    }

    fun retryUpload() {
        if (localOnly) return
        val manifest = _uiState.value.localManifest ?: return
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isRetryingUpload = true, error = null)
            runCatching {
                val serverRecordingId = manifest.serverRecordingId ?: recordingId
                val audioFile = localRecordingStore.audioFile(manifest.recordingId)
                if (audioFile.exists()) {
                    waiApi.uploadAudio(serverRecordingId, audioFile)
                } else {
                    waiApi.saveLiveTranscript(
                        recordingId = serverRecordingId,
                        segments = localRecordingStore.loadSegments(manifest.recordingId),
                        durationSeconds = manifest.durationSeconds.toInt(),
                    )
                }
                localRecordingStore.remove(manifest.recordingId)
            }.onSuccess {
                refresh()
            }.onFailure { error ->
                _uiState.value = _uiState.value.copy(
                    isRetryingUpload = false,
                    error = error.message,
                )
            }
        }
    }

    fun audioFile(): File? {
        val manifest = _uiState.value.localManifest ?: return null
        val audioFile = localRecordingStore.audioFile(manifest.recordingId)
        return audioFile.takeIf(File::exists)
    }

    private fun schedulePollingIfNeeded(detail: RecordingDetail?) {
        pollJob?.cancel()
        if (detail?.status != RecordingStatus.Processing) return
        pollJob = viewModelScope.launch {
            while (_uiState.value.detail?.status == RecordingStatus.Processing) {
                delay(4_000)
                runCatching { waiApi.getRecording(recordingId) }
                    .onSuccess { refreshed ->
                        _uiState.value = _uiState.value.copy(detail = refreshed, isLoading = false)
                        if (refreshed.status != RecordingStatus.Processing) {
                            cancelPolling()
                        }
                    }
                    .onFailure { error ->
                        _uiState.value = _uiState.value.copy(error = error.message)
                        cancelPolling()
                    }
            }
        }
    }

    private fun cancelPolling() {
        pollJob?.cancel()
        pollJob = null
    }

    override fun onCleared() {
        cancelPolling()
        super.onCleared()
    }
}
