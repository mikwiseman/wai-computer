package `is`.waiwai.computer.library

import `is`.waiwai.computer.MainDispatcherRule
import `is`.waiwai.computer.data.Folder
import `is`.waiwai.computer.data.WaiApi
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
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class FolderManagerViewModelTest {
    @get:Rule
    val mainDispatcherRule = MainDispatcherRule()

    @After
    fun tearDown() {
        unmockkAll()
    }

    @Test
    @OptIn(ExperimentalCoroutinesApi::class)
    fun `init loads and sorts folders by name`() = runTest(mainDispatcherRule.dispatcher) {
        val api = mockk<WaiApi>()
        coEvery { api.listFolders() } returns listOf(
            folder("f-2", "Zebra"),
            folder("f-1", "Alpha"),
        )
        val vm = FolderManagerViewModel(api)
        advanceUntilIdle()

        val state = vm.uiState.value
        assertEquals(listOf("Alpha", "Zebra"), state.folders.map { it.name })
        assertFalse(state.isLoading)
        assertNull(state.error)
    }

    @Test
    @OptIn(ExperimentalCoroutinesApi::class)
    fun `create appends folder and re-sorts`() = runTest(mainDispatcherRule.dispatcher) {
        val api = mockk<WaiApi>()
        coEvery { api.listFolders() } returns listOf(folder("f-1", "Alpha"))
        coEvery { api.createFolder("Beta") } returns folder("f-2", "Beta")
        val vm = FolderManagerViewModel(api)
        advanceUntilIdle()

        vm.create("  Beta  ")
        advanceUntilIdle()

        assertEquals(listOf("Alpha", "Beta"), vm.uiState.value.folders.map { it.name })
    }

    @Test
    @OptIn(ExperimentalCoroutinesApi::class)
    fun `create with blank name is ignored`() = runTest(mainDispatcherRule.dispatcher) {
        val api = mockk<WaiApi>(relaxed = true)
        coEvery { api.listFolders() } returns emptyList()
        val vm = FolderManagerViewModel(api)
        advanceUntilIdle()

        vm.create("   ")
        advanceUntilIdle()

        coVerify(exactly = 0) { api.createFolder(any()) }
    }

    @Test
    @OptIn(ExperimentalCoroutinesApi::class)
    fun `rename updates the matching folder`() = runTest(mainDispatcherRule.dispatcher) {
        val api = mockk<WaiApi>()
        coEvery { api.listFolders() } returns listOf(folder("f-1", "Old"))
        coEvery { api.renameFolder("f-1", "New") } returns folder("f-1", "New")
        val vm = FolderManagerViewModel(api)
        advanceUntilIdle()

        vm.rename("f-1", "New")
        advanceUntilIdle()

        assertEquals("New", vm.uiState.value.folders.single().name)
        assertNull(vm.uiState.value.pendingActionId)
    }

    @Test
    @OptIn(ExperimentalCoroutinesApi::class)
    fun `delete removes the folder optimistically and clears pending state`() = runTest(mainDispatcherRule.dispatcher) {
        val api = mockk<WaiApi>(relaxed = true)
        coEvery { api.listFolders() } returns listOf(folder("f-1", "Doomed"))
        coEvery { api.deleteFolder("f-1") } returns Unit
        val vm = FolderManagerViewModel(api)
        advanceUntilIdle()

        vm.delete("f-1")
        advanceUntilIdle()

        assertTrue(vm.uiState.value.folders.isEmpty())
        assertNull(vm.uiState.value.pendingActionId)
    }

    @Test
    @OptIn(ExperimentalCoroutinesApi::class)
    fun `delete failure surfaces error and keeps folder`() = runTest(mainDispatcherRule.dispatcher) {
        val api = mockk<WaiApi>()
        coEvery { api.listFolders() } returns listOf(folder("f-1", "Keeper"))
        coEvery { api.deleteFolder("f-1") } throws IllegalStateException("server is grumpy")
        val vm = FolderManagerViewModel(api)
        advanceUntilIdle()

        vm.delete("f-1")
        advanceUntilIdle()

        assertEquals(1, vm.uiState.value.folders.size)
        assertEquals("server is grumpy", vm.uiState.value.error)
    }

    private fun folder(id: String, name: String) = Folder(
        id = id,
        name = name,
        createdAt = Instant.now().toString(),
    )
}
