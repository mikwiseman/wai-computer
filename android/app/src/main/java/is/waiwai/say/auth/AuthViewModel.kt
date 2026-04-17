package `is`.waiwai.say.auth

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import `is`.waiwai.say.data.ApiError
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class AuthUiState(
    val isBusy: Boolean = false,
    val globalError: String? = null,
    val magicLinkSent: Boolean = false,
)

class AuthViewModel(
    private val authStore: AuthStore,
) : ViewModel() {
    private val _uiState = MutableStateFlow(AuthUiState())
    val uiState: StateFlow<AuthUiState> = _uiState.asStateFlow()

    fun clearError() {
        _uiState.value = _uiState.value.copy(globalError = null)
    }

    fun login(email: String, password: String) {
        submit {
            authStore.login(email, password)
            _uiState.value = AuthUiState()
        }
    }

    fun register(email: String, password: String) {
        submit {
            authStore.register(email, password)
            _uiState.value = AuthUiState()
        }
    }

    fun requestMagicLink(email: String) {
        submit {
            authStore.requestMagicLink(email)
            _uiState.value = AuthUiState(magicLinkSent = true)
        }
    }

    fun verifyMagicLink(token: String) {
        submit {
            authStore.verifyMagicLink(token)
            _uiState.value = AuthUiState()
        }
    }

    fun continueAsGuest() {
        submit {
            authStore.continueAsGuest()
            _uiState.value = AuthUiState()
        }
    }

    fun logout() {
        submit {
            authStore.logout()
            _uiState.value = AuthUiState()
        }
    }

    private fun submit(block: suspend () -> Unit) {
        viewModelScope.launch {
            _uiState.value = _uiState.value.copy(isBusy = true, globalError = null)
            runCatching { block() }
                .onFailure { error ->
                    val message = when (error) {
                        is ApiError.Http -> if (error.statusCode == 429) {
                            "Too many attempts, try again in a minute."
                        } else {
                            error.detail ?: error.message.orEmpty()
                        }
                        else -> error.message ?: "Something went wrong."
                    }
                    _uiState.value = _uiState.value.copy(
                        isBusy = false,
                        globalError = message,
                    )
                }
                .onSuccess {
                    _uiState.value = _uiState.value.copy(isBusy = false)
                }
        }
    }
}
