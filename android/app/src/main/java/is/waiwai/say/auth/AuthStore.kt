package `is`.waiwai.say.auth

import `is`.waiwai.say.data.ApiError
import `is`.waiwai.say.data.ApiTransport
import `is`.waiwai.say.data.AuthStoreContract
import `is`.waiwai.say.data.AuthTokenPair
import `is`.waiwai.say.data.LoginRequest
import `is`.waiwai.say.data.LogoutRequest
import `is`.waiwai.say.data.MagicLinkRequest
import `is`.waiwai.say.data.MessageResponse
import `is`.waiwai.say.data.RefreshRequest
import `is`.waiwai.say.data.RegisterRequest
import `is`.waiwai.say.data.SecureTokenStore
import `is`.waiwai.say.data.SettingsStore
import `is`.waiwai.say.data.StoredAuthMode
import `is`.waiwai.say.data.UserSummary
import `is`.waiwai.say.data.VerifyMagicLinkRequest
import `is`.waiwai.say.monitoring.SentryHelper
import java.time.Instant
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

sealed interface AuthState {
    data object Unknown : AuthState
    data object Onboarding : AuthState
    data class Guest(val since: Instant) : AuthState
    data class Authenticated(val user: UserSummary) : AuthState
    data class SessionExpired(val reason: String) : AuthState
}

