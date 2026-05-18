package `is`.waiwai.computer

import android.app.Application
import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import androidx.test.core.app.ApplicationProvider
import `is`.waiwai.computer.auth.AuthStore
import `is`.waiwai.computer.data.ApiTransport
import `is`.waiwai.computer.data.AppContainer
import `is`.waiwai.computer.data.AuthTokenPair
import `is`.waiwai.computer.data.CreateRecordingRequest
import `is`.waiwai.computer.data.CreateFolderRequest
import `is`.waiwai.computer.data.Folder
import `is`.waiwai.computer.data.LiveTranscriptSegment
import `is`.waiwai.computer.data.MessageResponse
import `is`.waiwai.computer.data.Recording
import `is`.waiwai.computer.data.RecordingDetail
import `is`.waiwai.computer.data.RecordingStatus
import `is`.waiwai.computer.data.RecordingType
import `is`.waiwai.computer.data.SaveTranscriptRequest
import `is`.waiwai.computer.data.SearchResponse
import `is`.waiwai.computer.data.SearchResult
import `is`.waiwai.computer.data.SecureTokenStore
import `is`.waiwai.computer.data.SettingsStore
import `is`.waiwai.computer.data.Summary
import `is`.waiwai.computer.data.UpdateFolderRequest
import `is`.waiwai.computer.data.UpdatePersonRequest
import `is`.waiwai.computer.data.UpdateRecordingRequest
import `is`.waiwai.computer.data.Person
import `is`.waiwai.computer.data.UserSummary
import `is`.waiwai.computer.data.WaiApi
import `is`.waiwai.computer.recording.AudioRecorder
import `is`.waiwai.computer.recording.RealtimeWebSocketManager
import `is`.waiwai.computer.recording.WsEvent
import io.ktor.client.HttpClient
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.MockRequestHandleScope
import io.ktor.client.engine.mock.respond
import io.ktor.client.plugins.contentnegotiation.ContentNegotiation
import io.ktor.http.ContentType
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpMethod
import io.ktor.http.HttpStatusCode
import io.ktor.http.content.ByteArrayContent
import io.ktor.http.content.OutgoingContent
import io.ktor.http.content.TextContent
import io.ktor.http.headersOf
import io.ktor.serialization.kotlinx.json.json
import java.io.File
import java.time.Instant
import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json

data class TestBackendState(
    val user: UserSummary = UserSummary(
        id = "user-1",
        email = "mik@example.com",
        createdAt = "2026-04-17T10:00:00Z",
    ),
    val folders: MutableList<Folder> = mutableListOf(),
    val recordings: MutableList<Recording> = mutableListOf(),
    val people: MutableList<Person> = mutableListOf(),
    val searchResults: MutableList<SearchResult> = mutableListOf(),
    var nextRecordingIndex: Int = 1,
    var nextFolderIndex: Int = 1,
    var nextPersonIndex: Int = 1,
)

data class TestAppFixture(
    val application: Application,
    val container: AppContainer,
    val authStore: AuthStore,
    val settingsStore: SettingsStore,
    val secureTokenStore: SecureTokenStore,
    val transport: ApiTransport,
    val backend: TestBackendState,
) {
    fun cleanup() {
        runBlocking {
            container.localRecordingStore.clearAll()
            secureTokenStore.clearAll()
            transport.close()
        }
    }
}

