package `is`.waiwai.say.data

import `is`.waiwai.say.monitoring.SentryHelper
import io.ktor.client.HttpClient
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.respond
import io.ktor.client.plugins.contentnegotiation.ContentNegotiation
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpStatusCode
import io.ktor.http.content.TextContent
import io.ktor.http.headersOf
import io.ktor.http.content.OutgoingContent
import io.ktor.serialization.kotlinx.json.json
import io.mockk.Runs
import io.mockk.coEvery
import io.mockk.every
import io.mockk.just
import io.mockk.mockk
import io.mockk.mockkObject
import io.mockk.unmockkAll
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class WaiApiTest {
    private val requestJson = Json {
        ignoreUnknownKeys = true
        explicitNulls = false
    }

    @Test
    fun `me retries once after 401 and refreshes token`() = runTest {
        val settingsStore = mockk<SettingsStore>()
        val authStore = mockk<AuthStoreContract>()
        val requestHeaders = mutableListOf<String?>()
        val engine = MockEngine { request ->
            requestHeaders += request.headers[HttpHeaders.Authorization]
            when (requestHeaders.size) {
                1 -> respond("", HttpStatusCode.Unauthorized)
                else -> respond(
                    content = """{"id":"user-1","email":"mik@example.com","created_at":"2026-04-17T11:00:00Z"}""",
                    status = HttpStatusCode.OK,
                    headers = headersOf(HttpHeaders.ContentType, "application/json"),
                )
            }
        }
        val client = testClient(engine)

        mockkObject(SentryHelper)
        every { SentryHelper.addBreadcrumb(any(), any(), any(), any()) } just Runs
        every { SentryHelper.captureError(any(), any()) } just Runs
        coEvery { settingsStore.snapshot() } returns appSettings()
        coEvery { authStore.currentAccessToken() } returnsMany listOf("expired-token", "fresh-token")
        coEvery { authStore.refresh() } returns true

        val transport = ApiTransport(settingsStore, client)
        val api = WaiApi(transport = transport, authStore = authStore)

        val user = api.me()

        assertEquals("user-1", user.id)
        assertEquals(listOf("Bearer expired-token", "Bearer fresh-token"), requestHeaders)
        transport.close()
        unmockkAll()
    }

    @Test
    fun `create recording forwards folder id and language`() = runTest {
        val settingsStore = mockk<SettingsStore>()
        val authStore = mockk<AuthStoreContract>()
        var requestBody = ""
        val engine = MockEngine { request ->
            requestBody = bodyText(request.body)
            respond(
                content = """{"id":"rec-1","title":"Inbox","type":"note","status":"pending_upload","created_at":"2026-04-17T11:00:00Z"}""",
                status = HttpStatusCode.OK,
                headers = headersOf(HttpHeaders.ContentType, "application/json"),
            )
        }
        val client = testClient(engine)

        mockkObject(SentryHelper)
        every { SentryHelper.addBreadcrumb(any(), any(), any(), any()) } just Runs
        every { SentryHelper.captureError(any(), any()) } just Runs
        coEvery { settingsStore.snapshot() } returns appSettings()
        coEvery { authStore.currentAccessToken() } returns "access-token"
        coEvery { authStore.refresh() } returns false

        val transport = ApiTransport(settingsStore, client)
        val api = WaiApi(transport = transport, authStore = authStore)
        api.createRecording(
            title = "Inbox",
            type = RecordingType.note,
            language = "ru",
            folderId = "folder-1",
        )

        val request = requestJson.decodeFromString<CreateRecordingRequest>(requestBody)

        assertEquals("Inbox", request.title)
        assertEquals("ru", request.language)
        assertEquals("folder-1", request.folderId)
        assertTrue(request.type == RecordingType.note)
        transport.close()
        unmockkAll()
    }

    private fun testClient(engine: MockEngine): HttpClient {
        return HttpClient(engine) {
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
    }

    private fun bodyText(body: Any): String = when (body) {
        is TextContent -> body.text
        is OutgoingContent.ByteArrayContent -> body.bytes().decodeToString()
        is OutgoingContent.NoContent -> ""
        else -> error("Unsupported request body: ${body::class.java.name}")
    }

    private fun appSettings(): AppSettings = AppSettings(
        baseUrl = "https://say.waiwai.is",
        transcriptionLanguage = SettingsStore.DEFAULT_TRANSCRIPTION_LANGUAGE,
        authMode = StoredAuthMode.Authenticated,
        authUserId = "user-1",
        onboardingSeen = true,
        guestSinceEpochMillis = null,
        legacyAccessToken = null,
    )
}
