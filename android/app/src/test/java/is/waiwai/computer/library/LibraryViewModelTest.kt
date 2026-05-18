package `is`.waiwai.computer.library

import `is`.waiwai.computer.MainDispatcherRule
import `is`.waiwai.computer.data.Recording
import `is`.waiwai.computer.data.RecordingStatus
import `is`.waiwai.computer.data.RecordingType
import `is`.waiwai.computer.data.WaiApi
import `is`.waiwai.computer.sync.LocalRecordingStore
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.mockk
import io.mockk.unmockkAll
import java.time.Instant
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class LibraryViewModelTest {
    @get:Rule
    val mainDispatcherRule = MainDispatcherRule()

    @After
    fun tearDown() {
        unmockkAll()
    }

    @Test
    @OptIn(ExperimentalCoroutinesApi::class)
    fun `initial load fetches All recordings`() = runTest(mainDispatcherRule.dispatcher) {
        val api = mockk<WaiApi>()
        val store = mockk<LocalRecordingStore>()
        coEvery {
            api.listRecordings(
                limit = 50,
                skip = 0,
                starred = false,
                trashed = false,
                type = null,
                folderId = null,
            )
        } returns listOf(
            recording("rec-1", starredAt = null),
            recording("rec-2", starredAt = "2026-05-18T10:00:00Z"),
        )
        coEvery { store.listPending() } returns emptyList()

        val vm = LibraryViewModel(api, store, isGuest = false)
        advanceUntilIdle()

        val state = vm.uiState.value
        check(state.error == null) { "Unexpected error: ${state.error}" }
        assertEquals(LibraryFilter.All, state.filter)
        assertEquals(2, state.items.size)
        assertFalse(state.isLoading)
        assertTrue(state.items.first { it.id == "rec-2" }.isStarred)
    }

    @Test
    @OptIn(ExperimentalCoroutinesApi::class)
    fun `setFilter Starred re-queries with starred true`() = runTest(mainDispatcherRule.dispatcher) {
        val api = mockk<WaiApi>(relaxed = true)
        val store = mockk<LocalRecordingStore>()
        coEvery { api.listRecordings(any(), any(), any(), any(), any(), any()) } returns emptyList()
        coEvery { store.listPending() } returns emptyList()

        val vm = LibraryViewModel(api, store, isGuest = false)
        advanceUntilIdle()
        vm.setFilter(LibraryFilter.Starred)
        advanceUntilIdle()

        coVerify { api.listRecordings(any(), any(), true, false, null, null) }
        assertEquals(LibraryFilter.Starred, vm.uiState.value.filter)
    }

    @Test
    @OptIn(ExperimentalCoroutinesApi::class)
    fun `setFilter Trash re-queries with trashed true`() = runTest(mainDispatcherRule.dispatcher) {
        val api = mockk<WaiApi>(relaxed = true)
        val store = mockk<LocalRecordingStore>()
        coEvery { api.listRecordings(any(), any(), any(), any(), any(), any()) } returns emptyList()
        coEvery { store.listPending() } returns emptyList()

        val vm = LibraryViewModel(api, store, isGuest = false)
        advanceUntilIdle()
        vm.setFilter(LibraryFilter.Trash)
        advanceUntilIdle()

        coVerify { api.listRecordings(any(), any(), false, true, null, null) }
    }

    @Test
    @OptIn(ExperimentalCoroutinesApi::class)
    fun `toggleStar optimistically updates and posts star to server`() = runTest(mainDispatcherRule.dispatcher) {
        val api = mockk<WaiApi>(relaxed = true)
        val store = mockk<LocalRecordingStore>()
        coEvery { api.listRecordings(any(), any(), any(), any(), any(), any()) } returns listOf(
            recording("rec-1", starredAt = null),
        )
        coEvery { store.listPending() } returns emptyList()
        coEvery { api.starRecording("rec-1") } returns recording("rec-1", starredAt = "now")

        val vm = LibraryViewModel(api, store, isGuest = false)
        advanceUntilIdle()
        vm.toggleStar("rec-1")
        advanceUntilIdle()

        assertTrue(vm.uiState.value.items.single().isStarred)
        coVerify { api.starRecording("rec-1") }
    }

    @Test
    @OptIn(ExperimentalCoroutinesApi::class)
    fun `toggleStar reverts optimistic update on failure`() = runTest(mainDispatcherRule.dispatcher) {
        val api = mockk<WaiApi>(relaxed = true)
        val store = mockk<LocalRecordingStore>()
        coEvery { api.listRecordings(any(), any(), any(), any(), any(), any()) } returns listOf(
            recording("rec-1", starredAt = null),
        )
        coEvery { store.listPending() } returns emptyList()
        coEvery { api.starRecording("rec-1") } throws IllegalStateException("network down")

        val vm = LibraryViewModel(api, store, isGuest = false)
        advanceUntilIdle()
        vm.toggleStar("rec-1")
        advanceUntilIdle()

        assertFalse(vm.uiState.value.items.single().isStarred)
        assertEquals("network down", vm.uiState.value.error)
    }

    @Test
    @OptIn(ExperimentalCoroutinesApi::class)
    fun `restore calls api and refreshes`() = runTest(mainDispatcherRule.dispatcher) {
        val api = mockk<WaiApi>(relaxed = true)
        val store = mockk<LocalRecordingStore>()
        coEvery { api.listRecordings(any(), any(), any(), any(), any(), any()) } returns emptyList()
        coEvery { store.listPending() } returns emptyList()
        coEvery { api.restoreRecording("rec-1") } returns recording("rec-1", starredAt = null)

        val vm = LibraryViewModel(api, store, isGuest = false)
        advanceUntilIdle()
        vm.restore("rec-1")
        advanceUntilIdle()

        coVerify { api.restoreRecording("rec-1") }
    }

    @Test
    @OptIn(ExperimentalCoroutinesApi::class)
    fun `deleteForever permanently deletes via api`() = runTest(mainDispatcherRule.dispatcher) {
        val api = mockk<WaiApi>(relaxed = true)
        val store = mockk<LocalRecordingStore>()
        coEvery { api.listRecordings(any(), any(), any(), any(), any(), any()) } returns emptyList()
        coEvery { store.listPending() } returns emptyList()

        val vm = LibraryViewModel(api, store, isGuest = false)
        advanceUntilIdle()
        vm.deleteForever("rec-1")
        advanceUntilIdle()

        coVerify { api.deleteRecording("rec-1", true) }
    }

    private fun recording(id: String, starredAt: String?, deletedAt: String? = null): Recording = Recording(
        id = id,
        type = RecordingType.note,
        status = RecordingStatus.Ready,
        createdAt = Instant.now().toString(),
        starredAt = starredAt,
        deletedAt = deletedAt,
    )
}