fun createTestAppFixture(
    initialRecordings: List<Recording> = emptyList(),
    initialFolders: List<Folder> = emptyList(),
    initialPeople: List<Person> = emptyList(),
    initialSearchResults: List<SearchResult> = emptyList(),
): TestAppFixture {
    val application = ApplicationProvider.getApplicationContext<Application>()
    val dataStoreFile = File(
        application.filesDir,
        "android-test-settings-${UUID.randomUUID()}.preferences_pb",
    )
    val dataStore = PreferenceDataStoreFactory.create(produceFile = { dataStoreFile })
    val settingsStore = SettingsStore(dataStore)
    val secureTokenStore = SecureTokenStore(application)
    val backend = TestBackendState(
        folders = initialFolders.toMutableList(),
        recordings = initialRecordings.toMutableList(),
        people = initialPeople.toMutableList(),
        searchResults = initialSearchResults.toMutableList(),
        nextRecordingIndex = initialRecordings.size + 1,
        nextFolderIndex = initialFolders.size + 1,
        nextPersonIndex = initialPeople.size + 1,
    )
    val client = testHttpClient(backend)
    val transport = ApiTransport(settingsStore, client)
    val authStore = AuthStore(settingsStore, secureTokenStore, transport)
    val waiApi = WaiApi(transport, authStore)
    val localRecordingStore = `is`.waiwai.computer.sync.LocalRecordingStore(application)
    runBlocking { localRecordingStore.clearAll() }
    val container = AppContainer(
        application = application,
        settingsStoreOverride = settingsStore,
        secureTokenStoreOverride = secureTokenStore,
        transportOverride = transport,
        authStoreOverride = authStore,
        waiApiOverride = waiApi,
        localRecordingStoreOverride = localRecordingStore,
        sentryDsnOverride = "",
    )
    return TestAppFixture(
        application = application,
        container = container,
        authStore = authStore,
        settingsStore = settingsStore,
        secureTokenStore = secureTokenStore,
        transport = transport,
        backend = backend,
    )
}

class TestAudioRecorder(
    private val frame: ShortArray = shortArrayOf(1, 2, 3, 4, 5, 6, 7, 8),
    private val frameDelayMs: Long = 50L,
) : AudioRecorder {
    private val recording = AtomicBoolean(false)

    override val isRecording: Boolean
        get() = recording.get()

    override fun start(): Flow<ShortArray> = flow {
        recording.set(true)
        while (recording.get()) {
            emit(frame)
            delay(frameDelayMs)
        }
    }

    override suspend fun stop() {
        recording.set(false)
    }
}

class TestWebSocketManager(
    segments: List<LiveTranscriptSegment> = listOf(
        LiveTranscriptSegment(
            text = "Transcript ready",
            isFinal = true,
            startMs = 0,
            endMs = 1000,
            confidence = 0.99,
        ),
    ),
) : RealtimeWebSocketManager {
    private val emittedSegments = segments.toList()
    private val mutableEvents = MutableSharedFlow<WsEvent>(replay = 1, extraBufferCapacity = 16)

    override val events: SharedFlow<WsEvent> = mutableEvents
    override val collectedSegments: List<LiveTranscriptSegment> = emittedSegments

    override suspend fun connect() {
        mutableEvents.emit(WsEvent.Connected)
        emittedSegments.forEach { mutableEvents.emit(WsEvent.Transcript(it)) }
    }

    override suspend fun sendAudio(data: ByteArray) = Unit

    override suspend fun finishStreaming(timeoutMillis: Long): Boolean = true

    override suspend fun disconnect() = Unit
}