class AuthStore(
    private val settingsStore: SettingsStore,
    private val secureTokenStore: SecureTokenStore,
    private val transport: ApiTransport,
) : AuthStoreContract {
    private val refreshMutex = Mutex()
    private val bootstrapMutex = Mutex()

    private val _state = MutableStateFlow<AuthState>(AuthState.Unknown)
    val state: StateFlow<AuthState> = _state.asStateFlow()

    override suspend fun currentAccessToken(): String? {
        return secureTokenStore.readAccessToken() ?: settingsStore.snapshot().legacyAccessToken
    }

    suspend fun currentRefreshToken(): String? = secureTokenStore.readRefreshToken()

    suspend fun bootstrap() {
        bootstrapMutex.withLock {
            val settings = settingsStore.snapshot()
            val accessToken = secureTokenStore.readAccessToken() ?: settings.legacyAccessToken
            val refreshToken = secureTokenStore.readRefreshToken()

            if (accessToken.isNullOrBlank()) {
                _state.value = when (settings.authMode) {
                    StoredAuthMode.Guest -> AuthState.Guest(
                        Instant.ofEpochMilli(settings.guestSinceEpochMillis ?: Instant.now().toEpochMilli()),
                    )
                    else -> AuthState.Onboarding
                }
                return
            }

            try {
                val user = fetchMe(accessToken)
                settingsStore.setAuthMode(StoredAuthMode.Authenticated, userId = user.id)
                _state.value = AuthState.Authenticated(user)
                SentryHelper.setUser(user.id)
                return
            } catch (error: ApiError) {
                if (error is ApiError.Unauthorized && !refreshToken.isNullOrBlank() && refresh()) {
                    val user = fetchMe(requireNotNull(secureTokenStore.readAccessToken()))
                    settingsStore.setAuthMode(StoredAuthMode.Authenticated, userId = user.id)
                    _state.value = AuthState.Authenticated(user)
                    SentryHelper.setUser(user.id)
                    return
                }
            }

            secureTokenStore.clearAll()
            settingsStore.clearLegacyAccessToken()
            settingsStore.setAuthMode(StoredAuthMode.Onboarding)
            SentryHelper.clearUser()
            _state.value = AuthState.Onboarding
        }
    }

    suspend fun login(email: String, password: String): UserSummary {
        val response = transport.request<AuthTokenPair>(
            method = io.ktor.http.HttpMethod.Post,
            path = "/api/auth/login",
            body = LoginRequest(email = email.trim(), password = password),
        )
        return persistTokensAndUser(response)
    }

    suspend fun register(email: String, password: String): UserSummary {
        val response = transport.request<AuthTokenPair>(
            method = io.ktor.http.HttpMethod.Post,
            path = "/api/auth/register",
            body = RegisterRequest(email = email.trim(), password = password),
        )
        return persistTokensAndUser(response)
    }

    suspend fun requestMagicLink(email: String): MessageResponse {
        return transport.request(
            method = io.ktor.http.HttpMethod.Post,
            path = "/api/auth/magic-link",
            body = MagicLinkRequest(email = email.trim(), client = "android"),
        )
    }

    suspend fun verifyMagicLink(token: String): UserSummary {
        val response = transport.request<AuthTokenPair>(
            method = io.ktor.http.HttpMethod.Post,
            path = "/api/auth/verify-magic",
            body = VerifyMagicLinkRequest(token = token),
        )
        return persistTokensAndUser(response)
    }

    suspend fun continueAsGuest() {
        val now = Instant.now()
        secureTokenStore.clearAll()
        settingsStore.clearLegacyAccessToken()
        settingsStore.markOnboardingSeen()
        settingsStore.setAuthMode(
            mode = StoredAuthMode.Guest,
            guestSinceEpochMillis = now.toEpochMilli(),
        )
        SentryHelper.clearUser()
        _state.value = AuthState.Guest(now)
    }

    suspend fun logout() {
        val refreshToken = secureTokenStore.readRefreshToken()
        try {
            transport.request<MessageResponse>(
                method = io.ktor.http.HttpMethod.Post,
                path = "/api/auth/logout",
                body = LogoutRequest(refreshToken = refreshToken),
                bearerToken = secureTokenStore.readAccessToken(),
            )
        } catch (_: Throwable) {
            // Deliberately ignore logout transport failures; local auth must still be cleared.
        }
        clearLocalSession()
    }

    /**
     * Permanently delete the current account on the server and clear local
     * credentials. Required by App Store / Play policy so the same flow is
     * available to users who signed up on any platform.
     */
    suspend fun deleteAccount(): MessageResponse {
        val response = transport.request<MessageResponse>(
            method = io.ktor.http.HttpMethod.Delete,
            path = "/api/auth/me",
            bearerToken = secureTokenStore.readAccessToken(),
        )
        clearLocalSession()
        return response
    }

    private suspend fun clearLocalSession() {
        secureTokenStore.clearAll()
        settingsStore.clearLegacyAccessToken()
        settingsStore.setAuthMode(StoredAuthMode.Onboarding)
        SentryHelper.clearUser()
        _state.value = AuthState.Onboarding
    }

    override suspend fun refresh(): Boolean {
        return refreshMutex.withLock {
            val refreshToken = secureTokenStore.readRefreshToken() ?: return@withLock false
            return@withLock try {
                val response = transport.request<AuthTokenPair>(
                    method = io.ktor.http.HttpMethod.Post,
                    path = "/api/auth/refresh",
                    body = RefreshRequest(refreshToken = refreshToken),
                )
                secureTokenStore.writeAccessToken(response.accessToken)
                secureTokenStore.writeRefreshToken(response.refreshToken)
                true
            } catch (_: Throwable) {
                secureTokenStore.clearAll()
                settingsStore.clearLegacyAccessToken()
                settingsStore.setAuthMode(StoredAuthMode.Onboarding)
                SentryHelper.clearUser()
                _state.value = AuthState.SessionExpired("Session expired, please sign in.")
                false
            }
        }
    }

    private suspend fun persistTokensAndUser(tokens: AuthTokenPair): UserSummary {
        secureTokenStore.writeAccessToken(tokens.accessToken)
        secureTokenStore.writeRefreshToken(tokens.refreshToken)
        settingsStore.clearLegacyAccessToken()
        settingsStore.markOnboardingSeen()

        val user = fetchMe(tokens.accessToken)
        settingsStore.setAuthMode(StoredAuthMode.Authenticated, userId = user.id)
        SentryHelper.setUser(user.id)
        _state.value = AuthState.Authenticated(user)
        return user
    }

    private suspend fun fetchMe(accessToken: String): UserSummary {
        return transport.request(
            method = io.ktor.http.HttpMethod.Get,
            path = "/api/auth/me",
            bearerToken = accessToken,
        )
    }
}
