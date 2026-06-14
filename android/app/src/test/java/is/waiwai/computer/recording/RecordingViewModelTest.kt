package `is`.waiwai.computer.recording

import android.app.Application
import android.content.Context
import `is`.waiwai.computer.MainDispatcherRule
import `is`.waiwai.computer.auth.AuthState
import `is`.waiwai.computer.auth.AuthStore
import `is`.waiwai.computer.data.AppSettings
import `is`.waiwai.computer.data.LiveTranscriptSegment
import `is`.waiwai.computer.data.Recording
import `is`.waiwai.computer.data.RecordingDetail
import `is`.waiwai.computer.data.RecordingStatus
import `is`.waiwai.computer.data.RecordingType
import `is`.waiwai.computer.data.SettingsStore
import `is`.waiwai.computer.data.StoredAuthMode
import `is`.waiwai.computer.data.UserSummary
import `is`.waiwai.computer.data.WaiApi
import `is`.waiwai.computer.sync.LocalRecordingStore
import `is`.waiwai.computer.sync.PendingSyncWorkerScheduler
import io.mockk.Runs
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.every
import io.mockk.just
import io.mockk.mockk
import io.mockk.mockkObject
import io.mockk.unmockkAll
import java.io.File
import java.time.Instant
import kotlin.io.path.createTempDirectory
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class RecordingViewModelTest {
    @get:Rule
    val mainDispatcherRule = MainDispatcherRule()

    @Test
    @OptIn(ExperimentalCoroutinesApi::class)
    fun `guest recording is saved locally without server calls`() = runTest {
        val tempRoot = createTempDirectory("waicomputer-recording-guest").toFile()
        val authStore = mockk<AuthStore>()
        val settingsStore = mockk<SettingsStore>()
        val waiApi = mockk<WaiApi>(relaxed = true)
        val scheduler = mockk<PendingSyncWorkerScheduler>(relaxed = true)
        val application = mockApplication(tempRoot)
        val localStore = LocalRecordingStore(mockContext(tempRoot))
        val authState = MutableStateFlow<AuthState>(AuthState.Guest(Instant.now()))

        every { authStore.state } returns authState
        coEvery { settingsStore.snapshot() } returns appSettings()
        mockForegroundService()

        val viewModel = RecordingViewModel(
            application = application,
            authStore = authStore,
            settingsStore = settingsStore,
            waiApi = waiApi,
            localRecordingStore = localStore,
            syncScheduler = scheduler,
            audioRecorderFactory = { FakeAudioRecorder() },
        )

        viewModel.startRecording(permissionGranted = true)
        advanceUntilIdle()
        viewModel.stopRecording()
        advanceUntilIdle()

        val manifest = localStore.listPending().singleOrNull()
        assertNotNull(manifest)
        assertTrue(manifest!!.localOnly)
        assertTrue(manifest.requiresAuthentication)
        coVerify(exactly = 0) { waiApi.createRecording(any(), any(), any(), any()) }
        unmockkAll()
    }

    @Test
    @OptIn(ExperimentalCoroutinesApi::class)
    fun `authenticated recording falls back to offline banner when websocket connect fails`() = runTest {
        val tempRoot = createTempDirectory("waicomputer-recording-auth").toFile()
        val authStore = mockk<AuthStore>()
        val settingsStore = mockk<SettingsStore>()
        val waiApi = mockk<WaiApi>()
        val scheduler = mockk<PendingSyncWorkerScheduler>(relaxed = true)
        val application = mockApplication(tempRoot)
        val localStore = LocalRecordingStore(mockContext(tempRoot))
        val authState = MutableStateFlow<AuthState>(
            AuthState.Authenticated(
                UserSummary("user-1", "mik@example.com", Instant.now().toString()),
            ),
        )

        every { authStore.state } returns authState
        coEvery { settingsStore.snapshot() } returns appSettings()
        coEvery {
            waiApi.createRecording(
                title = any(),
                type = any(),
                language = any(),
                folderId = any(),
            )
        } returns Recording(
            id = "remote-1",
            type = RecordingType.note,
            status = RecordingStatus.PendingUpload,
            createdAt = Instant.now().toString(),
        )
        coEvery { waiApi.uploadAudio("remote-1", any()) } returns readyDetail("remote-1")
        mockForegroundService()

        val viewModel = RecordingViewModel(
            application = application,
            authStore = authStore,
            settingsStore = settingsStore,
            waiApi = waiApi,
            localRecordingStore = localStore,
            syncScheduler = scheduler,
            audioRecorderFactory = { FakeAudioRecorder() },
            webSocketFactory = { FakeWebSocket(connectError = IllegalStateException("offline")) },
        )

        viewModel.startRecording(permissionGranted = true)
        advanceUntilIdle()

        assertTrue(viewModel.uiState.value.liveTranscriptionOffline)
        assertEquals(Phase.Recording, viewModel.uiState.value.phase)

        viewModel.stopRecording()
        advanceUntilIdle()

        coVerify { waiApi.uploadAudio("remote-1", any()) }
        unmockkAll()
    }

    @Test
    @OptIn(ExperimentalCoroutinesApi::class)
    fun `authenticated recording uploads audio even when realtime transcript finalized`() = runTest {
        val tempRoot = createTempDirectory("waicomputer-recording-audio-canonical").toFile()
        val authStore = mockk<AuthStore>()
        val settingsStore = mockk<SettingsStore>()
        val waiApi = mockk<WaiApi>()
        val scheduler = mockk<PendingSyncWorkerScheduler>(relaxed = true)
        val application = mockApplication(tempRoot)
        val localStore = LocalRecordingStore(mockContext(tempRoot))
        val authState = MutableStateFlow<AuthState>(
            AuthState.Authenticated(
                UserSummary("user-1", "mik@example.com", Instant.now().toString()),
            ),
        )
        val liveSegments = listOf(
            LiveTranscriptSegment(
                text = "Realtime preview text",
                speaker = null,
                isFinal = true,
                startMs = 0,
                endMs = 1_000,
                confidence = 0.8,
            ),
        )

        every { authStore.state } returns authState
        coEvery { settingsStore.snapshot() } returns appSettings()
        coEvery {
            waiApi.createRecording(
                title = any(),
                type = any(),
                language = any(),
                folderId = any(),
            )
        } returns Recording(
            id = "remote-audio",
            type = RecordingType.note,
            status = RecordingStatus.PendingUpload,
            createdAt = Instant.now().toString(),
        )
        coEvery { waiApi.uploadAudio("remote-audio", any()) } returns readyDetail("remote-audio")
        mockForegroundService()

        val viewModel = RecordingViewModel(
            application = application,
            authStore = authStore,
            settingsStore = settingsStore,
            waiApi = waiApi,
            localRecordingStore = localStore,
            syncScheduler = scheduler,
            audioRecorderFactory = { FakeAudioRecorder() },
            webSocketFactory = { FakeWebSocket(segments = liveSegments, didFinalize = true) },
        )

        viewModel.startRecording(permissionGranted = true)
        advanceUntilIdle()
        viewModel.stopRecording()
        advanceUntilIdle()

        coVerify { waiApi.uploadAudio("remote-audio", any()) }
        coVerify(exactly = 0) {
            waiApi.saveLiveTranscript(any(), any(), any())
        }
        unmockkAll()
    }

    @Test
    @OptIn(ExperimentalCoroutinesApi::class)
    fun `failed upload stores manifest and schedules retry`() = runTest {
        val tempRoot = createTempDirectory("waicomputer-recording-fail").toFile()
        val authStore = mockk<AuthStore>()
        val settingsStore = mockk<SettingsStore>()
        val waiApi = mockk<WaiApi>()
        val scheduler = mockk<PendingSyncWorkerScheduler>()
        val application = mockApplication(tempRoot)
        val localStore = LocalRecordingStore(mockContext(tempRoot))
        val authState = MutableStateFlow<AuthState>(
            AuthState.Authenticated(
                UserSummary("user-1", "mik@example.com", Instant.now().toString()),
            ),
        )

        every { authStore.state } returns authState
        coEvery { settingsStore.snapshot() } returns appSettings()
        coEvery {
            waiApi.createRecording(
                title = any(),
                type = any(),
                language = any(),
                folderId = any(),
            )
        } returns Recording(
            id = "remote-2",
            type = RecordingType.note,
            status = RecordingStatus.PendingUpload,
            createdAt = Instant.now().toString(),
        )
        coEvery { waiApi.uploadAudio("remote-2", any()) } throws IllegalStateException("upload failed")
        every { scheduler.enqueue() } just Runs
        mockForegroundService()

        val viewModel = RecordingViewModel(
            application = application,
            authStore = authStore,
            settingsStore = settingsStore,
            waiApi = waiApi,
            localRecordingStore = localStore,
            syncScheduler = scheduler,
            audioRecorderFactory = { FakeAudioRecorder() },
            webSocketFactory = { FakeWebSocket() },
        )

        viewModel.startRecording(permissionGranted = true)
        advanceUntilIdle()
        viewModel.stopRecording()
        advanceUntilIdle()

        val manifest = localStore.listPending().singleOrNull()
        assertNotNull(manifest)
        assertEquals("remote-2", manifest!!.serverRecordingId)
        assertEquals("upload failed", manifest.failureMessage)
        assertEquals("upload failed", viewModel.uiState.value.error)
        coVerify { waiApi.uploadAudio("remote-2", any()) }
        io.mockk.verify { scheduler.enqueue() }
        unmockkAll()
    }

    @Test
    @OptIn(ExperimentalCoroutinesApi::class)
    fun `server-side failed upload preserves local manifest and schedules retry`() = runTest {
        val tempRoot = createTempDirectory("waicomputer-recording-server-fail").toFile()
        val authStore = mockk<AuthStore>()
        val settingsStore = mockk<SettingsStore>()
        val waiApi = mockk<WaiApi>()
        val scheduler = mockk<PendingSyncWorkerScheduler>()
        val application = mockApplication(tempRoot)
        val localStore = LocalRecordingStore(mockContext(tempRoot))
        val authState = MutableStateFlow<AuthState>(
            AuthState.Authenticated(
                UserSummary("user-1", "mik@example.com", Instant.now().toString()),
            ),
        )

        every { authStore.state } returns authState
        coEvery { settingsStore.snapshot() } returns appSettings()
        coEvery {
            waiApi.createRecording(
                title = any(),
                type = any(),
                language = any(),
                folderId = any(),
            )
        } returns Recording(
            id = "remote-server-failed",
            type = RecordingType.note,
            status = RecordingStatus.PendingUpload,
            createdAt = Instant.now().toString(),
        )
        coEvery { waiApi.uploadAudio("remote-server-failed", any()) } returns RecordingDetail(
            id = "remote-server-failed",
            type = RecordingType.note,
            status = RecordingStatus.Failed,
            failureMessage = "Unsupported codec",
            createdAt = Instant.now().toString(),
        )
        every { scheduler.enqueue() } just Runs
        mockForegroundService()

        val viewModel = RecordingViewModel(
            application = application,
            authStore = authStore,
            settingsStore = settingsStore,
            waiApi = waiApi,
            localRecordingStore = localStore,
            syncScheduler = scheduler,
            audioRecorderFactory = { FakeAudioRecorder() },
            webSocketFactory = { FakeWebSocket() },
        )

        viewModel.startRecording(permissionGranted = true)
        advanceUntilIdle()
        viewModel.stopRecording()
        advanceUntilIdle()

        val manifest = localStore.listPending().singleOrNull()
        assertNotNull(manifest)
        assertEquals("remote-server-failed", manifest!!.serverRecordingId)
        assertEquals("Unsupported codec", manifest.failureMessage)
        assertEquals("Unsupported codec", viewModel.uiState.value.error)
        io.mockk.verify { scheduler.enqueue() }
        unmockkAll()
    }

    private fun mockForegroundService() {
        mockkObject(RecordingForegroundService.Companion)
        every { RecordingForegroundService.start(any()) } just Runs
        every { RecordingForegroundService.stop(any()) } just Runs
    }

    private fun mockApplication(root: File): Application {
        val application = mockk<Application>(relaxed = true)
        every { application.filesDir } returns root
        every { application.applicationContext } returns application
        every { application.packageName } returns "is.waiwai.computer"
        return application
    }

    private fun mockContext(root: File): Context {
        val context = mockk<Context>()
        every { context.filesDir } returns root
        return context
    }

    private fun appSettings() = AppSettings(
        baseUrl = "https://wai.computer",
        transcriptionLanguage = "multi",
        authMode = StoredAuthMode.Authenticated,
        authUserId = "user-1",
        onboardingSeen = true,
        guestSinceEpochMillis = null,
        legacyAccessToken = null,
    )

    private fun readyDetail(id: String) = RecordingDetail(
        id = id,
        type = RecordingType.note,
        status = RecordingStatus.Ready,
        createdAt = Instant.now().toString(),
        durationSeconds = 1,
    )
}

private class FakeAudioRecorder : AudioRecorder {
    override val isRecording: Boolean = true

    override fun start() = flowOf(shortArrayOf(1, 2, 3, 4))

    override suspend fun stop() = Unit
}

private class FakeWebSocket(
    private val connectError: Throwable? = null,
    private val segments: List<LiveTranscriptSegment> = emptyList(),
    private val didFinalize: Boolean = false,
) : RealtimeWebSocketManager {
    private val mutableEvents = MutableSharedFlow<WsEvent>(extraBufferCapacity = 8)

    override val events: SharedFlow<WsEvent> = mutableEvents
    override val collectedSegments: List<LiveTranscriptSegment> = segments

    override suspend fun connect() {
        connectError?.let { throw it }
        mutableEvents.emit(WsEvent.Connected)
    }

    override suspend fun sendAudio(data: ByteArray) = Unit

    override suspend fun finishStreaming(timeoutMillis: Long): Boolean = didFinalize

    override suspend fun disconnect() = Unit
}
