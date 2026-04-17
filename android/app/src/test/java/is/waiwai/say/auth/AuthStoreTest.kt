package `is`.waiwai.say.auth

import `is`.waiwai.say.data.ApiTransport
import `is`.waiwai.say.data.AppSettings
import `is`.waiwai.say.data.SecureTokenStore
import `is`.waiwai.say.data.SettingsStore
import `is`.waiwai.say.data.StoredAuthMode
import `is`.waiwai.say.monitoring.SentryHelper
import io.ktor.client.HttpClient
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.respond
import io.ktor.client.plugins.contentnegotiation.ContentNegotiation
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpStatusCode
import io.ktor.http.headersOf
import io.ktor.serialization.kotlinx.json.json
import io.mockk.Runs
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.every
import io.mockk.just
import io.mockk.mockk
import io.mockk.mockkObject
import io.mockk.unmockkAll
import java.time.Instant
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AuthStoreTest {
    @Test
    fun `bootstrap enters onboarding when there are no tokens`() = runTest {
        val settingsStore = mockk<SettingsStore>()
        val secureTokenStore = mockk<SecureTokenStore>()
        val transport = mockk<ApiTransport>()

        coEvery { settingsStore.snapshot() } returns appSettings(mode = StoredAuthMode.Onboarding)
        every { secureTokenStore.readAccessToken() } returns null
        every { secureTokenStore.readRefreshToken() } returns null

        val store = AuthStore(settingsStore, secureTokenStore, transport)
        store.bootstrap()

        assertEquals(AuthState.Onboarding, store.state.value)
    }

    @Test
    fun `login persists tokens and emits authenticated`() = runTest {
        val settingsStore = mockk<SettingsStore>()
        val secureTokenStore = mockk<SecureTokenStore>()
        val transport = transportWithResponses(
            """{"access_token":"access-1","refresh_token":"refresh-1","token_type":"bearer"}""",
            """{"id":"user-1","email":"mik@example.com","created_at":"2026-04-17T11:00:00Z"}""",
        )

        mockkObject(SentryHelper)
        every { SentryHelper.setUser(any()) } just Runs
        every { SentryHelper.addBreadcrumb(any(), any(), any(), any()) } just Runs
        every { SentryHelper.captureError(any(), any()) } just Runs
        every { secureTokenStore.writeAccessToken("access-1") } just Runs
        every { secureTokenStore.writeRefreshToken("refresh-1") } just Runs
        coEvery { settingsStore.snapshot() } returns appSettings(mode = StoredAuthMode.Onboarding)
        coEvery { settingsStore.clearLegacyAccessToken() } just Runs
        coEvery { settingsStore.markOnboardingSeen() } just Runs
        coEvery { settingsStore.setAuthMode(StoredAuthMode.Authenticated, "user-1", null) } just Runs

        val store = AuthStore(settingsStore, secureTokenStore, transport)
        val loggedInUser = store.login("mik@example.com", "password123")

        assertEquals("user-1", loggedInUser.id)
        assertEquals(AuthState.Authenticated(loggedInUser), store.state.value)
        coVerify { settingsStore.setAuthMode(StoredAuthMode.Authenticated, "user-1", null) }
        transport.close()
        unmockkAll()
    }

    @Test
    fun `refresh failure clears local auth and emits session expired`() = runTest {
        val settingsStore = mockk<SettingsStore>()
        val secureTokenStore = mockk<SecureTokenStore>()
        val transport = transportWithStatus(HttpStatusCode.Unauthorized)

        mockkObject(SentryHelper)
        every { SentryHelper.clearUser() } just Runs
        every { SentryHelper.addBreadcrumb(any(), any(), any(), any()) } just Runs
        every { SentryHelper.captureError(any(), any()) } just Runs
        every { secureTokenStore.readRefreshToken() } returns "refresh-1"
        every { secureTokenStore.clearAll() } just Runs
        coEvery { settingsStore.snapshot() } returns appSettings(mode = StoredAuthMode.Authenticated)
        coEvery { settingsStore.clearLegacyAccessToken() } just Runs
        coEvery { settingsStore.setAuthMode(StoredAuthMode.Onboarding, null, null) } just Runs

        val store = AuthStore(settingsStore, secureTokenStore, transport)
        val refreshed = store.refresh()

        assertFalse(refreshed)
        val state = store.state.value
        assertTrue(state is AuthState.SessionExpired)
        assertEquals(
            "Session expired, please sign in.",
            (state as AuthState.SessionExpired).reason,
        )
        transport.close()
        unmockkAll()
    }

    private fun transportWithResponses(vararg jsonBodies: String): ApiTransport {
        var index = 0
        val engine = MockEngine {
            respond(
                content = jsonBodies[index++],
                status = HttpStatusCode.OK,
                headers = headersOf(HttpHeaders.ContentType, "application/json"),
            )
        }
        val client = HttpClient(engine) {
            install(ContentNegotiation) {
                json(
                    Json {
                        ignoreUnknownKeys = true
                        explicitNulls = false
                        isLenient = true
                    },
                )
            }
        }
        return ApiTransport(mockk(relaxed = true), client)
    }

    private fun transportWithStatus(status: HttpStatusCode): ApiTransport {
        val engine = MockEngine {
            respond(
                content = "",
                status = status,
                headers = headersOf(HttpHeaders.ContentType, "application/json"),
            )
        }
        val client = HttpClient(engine) {
            install(ContentNegotiation) {
                json(
                    Json {
                        ignoreUnknownKeys = true
                        explicitNulls = false
                        isLenient = true
                    },
                )
            }
        }
        return ApiTransport(mockk(relaxed = true), client)
    }

    private fun appSettings(mode: StoredAuthMode): AppSettings = AppSettings(
        baseUrl = "https://say.waiwai.is",
        transcriptionLanguage = SettingsStore.DEFAULT_TRANSCRIPTION_LANGUAGE,
        authMode = mode,
        authUserId = null,
        onboardingSeen = mode != StoredAuthMode.Onboarding,
        guestSinceEpochMillis = null,
        legacyAccessToken = null,
    )
}
