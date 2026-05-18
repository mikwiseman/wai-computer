package `is`.waiwai.computer.library

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import `is`.waiwai.computer.data.Folder
import `is`.waiwai.computer.data.WaiApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class FolderManagerUiState(
    val folders: List<Folder> = emptyList(),
    val isLoading: Boolean = true,
    val error: String? = null,
    val pendingActionId: String? = null,
)

class FolderManagerViewModel(
    private val waiApi: WaiApi,
) : ViewModel() {
    private val _uiState = MutableStateFlow(FolderManagerUiState())
    val uiState: StateFlow<FolderManagerUiState> = _uiState.asStateFlow()

    init {
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isLoading = true, error = null)
            runCatching { waiApi.listFolders() }
                .onSuccess { folders ->
                    _uiState.value = _uiState.value.copy(
                        folders = folders.sortedBy { it.name.lowercase() },
                        isLoading = false,
                        error = null,
                    )
                }
                .onFailure { error ->
                    _uiState.value = _uiState.value.copy(
                        isLoading = false,
                        error = error.message,
                    )
                }
        }
    }

    fun create(name: String) {
        val trimmed = name.trim()
        if (trimmed.isEmpty()) return
        viewModelScope.launch {
            runCatching { waiApi.createFolder(trimmed) }
                .onSuccess { folder ->
                    _uiState.value = _uiState.value.copy(
                        folders = (_uiState.value.folders + folder).sortedBy { it.name.lowercase() },
                        error = null,
                    )
                }
                .onFailure { error ->
                    _uiState.value = _uiState.value.copy(error = error.message)
                }
        }
    }

    fun rename(folderId: String, newName: String) {
        val trimmed = newName.trim()
        if (trimmed.isEmpty()) return
        _uiState.value = _uiState.value.copy(pendingActionId = folderId)
        viewModelScope.launch {
            runCatching { waiApi.renameFolder(folderId, trimmed) }
                .onSuccess { updated ->
                    _uiState.value = _uiState.value.copy(
                        folders = _uiState.value.folders.map { if (it.id == folderId) updated else it }
                            .sortedBy { it.name.lowercase() },
                        pendingActionId = null,
                        error = null,
                    )
                }
                .onFailure { error ->
                    _uiState.value = _uiState.value.copy(
                        pendingActionId = null,
                        error = error.message,
                    )
                }
        }
    }

    fun delete(folderId: String) {
        _uiState.value = _uiState.value.copy(pendingActionId = folderId)
        viewModelScope.launch {
            runCatching { waiApi.deleteFolder(folderId) }
                .onSuccess {
                    _uiState.value = _uiState.value.copy(
                        folders = _uiState.value.folders.filterNot { it.id == folderId },
                        pendingActionId = null,
                        error = null,
                    )
                }
                .onFailure { error ->
                    _uiState.value = _uiState.value.copy(
                        pendingActionId = null,
                        error = error.message,
                    )
                }
        }
    }

    fun clearError() {
        _uiState.value = _uiState.value.copy(error = null)
    }
}
