package `is`.waiwai.computer.people

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import `is`.waiwai.computer.data.Person
import `is`.waiwai.computer.data.WaiApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class PeopleManagerUiState(
    val people: List<Person> = emptyList(),
    val isLoading: Boolean = true,
    val error: String? = null,
    val pendingActionId: String? = null,
)

class PeopleManagerViewModel(
    private val waiApi: WaiApi,
) : ViewModel() {
    private val _uiState = MutableStateFlow(PeopleManagerUiState())
    val uiState: StateFlow<PeopleManagerUiState> = _uiState.asStateFlow()

    init {
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isLoading = true, error = null)
            runCatching { waiApi.listPeople() }
                .onSuccess { people ->
                    _uiState.value = _uiState.value.copy(
                        people = people.sortedBy { it.displayName.lowercase() },
                        isLoading = false,
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

    fun rename(personId: String, newName: String) {
        val trimmed = newName.trim()
        if (trimmed.isEmpty()) return
        _uiState.value = _uiState.value.copy(pendingActionId = personId)
        viewModelScope.launch {
            runCatching { waiApi.updatePerson(id = personId, displayName = trimmed) }
                .onSuccess { updated ->
                    _uiState.value = _uiState.value.copy(
                        people = _uiState.value.people
                            .map { if (it.id == personId) updated else it }
                            .sortedBy { it.displayName.lowercase() },
                        pendingActionId = null,
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

    fun delete(personId: String) {
        _uiState.value = _uiState.value.copy(pendingActionId = personId)
        viewModelScope.launch {
            runCatching { waiApi.deletePerson(personId) }
                .onSuccess {
                    _uiState.value = _uiState.value.copy(
                        people = _uiState.value.people.filterNot { it.id == personId },
                        pendingActionId = null,
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
