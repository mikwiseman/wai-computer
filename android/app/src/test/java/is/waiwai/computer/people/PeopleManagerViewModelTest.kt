package `is`.waiwai.computer.people

import `is`.waiwai.computer.MainDispatcherRule
import `is`.waiwai.computer.data.Person
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
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class PeopleManagerViewModelTest {
    @get:Rule
    val mainDispatcherRule = MainDispatcherRule()

    @After
    fun tearDown() {
        unmockkAll()
    }

    @Test
    @OptIn(ExperimentalCoroutinesApi::class)
    fun `init loads and sorts people`() = runTest(mainDispatcherRule.dispatcher) {
        val api = mockk<WaiApi>()
        coEvery { api.listPeople() } returns listOf(person("p-2", "Zara"), person("p-1", "Anna"))
        val vm = PeopleManagerViewModel(api)
        advanceUntilIdle()

        assertEquals(listOf("Anna", "Zara"), vm.uiState.value.people.map { it.displayName })
    }

    @Test
    @OptIn(ExperimentalCoroutinesApi::class)
    fun `rename updates the matching person and clears pending`() = runTest(mainDispatcherRule.dispatcher) {
        val api = mockk<WaiApi>()
        coEvery { api.listPeople() } returns listOf(person("p-1", "Old"))
        coEvery { api.updatePerson(id = "p-1", displayName = "New", color = null, aliases = null) } returns
            person("p-1", "New")
        val vm = PeopleManagerViewModel(api)
        advanceUntilIdle()

        vm.rename("p-1", "New")
        advanceUntilIdle()

        assertEquals("New", vm.uiState.value.people.single().displayName)
        assertNull(vm.uiState.value.pendingActionId)
    }

    @Test
    @OptIn(ExperimentalCoroutinesApi::class)
    fun `delete removes person on success`() = runTest(mainDispatcherRule.dispatcher) {
        val api = mockk<WaiApi>(relaxed = true)
        coEvery { api.listPeople() } returns listOf(person("p-1", "Mik"))
        coEvery { api.deletePerson("p-1") } returns Unit
        val vm = PeopleManagerViewModel(api)
        advanceUntilIdle()

        vm.delete("p-1")
        advanceUntilIdle()

        assertTrue(vm.uiState.value.people.isEmpty())
    }

    @Test
    @OptIn(ExperimentalCoroutinesApi::class)
    fun `rename with blank name is a noop`() = runTest(mainDispatcherRule.dispatcher) {
        val api = mockk<WaiApi>(relaxed = true)
        coEvery { api.listPeople() } returns listOf(person("p-1", "Mik"))
        val vm = PeopleManagerViewModel(api)
        advanceUntilIdle()

        vm.rename("p-1", "   ")
        advanceUntilIdle()

        coVerify(exactly = 0) { api.updatePerson(any(), any(), any(), any()) }
    }

    @Test
    @OptIn(ExperimentalCoroutinesApi::class)
    fun `delete failure surfaces error and keeps person`() = runTest(mainDispatcherRule.dispatcher) {
        val api = mockk<WaiApi>()
        coEvery { api.listPeople() } returns listOf(person("p-1", "Mik"))
        coEvery { api.deletePerson("p-1") } throws IllegalStateException("nope")
        val vm = PeopleManagerViewModel(api)
        advanceUntilIdle()

        vm.delete("p-1")
        advanceUntilIdle()

        assertEquals(1, vm.uiState.value.people.size)
        assertEquals("nope", vm.uiState.value.error)
    }

    private fun person(id: String, name: String): Person = Person(
        id = id,
        displayName = name,
        color = null,
        aliases = null,
        voiceprintCount = 1,
        createdAt = Instant.now().toString(),
        updatedAt = Instant.now().toString(),
    )
}
