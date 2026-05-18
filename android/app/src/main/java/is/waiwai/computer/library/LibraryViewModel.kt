package `is`.waiwai.computer.library

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import `is`.waiwai.computer.data.Recording
import `is`.waiwai.computer.data.RecordingStatus
import `is`.waiwai.computer.data.WaiApi
import `is`.waiwai.computer.sync.LocalRecordingManifest
import `is`.waiwai.computer.sync.LocalRecordingStore
import `is`.waiwai.computer.ui.formatDuration
import `is`.waiwai.computer.ui.formatRelativeTime
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

enum class LibraryFilter {
    All,
    Starred,
    Trash,
}

data class LibraryItemUiModel(
    val id: String,
    val title: String?,
    val type: `is`.waiwai.computer.data.RecordingType,
    val status: RecordingStatus,
    val relativeTimeLabel: String,
    val createdAtLabel: String,
    val durationLabel: String,
    val failureMessage: String?,
    val isStarred: Boolean = false,
    val isTrashed: Boolean = false,
    val localOnly: Boolean = false,
)

data class LibraryUiState(
    val isLoading: Boolean = true,
    val isRefreshing: Boolean = false,
    val filter: LibraryFilter = LibraryFilter.All,
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

    fun setFilter(filter: LibraryFilter) {
        if (_uiState.value.filter == filter) return
        _uiState.value = _uiState.value.copy(filter = filter, items = emptyList(), isLoading = true)
        refresh()
    }

    fun refresh() {
        val filter = _uiState.value.filter
        viewModelScope.launch {
            val hasItems = _uiState.value.items.isNotEmpty()
            _uiState.value = _uiState.value.copy(
                isLoading = !hasItems,
                isRefreshing = hasItems,
                error = null,
            )
            runCatching {
                if (isGuest) {
                    // Guests only have local recordings; filters don't apply.
                    localRecordingStore.listPending().map { it.toUiModel() }
                } else {
                    when (filter) {
                        LibraryFilter.All -> {
                            waiApi.listRecordings(
                                limit = 50,
                                skip = 0,
                                starred = false,
                                trashed = false,
                                type = null,
                                folderId = null,
                            ).map { it.toUiModel() } +
                                localRecordingStore.listPending()
                                    .filter { !it.localOnly }
                                    .map { it.toUiModel() }
                        }
                        LibraryFilter.Starred ->
                            waiApi.listRecordings(
                                limit = 50,
                                skip = 0,
                                starred = true,
                                trashed = false,
                                type = null,
                                folderId = null,
                            ).map { it.toUiModel() }
                        LibraryFilter.Trash ->
                            waiApi.listRecordings(
                                limit = 50,
                                skip = 0,
                                starred = false,
                                trashed = true,
                                type = null,
                                folderId = null,
                            ).map { it.toUiModel() }
                    }
                }
            }.onSuccess { items ->
                _uiState.value = _uiState.value.copy(
                    isLoading = false,
                    isRefreshing = false,
                    items = items.sortedByDescending { it.createdAtLabel },
                    error = null,
                )
            }.onFailure { error ->
                _uiState.value = _uiState.value.copy(
                    isLoading = false,
                    isRefreshing = false,
                    items = emptyList(),
                    error = error.message,
                )
            }
        }
    }

    fun toggleStar(recordingId: String) {
        val current = _uiState.value.items.firstOrNull { it.id == recordingId } ?: return
        val target = !current.isStarred
        // Optimistic update.
        _uiState.value = _uiState.value.copy(
            items = _uiState.value.items.map {
                if (it.id == recordingId) it.copy(isStarred = target) else it
            },
        )
        viewModelScope.launch {
            runCatching {
                if (target) waiApi.starRecording(recordingId) else waiApi.unstarRecording(recordingId)
            }.onFailure {
                // Revert on failure.
                _uiState.value = _uiState.value.copy(
                    items = _uiState.value.items.map {
                        if (it.id == recordingId) it.copy(isStarred = !target) else it
                    },
                    error = it.message,
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

    fun restore(recordingId: String) {
        viewModelScope.launch {
            runCatching { waiApi.restoreRecording(recordingId) }
                .onSuccess { refresh() }
                .onFailure { _uiState.value = _uiState.value.copy(error = it.message) }
        }
    }

    fun deleteForever(recordingId: String) {
        viewModelScope.launch {
            runCatching { waiApi.deleteRecording(recordingId, permanent = true) }
                .onSuccess { refresh() }
                .onFailure { _uiState.value = _uiState.value.copy(error = it.message) }
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
            isStarred = !starredAt.isNullOrBlank(),
            isTrashed = !deletedAt.isNullOrBlank(),
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
