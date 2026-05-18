package `is`.waiwai.computer.library

import `is`.waiwai.computer.MainDispatcherRule
import `is`.waiwai.computer.data.RecordingDetail
import `is`.waiwai.computer.data.RecordingStatus
import `is`.waiwai.computer.data.Summary
import `is`.waiwai.computer.data.WaiApi
import `is`.waiwai.computer.sync.LocalRecordingStore
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.mockk
import io.mockk.unmockkAll
import java.time.Instant
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class RecordingDetailViewModelTest {
    @get:Rule
    val mainDispatcherRule = MainDispatcherRule()

    @After
    fun tearDown() {
        unmockkAll()
    }

    @Test
    @OptIn(ExperimentalCoroutinesApi::class)
    fun `regenerateSummary merges generated summary into detail`() = runTest(mainDispatcherRule.dispatcher) {
        val api = mockk<WaiApi>(relaxed = true)
        val store = mockk<LocalRecordingStore>()
        coEvery { store.manifest("rec-1") } returns null
        coEvery { api.getRecording("rec-1") } returns detail("rec-1", status = RecordingStatus.Ready)
        coEvery { api.listFolders() } returns emptyList()
        coEvery { api.generateSummary("rec-1") } returns Summary(
            summary = "Generated summary",
            keyPoints = listOf("one"),
        )

        val vm = RecordingDetailViewModel(api, store, recordingId = "rec-1", localOnly = false)
        advanceUntilIdle()
        vm.regenerateSummary()
        advanceUntilIdle()

        val state = vm.uiState.value
        assertEquals("Generated summary", state.detail?.summary?.summary)
        assertFalse(state.isGeneratingSummary)
        coVerify { api.generateSummary("rec-1") }
    }

    @Test
    @OptIn(ExperimentalCoroutinesApi::class)
    fun `regenerateSummary failure surfaces error and clears flag`() = runTest(mainDispatcherRule.dispatcher) {
        val api = mockk<WaiApi>(relaxed = true)
        val store = mockk<LocalRecordingStore>()
        coEvery { store.manifest("rec-1") } returns null
        coEvery { api.getRecording("rec-1") } returns detail("rec-1", status = RecordingStatus.Ready)
        coEvery { api.listFolders() } returns emptyList()
        coEvery { api.generateSummary("rec-1") } throws IllegalStateException("LLM down")

        val vm = RecordingDetailViewModel(api, store, recordingId = "rec-1", localOnly = false)
        advanceUntilIdle()
        vm.regenerateSummary()
        advanceUntilIdle()

        assertEquals("LLM down", vm.uiState.value.error)
        assertFalse(vm.uiState.value.isGeneratingSummary)
    }

    @Test
    @OptIn(ExperimentalCoroutinesApi::class)
    fun `regenerateSummary is a no-op when already generating`() = runTest(mainDispatcherRule.dispatcher) {
        val api = mockk<WaiApi>(relaxed = true)
        val store = mockk<LocalRecordingStore>()
        coEvery { store.manifest("rec-1") } returns null
        coEvery { api.getRecording("rec-1") } returns detail("rec-1", status = RecordingStatus.Ready)
        coEvery { api.listFolders() } returns emptyList()
        // generateSummary never returns
        coEvery { api.generateSummary("rec-1") } coAnswers {
            kotlinx.coroutines.awaitCancellation()
        }

        val vm = RecordingDetailViewModel(api, store, recordingId = "rec-1", localOnly = false)
        advanceUntilIdle()
        vm.regenerateSummary()
        runCurrent()
        vm.regenerateSummary()
        runCurrent()

        // Both calls scheduled, but the second short-circuits before launching.
        coVerify(exactly = 1) { api.generateSummary("rec-1") }
    }

    @Test
    @OptIn(ExperimentalCoroutinesApi::class)
    fun `polling refreshes detail until status leaves processing`() = runTest(mainDispatcherRule.dispatcher) {
        val api = mockk<WaiApi>(relaxed = true)
        val store = mockk<LocalRecordingStore>()
        coEvery { store.manifest("rec-1") } returns null
        coEvery { api.listFolders() } returns emptyList()
        coEvery { api.getRecording("rec-1") } returnsMany listOf(
            detail("rec-1", status = RecordingStatus.Processing),
            detail("rec-1", status = RecordingStatus.Processing),
            detail("rec-1", status = RecordingStatus.Ready),
        )

        val vm = RecordingDetailViewModel(api, store, recordingId = "rec-1", localOnly = false)
        advanceUntilIdle()
        // initial refresh -> Processing, polling starts. Advance through backoff window.
        advanceTimeBy(20_000)
        advanceUntilIdle()

        assertEquals(RecordingStatus.Ready, vm.uiState.value.detail?.status)
        coVerify(atLeast = 2) { api.getRecording("rec-1") }
    }

    @Test
    fun `backoffMillis follows 2-3-5-8 pattern`() {
        val api = mockk<WaiApi>()
        val store = mockk<LocalRecordingStore>(relaxed = true)
        coEvery { api.getRecording(any()) } returns detail("rec-1", status = RecordingStatus.Ready)
        coEvery { api.listFolders() } returns emptyList()

        val vm = RecordingDetailViewModel(api, store, recordingId = "rec-1", localOnly = false)
        assertEquals(2_000L, vm.backoffMillis(1))
        assertEquals(3_000L, vm.backoffMillis(2))
        assertEquals(5_000L, vm.backoffMillis(3))
        assertEquals(8_000L, vm.backoffMillis(4))
        assertEquals(8_000L, vm.backoffMillis(10))
    }

    @Test
    @OptIn(ExperimentalCoroutinesApi::class)
    fun `polling does not start when detail is Ready`() = runTest(mainDispatcherRule.dispatcher) {
        val api = mockk<WaiApi>(relaxed = true)
        val store = mockk<LocalRecordingStore>()
        coEvery { store.manifest("rec-1") } returns null
        coEvery { api.listFolders() } returns emptyList()
        coEvery { api.getRecording("rec-1") } returns detail("rec-1", status = RecordingStatus.Ready)

        val vm = RecordingDetailViewModel(api, store, recordingId = "rec-1", localOnly = false)
        advanceUntilIdle()
        // Advance plenty of time — no further getRecording calls expected.
        advanceTimeBy(60_000)
        advanceUntilIdle()

        coVerify(exactly = 1) { api.getRecording("rec-1") }
    }

    private fun detail(id: String, status: RecordingStatus, summary: Summary? = null): RecordingDetail = RecordingDetail(
        id = id,
        status = status,
        createdAt = Instant.now().toString(),
        summary = summary,
    )
}
