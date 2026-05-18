package `is`.waiwai.computer.search

import `is`.waiwai.computer.MainDispatcherRule
import `is`.waiwai.computer.data.SearchMode
import `is`.waiwai.computer.data.SearchResponse
import `is`.waiwai.computer.data.SearchResult
import `is`.waiwai.computer.data.WaiApi
import io.mockk.coEvery
import io.mockk.coVerify
import io.mockk.mockk
import io.mockk.unmockkAll
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

class SearchViewModelTest {
    @get:Rule
    val mainDispatcherRule = MainDispatcherRule()

    @After
    fun tearDown() {
        unmockkAll()
    }

    @Test
    @OptIn(ExperimentalCoroutinesApi::class)
    fun `submit fetches results and surfaces them`() = runTest {
        val api = mockk<WaiApi>()
        coEvery { api.search(query = "android", mode = SearchMode.Hybrid) } returns SearchResponse(
            results = listOf(sampleResult("rec-1")),
            total = 1,
        )
        val vm = SearchViewModel(api)

        vm.updateQuery("android")
        vm.submit()
        advanceUntilIdle()

        val state = vm.uiState.value
        assertEquals(1, state.results.size)
        assertEquals("rec-1", state.results.single().recordingId)
        assertFalse(state.isLoading)
        assertTrue(state.hasSearched)
        assertNull(state.error)
    }

    @Test
    @OptIn(ExperimentalCoroutinesApi::class)
    fun `submit on blank query is a noop`() = runTest {
        val api = mockk<WaiApi>(relaxed = true)
        val vm = SearchViewModel(api)

        vm.updateQuery("   ")
        vm.submit()
        advanceUntilIdle()

        coVerify(exactly = 0) { api.search(any(), any(), any(), any()) }
        assertFalse(vm.uiState.value.hasSearched)
    }

    @Test
    @OptIn(ExperimentalCoroutinesApi::class)
    fun `failed search surfaces error and clears results`() = runTest {
        val api = mockk<WaiApi>()
        coEvery { api.search(query = any(), mode = any()) } throws IllegalStateException("server is down")
        val vm = SearchViewModel(api)

        vm.updateQuery("memory")
        vm.submit()
        advanceUntilIdle()

        val state = vm.uiState.value
        assertEquals(emptyList<SearchResult>(), state.results)
        assertEquals("server is down", state.error)
        assertTrue(state.hasSearched)
    }

    @Test
    @OptIn(ExperimentalCoroutinesApi::class)
    fun `selecting a new mode re-runs the search when a query was already submitted`() = runTest {
        val api = mockk<WaiApi>()
        coEvery { api.search(query = "ship", mode = SearchMode.Hybrid) } returns SearchResponse(
            results = listOf(sampleResult("rec-h")),
            total = 1,
        )
        coEvery { api.search(query = "ship", mode = SearchMode.Semantic) } returns SearchResponse(
            results = listOf(sampleResult("rec-s")),
            total = 1,
        )
        val vm = SearchViewModel(api)

        vm.updateQuery("ship")
        vm.submit()
        advanceUntilIdle()
        vm.selectMode(SearchMode.Semantic)
        advanceUntilIdle()

        val state = vm.uiState.value
        assertEquals(SearchMode.Semantic, state.mode)
        assertEquals("rec-s", state.results.single().recordingId)
        coVerify { api.search("ship", SearchMode.Hybrid, any(), any()) }
        coVerify { api.search("ship", SearchMode.Semantic, any(), any()) }
    }

    @Test
    @OptIn(ExperimentalCoroutinesApi::class)
    fun `selecting the same mode does not re-fetch`() = runTest {
        val api = mockk<WaiApi>()
        coEvery { api.search(query = "ship", mode = SearchMode.Hybrid) } returns SearchResponse(
            results = listOf(sampleResult("rec-h")),
            total = 1,
        )
        val vm = SearchViewModel(api)

        vm.updateQuery("ship")
        vm.submit()
        advanceUntilIdle()
        vm.selectMode(SearchMode.Hybrid)
        advanceUntilIdle()

        coVerify(exactly = 1) { api.search(any(), any(), any(), any()) }
    }

    @Test
    @OptIn(ExperimentalCoroutinesApi::class)
    fun `clear resets state and cancels in-flight request`() = runTest {
        val api = mockk<WaiApi>()
        coEvery { api.search(any(), any(), any(), any()) } returns SearchResponse()
        val vm = SearchViewModel(api)

        vm.updateQuery("a")
        vm.submit()
        vm.clear()
        advanceUntilIdle()

        val state = vm.uiState.value
        assertEquals("", state.query)
        assertEquals(emptyList<SearchResult>(), state.results)
        assertFalse(state.hasSearched)
    }

    private fun sampleResult(id: String): SearchResult = SearchResult(
        recordingId = id,
        recordingTitle = "Sample",
        recordingType = "note",
        segmentId = "seg-1",
        speaker = "Mik",
        content = "Sample content",
        startMs = 0,
        endMs = 1000,
        score = 0.9,
    )
}