private fun testHttpClient(backend: TestBackendState): HttpClient {
    val json = Json {
        ignoreUnknownKeys = true
        explicitNulls = false
        isLenient = true
    }
    val engine = MockEngine { request ->
        val path = request.url.encodedPath
        val isAuthorized = request.headers[HttpHeaders.Authorization] == "Bearer access-token"
        when {
            path == "/api/auth/login" && request.method == HttpMethod.Post ->
                jsonResponse(json, AuthTokenPair(accessToken = "access-token", refreshToken = "refresh-token"))
            path == "/api/auth/register" && request.method == HttpMethod.Post ->
                jsonResponse(json, AuthTokenPair(accessToken = "access-token", refreshToken = "refresh-token"))
            path == "/api/auth/verify-magic" && request.method == HttpMethod.Post ->
                jsonResponse(json, AuthTokenPair(accessToken = "access-token", refreshToken = "refresh-token"))
            path == "/api/auth/magic-link" && request.method == HttpMethod.Post ->
                jsonResponse(json, MessageResponse("sent"))
            path == "/api/auth/refresh" && request.method == HttpMethod.Post ->
                jsonResponse(json, AuthTokenPair(accessToken = "access-token", refreshToken = "refresh-token"))
            path == "/api/auth/logout" && request.method == HttpMethod.Post ->
                jsonResponse(json, MessageResponse("ok"))
            path == "/api/auth/me" && request.method == HttpMethod.Get && isAuthorized ->
                jsonResponse(json, backend.user)
            path == "/api/folders" && request.method == HttpMethod.Get && isAuthorized ->
                jsonResponse(json, backend.folders)
            path == "/api/recordings" && request.method == HttpMethod.Get && isAuthorized ->
                jsonResponse(json, backend.recordings.toList())
            path == "/api/recordings" && request.method == HttpMethod.Post && isAuthorized -> {
                val body = requestBodyText(request.body)
                val payload = json.decodeFromString<CreateRecordingRequest>(body)
                val created = Recording(
                    id = "rec-${backend.nextRecordingIndex++}",
                    title = payload.title,
                    type = payload.type,
                    status = RecordingStatus.PendingUpload,
                    language = payload.language,
                    folderId = payload.folderId,
                    createdAt = Instant.now().toString(),
                )
                backend.recordings.add(0, created)
                jsonResponse(json, created)
            }
            path.matches(Regex("/api/recordings/[^/]+")) && request.method == HttpMethod.Delete && isAuthorized -> {
                val recordingId = path.substringAfterLast("/")
                backend.recordings.removeAll { it.id == recordingId }
                respond("", HttpStatusCode.OK)
            }
            path.matches(Regex("/api/recordings/[^/]+")) && request.method == HttpMethod.Get && isAuthorized -> {
                val recordingId = path.substringAfterLast("/")
                jsonResponse(json, backend.recordingDetail(recordingId))
            }
            path.matches(Regex("/api/recordings/[^/]+")) && request.method == HttpMethod.Patch && isAuthorized -> {
                val recordingId = path.substringAfterLast("/")
                val payload = json.decodeFromString<UpdateRecordingRequest>(requestBodyText(request.body))
                val updated = backend.recordings.first { it.id == recordingId }.copy(
                    title = payload.title ?: backend.recordings.first { it.id == recordingId }.title,
                    folderId = payload.folderId ?: backend.recordings.first { it.id == recordingId }.folderId,
                )
                backend.replaceRecording(updated)
                jsonResponse(json, updated)
            }
            path.matches(Regex("/api/recordings/[^/]+/transcript")) && request.method == HttpMethod.Post && isAuthorized -> {
                val recordingId = path.split("/")[3]
                val payload = json.decodeFromString<SaveTranscriptRequest>(requestBodyText(request.body))
                val ready = backend.recordings.first { it.id == recordingId }.copy(
                    status = RecordingStatus.Ready,
                    durationSeconds = payload.durationSeconds,
                )
                backend.replaceRecording(ready)
                jsonResponse(json, backend.recordingDetail(recordingId))
            }
            path.matches(Regex("/api/recordings/[^/]+/upload")) && request.method == HttpMethod.Post && isAuthorized -> {
                val recordingId = path.split("/")[3]
                val ready = backend.recordings.first { it.id == recordingId }.copy(status = RecordingStatus.Ready)
                backend.replaceRecording(ready)
                jsonResponse(json, backend.recordingDetail(recordingId))
            }
            path == "/api/search" && request.method == HttpMethod.Get && isAuthorized -> {
                val q = request.url.parameters["q"].orEmpty()
                val matching = backend.searchResults.filter {
                    q.isEmpty() ||
                        it.content.contains(q, ignoreCase = true) ||
                        it.recordingTitle?.contains(q, ignoreCase = true) == true
                }
                jsonResponse(json, SearchResponse(results = matching, total = matching.size))
            }
            (path == "/api/search/semantic" || path == "/api/search/fts") &&
                request.method == HttpMethod.Get && isAuthorized -> {
                jsonResponse(
                    json,
                    SearchResponse(results = backend.searchResults, total = backend.searchResults.size),
                )
            }
            path.matches(Regex("/api/recordings/[^/]+/star")) && request.method == HttpMethod.Post && isAuthorized -> {
                val recordingId = path.split("/")[3]
                val updated = backend.recordings.first { it.id == recordingId }
                    .copy(starredAt = Instant.now().toString())
                backend.replaceRecording(updated)
                jsonResponse(json, updated)
            }
            path.matches(Regex("/api/recordings/[^/]+/star")) && request.method == HttpMethod.Delete && isAuthorized -> {
                val recordingId = path.split("/")[3]
                val updated = backend.recordings.first { it.id == recordingId }.copy(starredAt = null)
                backend.replaceRecording(updated)
                jsonResponse(json, updated)
            }
            path.matches(Regex("/api/recordings/[^/]+/restore")) && request.method == HttpMethod.Post && isAuthorized -> {
                val recordingId = path.split("/")[3]
                val updated = backend.recordings.first { it.id == recordingId }.copy(deletedAt = null)
                backend.replaceRecording(updated)
                jsonResponse(json, updated)
            }
            path.matches(Regex("/api/recordings/[^/]+/generate-summary")) &&
                request.method == HttpMethod.Post && isAuthorized -> {
                jsonResponse(
                    json,
                    Summary(
                        summary = "Generated summary",
                        keyPoints = listOf("first", "second"),
                        topics = listOf("android"),
                        sentiment = "positive",
                    ),
                )
            }
            path == "/api/folders" && request.method == HttpMethod.Post && isAuthorized -> {
                val payload = json.decodeFromString<CreateFolderRequest>(requestBodyText(request.body))
                val folder = Folder(
                    id = "folder-${backend.nextFolderIndex++}",
                    name = payload.name,
                    createdAt = Instant.now().toString(),
                )
                backend.folders.add(folder)
                jsonResponse(json, folder)
            }
            path.matches(Regex("/api/folders/[^/]+")) && request.method == HttpMethod.Patch && isAuthorized -> {
                val folderId = path.substringAfterLast("/")
                val payload = json.decodeFromString<UpdateFolderRequest>(requestBodyText(request.body))
                val index = backend.folders.indexOfFirst { it.id == folderId }
                val updated = backend.folders[index].copy(name = payload.name)
                backend.folders[index] = updated
                jsonResponse(json, updated)
            }
            path.matches(Regex("/api/folders/[^/]+")) && request.method == HttpMethod.Delete && isAuthorized -> {
                val folderId = path.substringAfterLast("/")
                backend.folders.removeAll { it.id == folderId }
                respond("", HttpStatusCode.NoContent)
            }
            path == "/api/people" && request.method == HttpMethod.Get && isAuthorized ->
                jsonResponse(json, backend.people.toList())
            path.matches(Regex("/api/people/[^/]+")) && request.method == HttpMethod.Patch && isAuthorized -> {
                val personId = path.substringAfterLast("/")
                val payload = json.decodeFromString<UpdatePersonRequest>(requestBodyText(request.body))
                val index = backend.people.indexOfFirst { it.id == personId }
                val current = backend.people[index]
                val updated = current.copy(
                    displayName = payload.displayName ?: current.displayName,
                    color = payload.color ?: current.color,
                    aliases = payload.aliases ?: current.aliases,
                    updatedAt = Instant.now().toString(),
                )
                backend.people[index] = updated
                jsonResponse(json, updated)
            }
            path.matches(Regex("/api/people/[^/]+")) && request.method == HttpMethod.Delete && isAuthorized -> {
                val personId = path.substringAfterLast("/")
                backend.people.removeAll { it.id == personId }
                respond("", HttpStatusCode.NoContent)
            }
            !isAuthorized && path.startsWith("/api/") ->
                respond("", HttpStatusCode.Unauthorized)
            else ->
                error("Unhandled request in androidTest fixture: ${request.method.value} $path")
        }
    }
    return HttpClient(engine) {
        install(ContentNegotiation) {
            json(json)
        }
    }
}

private fun TestBackendState.replaceRecording(recording: Recording) {
    val index = recordings.indexOfFirst { it.id == recording.id }
    if (index >= 0) {
        recordings[index] = recording
    } else {
        recordings.add(0, recording)
    }
}

private fun TestBackendState.recordingDetail(recordingId: String): RecordingDetail {
    val recording = recordings.first { it.id == recordingId }
    return RecordingDetail(
        id = recording.id,
        title = recording.title,
        type = recording.type,
        status = recording.status,
        durationSeconds = recording.durationSeconds,
        createdAt = recording.createdAt,
        language = recording.language,
        folderId = recording.folderId,
    )
}

private fun requestBodyText(body: OutgoingContent): String = when (body) {
    is TextContent -> body.text
    is ByteArrayContent -> body.bytes().decodeToString()
    is OutgoingContent.NoContent -> ""
    else -> error("Unsupported request body: ${body::class.java.name}")
}

private suspend inline fun <reified T> MockRequestHandleScope.jsonResponse(
    json: Json,
    payload: T,
) = respond(
    content = json.encodeToString(payload),
    status = HttpStatusCode.OK,
    headers = headersOf(HttpHeaders.ContentType, ContentType.Application.Json.toString()),
)
