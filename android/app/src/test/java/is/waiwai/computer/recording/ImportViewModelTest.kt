package `is`.waiwai.computer.recording

import `is`.waiwai.computer.MainDispatcherRule
import `is`.waiwai.computer.data.Recording
import `is`.waiwai.computer.data.RecordingDetail
import `is`.waiwai.computer.data.RecordingStatus
import `is`.waiwai.computer.data.RecordingType
import `is`.waiwai.computer.data.WaiApi
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.mockk
import io.mockk.unmockkAll
import java.io.ByteArrayInputStream
import java.io.File
import java.io.InputStream
import java.time.Instant
import kotlin.io.path.createTempDirectory
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class ImportViewModelTest {
    @get:Rule
    val mainDispatcherRule = MainDispatcherRule()

    private val cacheDir: File = createTempDirectory("import-vm-cache").toFile()

    @After
    fun tearDown() {
        cacheDir.deleteRecursively()
        unmockkAll()
    }

    @Test
    @OptIn(ExperimentalCoroutinesApi::class)
    fun `successful import creates recording uploads audio and reports success`() = runTest {
        val api = mockk<WaiApi>()
        val created = Recording(
            id = "rec-1",
            title = "memo",
            type = RecordingType.note,
            status = RecordingStatus.PendingUpload,
            createdAt = Instant.now().toString(),
        )
        coEvery { api.createRecording(title = "memo", type = RecordingType.note, language = "en") } returns created
        coEvery { api.uploadAudio("rec-1", any()) } returns readyDetail("rec-1")
        val vm = ImportViewModel(
            waiApi = api,
            cacheDirProvider = { cacheDir },
            language = "en",
            ioDispatcher = StandardTestDispatcher(testScheduler),
        )

        vm.import(FakeSource("memo.mp3", "mp3", "abc".toByteArray()))
        advanceUntilIdle()

        val state = vm.uiState.value
        assertTrue("expected Success but was $state", state is ImportUiState.Success)
        assertEquals("rec-1", (state as ImportUiState.Success).recording.id)
        coVerify { api.uploadAudio("rec-1", any()) }
        // cached file should be cleaned up
        assertTrue(cacheDir.listFiles().orEmpty().none { it.name.startsWith("import-") })
    }

    @Test
    @OptIn(ExperimentalCoroutinesApi::class)
    fun `failed upload deletes the freshly created recording and reports error`() = runTest {
        val api = mockk<WaiApi>(relaxed = true)
        val created = Recording(
            id = "rec-2",
            title = "broken",
            type = RecordingType.note,
            status = RecordingStatus.PendingUpload,
            createdAt = Instant.now().toString(),
        )
        coEvery { api.createRecording(title = "broken", type = RecordingType.note, language = "en") } returns created
        coEvery { api.uploadAudio("rec-2", any()) } throws IllegalStateException("network down")
        val vm = ImportViewModel(
            waiApi = api,
            cacheDirProvider = { cacheDir },
            language = "en",
            ioDispatcher = StandardTestDispatcher(testScheduler),
        )

        vm.import(FakeSource("broken.wav", "wav", "abc".toByteArray()))
        advanceUntilIdle()

        val state = vm.uiState.value
        assertTrue(state is ImportUiState.Error)
        assertEquals("network down", (state as ImportUiState.Error).message)
        coVerify { api.deleteRecording("rec-2", true) }
    }

    @Test
    @OptIn(ExperimentalCoroutinesApi::class)
    fun `failure to open the input stream surfaces error without server calls`() = runTest {
        val api = mockk<WaiApi>(relaxed = true)
        val vm = ImportViewModel(
            waiApi = api,
            cacheDirProvider = { cacheDir },
            language = "en",
            ioDispatcher = StandardTestDispatcher(testScheduler),
        )

        vm.import(FakeSource("gone.mp3", "mp3", null))
        advanceUntilIdle()

        val state = vm.uiState.value
        assertTrue(state is ImportUiState.Error)
        coVerify(exactly = 0) { api.createRecording(any(), any(), any(), any()) }
        coVerify(exactly = 0) { api.uploadAudio(any(), any()) }
    }

    @Test
    @OptIn(ExperimentalCoroutinesApi::class)
    fun `failed processing surfaces failure message without cleanup of server recording`() = runTest {
        val api = mockk<WaiApi>(relaxed = true)
        val created = Recording(
            id = "rec-3",
            title = "weird",
            type = RecordingType.note,
            status = RecordingStatus.PendingUpload,
            createdAt = Instant.now().toString(),
        )
        coEvery { api.createRecording(title = "weird", type = RecordingType.note, language = "en") } returns created
        coEvery { api.uploadAudio("rec-3", any()) } returns RecordingDetail(
            id = "rec-3",
            status = RecordingStatus.Failed,
            failureMessage = "Unsupported codec",
            createdAt = Instant.now().toString(),
        )
        val vm = ImportViewModel(
            waiApi = api,
            cacheDirProvider = { cacheDir },
            language = "en",
            ioDispatcher = StandardTestDispatcher(testScheduler),
        )

        vm.import(FakeSource("weird.opus", "opus", "abc".toByteArray()))
        advanceUntilIdle()

        val state = vm.uiState.value
        assertTrue(state is ImportUiState.Error)
        assertEquals("Unsupported codec", (state as ImportUiState.Error).message)
        // server failure ≠ exception path → do NOT permanently delete
        coVerify(exactly = 0) { api.deleteRecording(any(), true) }
    }

    @Test
    @OptIn(ExperimentalCoroutinesApi::class)
    fun `consumeSuccess returns to Idle only when Success`() = runTest {
        val api = mockk<WaiApi>()
        val created = Recording(
            id = "rec-1",
            title = "memo",
            type = RecordingType.note,
            status = RecordingStatus.PendingUpload,
            createdAt = Instant.now().toString(),
        )
        coEvery { api.createRecording(any(), any(), any(), any()) } returns created
        coEvery { api.uploadAudio(any(), any()) } returns readyDetail("rec-1")
        val vm = ImportViewModel(
            waiApi = api,
            cacheDirProvider = { cacheDir },
            language = "en",
            ioDispatcher = StandardTestDispatcher(testScheduler),
        )

        vm.import(FakeSource("memo.mp3", "mp3", "abc".toByteArray()))
        advanceUntilIdle()
        assertNotNull(vm.uiState.value as? ImportUiState.Success)

        vm.consumeSuccess()
        assertEquals(ImportUiState.Idle, vm.uiState.value)
    }

    @Test
    @OptIn(ExperimentalCoroutinesApi::class)
    fun `second import is a no-op while one is in flight`() = runTest {
        val api = mockk<WaiApi>(relaxed = true)
        val vm = ImportViewModel(
            waiApi = api,
            cacheDirProvider = { cacheDir },
            language = "en",
            ioDispatcher = StandardTestDispatcher(testScheduler),
        )

        vm.import(FakeSource("first.mp3", "mp3", "a".toByteArray()))
        val afterFirst = vm.uiState.value
        assertTrue(afterFirst is ImportUiState.Uploading)
        assertEquals("first", (afterFirst as ImportUiState.Uploading).filename)

        vm.import(FakeSource("second.mp3", "mp3", "b".toByteArray()))
        val afterSecond = vm.uiState.value
        assertTrue(afterSecond is ImportUiState.Uploading)
        // second call must not overwrite the filename — it's a no-op
        assertEquals("first", (afterSecond as ImportUiState.Uploading).filename)
    }

    private fun readyDetail(id: String): RecordingDetail = RecordingDetail(
        id = id,
        status = RecordingStatus.Ready,
        createdAt = Instant.now().toString(),
    )

    private class FakeSource(
        override val displayName: String,
        override val extension: String?,
        private val bytes: ByteArray?,
    ) : ImportSource {
        override suspend fun openInputStream(): InputStream? = bytes?.let { ByteArrayInputStream(it) }
    }
}
