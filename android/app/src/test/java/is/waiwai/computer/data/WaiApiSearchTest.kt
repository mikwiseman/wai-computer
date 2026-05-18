package `is`.waiwai.computer.data

import `is`.waiwai.computer.monitoring.SentryHelper
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
import io.mockk.every
import io.mockk.just
import io.mockk.mockk
import io.mockk.mockkObject
import io.mockk.unmockkAll
import kotlinx.coroutines.test.runTest
import kotlinx.serialization.json.Json
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class WaiApiSearchTest {
    @Before
    fun setUp() {
        mockkObject(SentryHelper)
        every { SentryHelper.addBreadcrumb(any(), any(), any(), any()) } just Runs
        every { SentryHelper.captureError(any(), any()) } just Runs
    }

    @After
    fun tearDown() {
        unmockkAll()
    }

    @Test
    fun `hybrid search sends q limit offset and decodes results`() = runTest {
        val urls = mutableListOf<String>()
        val engine = MockEngine { request ->
            urls += request.url.toString()
            respond(
                content = """
                    {
                      "results": [
                        {
                          "recording_id": "rec-1",
                          "recording_title": "Stand-up",
                          "recording_type": "meeting",
                          "segment_id": "seg-1",
                          "speaker": "Mik",
                          "content": "Shipping the Android v1.0",
                          "start_ms": 100,
                          "end_ms": 4500,
                          "score": 0.873
                        }
                      ],
                      "total": 1
                    }
                """.trimIndent(),
                status = HttpStatusCode.OK,
                headers = headersOf(HttpHeaders.ContentType, "application/json"),
            )
        }
        val api = apiUnder(engine)

        val response = api.search(query = "android", mode = SearchMode.Hybrid, limit = 10, offset = 0)

        assertEquals(1, response.total)
        val first = response.results.single()
        assertEquals("rec-1", first.recordingId)
        assertEquals("Stand-up", first.recordingTitle)
        assertEquals("meeting", first.recordingType)
        assertEquals("Mik", first.speaker)
        assertEquals("Shipping the Android v1.0", first.content)
        assertEquals(0.873, first.score, 0.0001)

        val url = urls.single()
        assertTrue("expected /api/search path: $url", url.contains("/api/search?"))
        assertTrue(url.contains("q=android"))
        assertTrue(url.contains("limit=10"))
        assertTrue(url.contains("offset=0"))
    }

    @Test
    fun `semantic mode routes to slash semantic`() = runTest {
        val urls = mutableListOf<String>()
        val engine = MockEngine { request ->
            urls += request.url.toString()
            respond(
                content = """{"results":[],"total":0}""",
                status = HttpStatusCode.OK,
                headers = headersOf(HttpHeaders.ContentType, "application/json"),
            )
        }
        val api = apiUnder(engine)

        api.search(query = "memory", mode = SearchMode.Semantic)

        assertTrue(urls.single().contains("/api/search/semantic?"))
    }

    @Test
    fun `fulltext mode routes to slash fts`() = runTest {
        val urls = mutableListOf<String>()
        val engine = MockEngine { request ->
            urls += request.url.toString()
            respond(
                content = """{"results":[],"total":0}""",
                status = HttpStatusCode.OK,
                headers = headersOf(HttpHeaders.ContentType, "application/json"),
            )
        }
        val api = apiUnder(engine)

        api.search(query = "ship", mode = SearchMode.Fulltext)

        assertTrue(urls.single().contains("/api/search/fts?"))
    }

    @Test
    fun `search retries once after 401 then succeeds`() = runTest {
        val seenAuth = mutableListOf<String?>()
        val engine = MockEngine { request ->
            seenAuth += request.headers[HttpHeaders.Authorization]
            if (seenAuth.size == 1) {
                respond("", HttpStatusCode.Unauthorized)
            } else {
                respond(
                    content = """{"results":[],"total":0}""",
                    status = HttpStatusCode.OK,
                    headers = headersOf(HttpHeaders.ContentType, "application/json"),
                )
            }
        }
        val settingsStore = mockk<SettingsStore>()
        val authStore = mockk<AuthStoreContract>()
        coEvery { settingsStore.snapshot() } returns appSettings()
        coEvery { authStore.currentAccessToken() } returnsMany listOf("expired", "fresh")
        coEvery { authStore.refresh() } returns true

        val transport = ApiTransport(settingsStore, testClient(engine))
        val api = WaiApi(transport = transport, authStore = authStore)

        api.search(query = "anything")

        assertEquals(listOf("Bearer expired", "Bearer fresh"), seenAuth)
        transport.close()
    }

    @Test
    fun `star recording posts to slash star and decodes`() = runTest {
        val methodSeen = mutableListOf<String>()
        val engine = MockEngine { request ->
            methodSeen += request.method.value
            respond(
                content = """{
                    "id":"rec-1",
                    "type":"note",
                    "status":"ready",
                    "starred_at":"2026-05-18T11:00:00Z",
                    "created_at":"2026-05-18T10:00:00Z"
                }""".trimIndent(),
                status = HttpStatusCode.OK,
                headers = headersOf(HttpHeaders.ContentType, "application/json"),
            )
        }
        val api = apiUnder(engine)

        val recording = api.starRecording("rec-1")

        assertEquals("rec-1", recording.id)
        assertEquals("2026-05-18T11:00:00Z", recording.starredAt)
        assertEquals(listOf("POST"), methodSeen)
    }

    @Test
    fun `unstar recording deletes the star resource`() = runTest {
        val methodSeen = mutableListOf<String>()
        val engine = MockEngine { request ->
            methodSeen += request.method.value
            respond(
                content = """{
                    "id":"rec-1",
                    "type":"note",
                    "status":"ready",
                    "starred_at":null,
                    "created_at":"2026-05-18T10:00:00Z"
                }""".trimIndent(),
                status = HttpStatusCode.OK,
                headers = headersOf(HttpHeaders.ContentType, "application/json"),
            )
        }
        val api = apiUnder(engine)

        val recording = api.unstarRecording("rec-1")

        assertEquals(null, recording.starredAt)
        assertEquals(listOf("DELETE"), methodSeen)
    }

    @Test
    fun `restore recording posts to restore`() = runTest {
        val paths = mutableListOf<String>()
        val methods = mutableListOf<String>()
        val engine = MockEngine { request ->
            paths += request.url.encodedPath
            methods += request.method.value
            respond(
                content = """{
                    "id":"rec-1",
                    "type":"note",
                    "status":"ready",
                    "deleted_at":null,
                    "created_at":"2026-05-18T10:00:00Z"
                }""".trimIndent(),
                status = HttpStatusCode.OK,
                headers = headersOf(HttpHeaders.ContentType, "application/json"),
            )
        }
        val api = apiUnder(engine)

        val recording = api.restoreRecording("rec-1")

        assertEquals(null, recording.deletedAt)
        assertEquals(listOf("/api/recordings/rec-1/restore"), paths)
        assertEquals(listOf("POST"), methods)
    }

    @Test
    fun `generate summary posts to generate-summary and decodes Summary`() = runTest {
        val paths = mutableListOf<String>()
        val engine = MockEngine { request ->
            paths += request.url.encodedPath
            respond(
                content = """{
                    "summary":"This is the summary.",
                    "key_points":["one","two"],
                    "topics":["android"],
                    "sentiment":"positive"
                }""".trimIndent(),
                status = HttpStatusCode.OK,
                headers = headersOf(HttpHeaders.ContentType, "application/json"),
            )
        }
        val api = apiUnder(engine)

        val summary = api.generateSummary("rec-1")

        assertEquals("This is the summary.", summary.summary)
        assertEquals(listOf("one", "two"), summary.keyPoints)
        assertEquals(listOf("android"), summary.topics)
        assertEquals(listOf("/api/recordings/rec-1/generate-summary"), paths)
    }

    @Test
    fun `create folder posts name and decodes Folder`() = runTest {
        var requestBody = ""
        val engine = MockEngine { request ->
            requestBody = (request.body as io.ktor.http.content.TextContent).text
            respond(
                content = """{"id":"f-1","name":"Work","created_at":"2026-05-18T10:00:00Z"}""",
                status = HttpStatusCode.OK,
                headers = headersOf(HttpHeaders.ContentType, "application/json"),
            )
        }
        val api = apiUnder(engine)

        val folder = api.createFolder("Work")

        assertEquals("f-1", folder.id)
        assertEquals("Work", folder.name)
        assertTrue(requestBody.contains("\"name\":\"Work\""))
    }

    @Test
    fun `rename folder patches name`() = runTest {
        var requestBody = ""
        val methods = mutableListOf<String>()
        val engine = MockEngine { request ->
            methods += request.method.value
            requestBody = (request.body as io.ktor.http.content.TextContent).text
            respond(
                content = """{"id":"f-1","name":"Renamed"}""",
                status = HttpStatusCode.OK,
                headers = headersOf(HttpHeaders.ContentType, "application/json"),
            )
        }
        val api = apiUnder(engine)

        val folder = api.renameFolder("f-1", "Renamed")

        assertEquals("Renamed", folder.name)
        assertEquals(listOf("PATCH"), methods)
        assertTrue(requestBody.contains("\"name\":\"Renamed\""))
    }

    @Test
    fun `delete folder issues DELETE and returns Unit`() = runTest {
        val methods = mutableListOf<String>()
        val engine = MockEngine { request ->
            methods += request.method.value
            respond("", HttpStatusCode.NoContent)
        }
        val api = apiUnder(engine)

        api.deleteFolder("f-1")

        assertEquals(listOf("DELETE"), methods)
    }

    @Test
    fun `update person patches selected fields only`() = runTest {
        var requestBody = ""
        val engine = MockEngine { request ->
            requestBody = (request.body as io.ktor.http.content.TextContent).text
            respond(
                content = """{
                    "id":"p-1",
                    "display_name":"Mik W",
                    "color":"#FF0",
                    "voiceprint_count":2,
                    "created_at":"2026-05-18T10:00:00Z",
                    "updated_at":"2026-05-18T10:00:00Z"
                }""".trimIndent(),
                status = HttpStatusCode.OK,
                headers = headersOf(HttpHeaders.ContentType, "application/json"),
            )
        }
        val api = apiUnder(engine)

        val person = api.updatePerson("p-1", displayName = "Mik W", color = "#FF0")

        assertEquals("Mik W", person.displayName)
        assertEquals("#FF0", person.color)
        assertTrue(requestBody.contains("\"display_name\":\"Mik W\""))
        assertTrue(requestBody.contains("\"color\":\"#FF0\""))
        // aliases omitted because explicitNulls=false in the client
        assertTrue(!requestBody.contains("aliases"))
    }

    @Test
    fun `delete person issues DELETE`() = runTest {
        val methods = mutableListOf<String>()
        val engine = MockEngine { request ->
            methods += request.method.value
            respond("", HttpStatusCode.NoContent)
        }
        val api = apiUnder(engine)

        api.deletePerson("p-1")

        assertEquals(listOf("DELETE"), methods)
    }

    private fun apiUnder(engine: MockEngine): WaiApi {
        val settingsStore = mockk<SettingsStore>()
        val authStore = mockk<AuthStoreContract>()
        coEvery { settingsStore.snapshot() } returns appSettings()
        coEvery { authStore.currentAccessToken() } returns "access-token"
        coEvery { authStore.refresh() } returns false
        val transport = ApiTransport(settingsStore, testClient(engine))
        return WaiApi(transport = transport, authStore = authStore)
    }

    private fun testClient(engine: MockEngine): HttpClient = HttpClient(engine) {
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

    private fun appSettings(): AppSettings = AppSettings(
        baseUrl = "https://wai.computer",
        transcriptionLanguage = SettingsStore.DEFAULT_TRANSCRIPTION_LANGUAGE,
        authMode = StoredAuthMode.Authenticated,
        authUserId = "user-1",
        onboardingSeen = true,
        guestSinceEpochMillis = null,
        legacyAccessToken = null,
    )
}
