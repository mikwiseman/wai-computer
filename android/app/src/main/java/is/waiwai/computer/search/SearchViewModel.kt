package `is`.waiwai.computer.search

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import `is`.waiwai.computer.data.SearchMode
import `is`.waiwai.computer.data.SearchResult
import `is`.waiwai.computer.data.WaiApi
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class SearchUiState(
    val query: String = "",
    val mode: SearchMode = SearchMode.Hybrid,
    val results: List<SearchResult> = emptyList(),
    val total: Int = 0,
    val isLoading: Boolean = false,
    val hasSearched: Boolean = false,
    val error: String? = null,
)

class SearchViewModel(
    private val waiApi: WaiApi,
) : ViewModel() {
    private val _uiState = MutableStateFlow(SearchUiState())
    val uiState: StateFlow<SearchUiState> = _uiState.asStateFlow()

    private var inflight: Job? = null

    fun updateQuery(value: String) {
        _uiState.value = _uiState.value.copy(query = value)
    }

    fun selectMode(mode: SearchMode) {
        val current = _uiState.value
        if (current.mode == mode) return
        _uiState.value = current.copy(mode = mode)
        if (current.query.isNotBlank() && current.hasSearched) {
            submit()
        }
    }

    fun clear() {
        inflight?.cancel()
        _uiState.value = SearchUiState()
    }

    fun submit() {
        val state = _uiState.value
        val trimmed = state.query.trim()
        if (trimmed.isEmpty()) return
        inflight?.cancel()
        inflight = viewModelScope.launch {
            _uiState.value = state.copy(isLoading = true, error = null)
            runCatching { waiApi.search(query = trimmed, mode = state.mode) }
                .onSuccess { response ->
                    _uiState.value = _uiState.value.copy(
                        results = response.results,
                        total = response.total,
                        isLoading = false,
                        hasSearched = true,
                        error = null,
                    )
                }
                .onFailure { error ->
                    _uiState.value = _uiState.value.copy(
                        results = emptyList(),
                        total = 0,
                        isLoading = false,
                        hasSearched = true,
                        error = error.message ?: "Search failed.",
                    )
                }
        }
    }
}
