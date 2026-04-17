package `is`.waiwai.say.library

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import `is`.waiwai.say.data.Recording
import `is`.waiwai.say.data.RecordingStatus
import `is`.waiwai.say.data.WaiApi
import `is`.waiwai.say.sync.LocalRecordingManifest
import `is`.waiwai.say.sync.LocalRecordingStore
import `is`.waiwai.say.ui.formatDuration
import `is`.waiwai.say.ui.formatRelativeTime
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class LibraryItemUiModel(
    val id: String,
    val title: String?,
    val type: `is`.waiwai.say.data.RecordingType,
    val status: RecordingStatus,
    val relativeTimeLabel: String,
    val createdAtLabel: String,
    val durationLabel: String,
    val failureMessage: String?,
    val localOnly: Boolean = false,
)

data class LibraryUiState(
    val isLoading: Boolean = true,
    val isRefreshing: Boolean = false,
    val items: List<LibraryItemUiModel> = emptyList(),
    val error: String? = null,
)

class LibraryViewModel(
    private val waiApi: WaiApi,
    private val localRecordingStore: LocalRecordingStore,
    private val isGuest: Boolean,
) : ViewModel() {
    private val _uiState = MutableStateFlow(LibraryUiState())
    val uiState: StateFlow<LibraryUiState> = _uiState.asStateFlow()

    init {
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            val hasItems = _uiState.value.items.isNotEmpty()
            _uiState.value = _uiState.value.copy(
                isLoading = !hasItems,
                isRefreshing = hasItems,
                error = null,
            )
            runCatching {
                if (isGuest) {
                    localRecordingStore.listPending().map { it.toUiModel() }
                } else {
                    waiApi.listRecordings().map { it.toUiModel() } +
                        localRecordingStore.listPending()
                            .filter { !it.localOnly }
                            .map { it.toUiModel() }
                }
            }.onSuccess { items ->
                _uiState.value = LibraryUiState(
                    isLoading = false,
                    isRefreshing = false,
                    items = items.sortedByDescending { it.createdAtLabel },
                )
            }.onFailure { error ->
                _uiState.value = LibraryUiState(
                    isLoading = false,
                    isRefreshing = false,
                    error = error.message,
                )
            }
        }
    }

    fun delete(recordingId: String, localOnly: Boolean) {
        viewModelScope.launch {
            if (localOnly) {
                localRecordingStore.remove(recordingId)
            } else {
                waiApi.deleteRecording(recordingId)
            }
            refresh()
        }
    }

    private fun Recording.toUiModel(): LibraryItemUiModel {
        return LibraryItemUiModel(
            id = id,
            title = title?.takeIf { it.isNotBlank() },
            type = type,
            status = status,
            relativeTimeLabel = formatRelativeTime(createdAt),
            createdAtLabel = createdAt,
            durationLabel = formatDuration(durationSeconds?.toLong() ?: 0L),
            failureMessage = failureMessage,
            localOnly = false,
        )
    }

    private fun LocalRecordingManifest.toUiModel(): LibraryItemUiModel {
        return LibraryItemUiModel(
            id = recordingId,
            title = title?.takeIf { it.isNotBlank() },
            type = recordingType,
            status = if (failureMessage != null) RecordingStatus.Failed else RecordingStatus.PendingUpload,
            relativeTimeLabel = formatRelativeTime(java.time.Instant.ofEpochMilli(createdAtEpochMillis).toString()),
            createdAtLabel = java.time.Instant.ofEpochMilli(createdAtEpochMillis).toString(),
            durationLabel = formatDuration(durationSeconds),
            failureMessage = failureMessage,
            localOnly = localOnly || serverRecordingId == null,
        )
    }
}
