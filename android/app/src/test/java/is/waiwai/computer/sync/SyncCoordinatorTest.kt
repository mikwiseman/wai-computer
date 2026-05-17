package `is`.waiwai.computer.sync

import `is`.waiwai.computer.MainDispatcherRule
import `is`.waiwai.computer.auth.AuthState
import `is`.waiwai.computer.auth.AuthStore
import `is`.waiwai.computer.data.UserSummary
import io.mockk.every
import io.mockk.mockk
import io.mockk.verify
import java.time.Instant
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import org.junit.Rule
import org.junit.Test

class SyncCoordinatorTest {
    @get:Rule
    val mainDispatcherRule = MainDispatcherRule()

    @Test
    @OptIn(ExperimentalCoroutinesApi::class)
    fun `enqueue runs only when authenticated and connected`() = runTest {
        val authStore = mockk<AuthStore>()
        val networkMonitor = mockk<NetworkMonitor>()
        val scheduler = mockk<PendingSyncWorkerScheduler>(relaxed = true)
        val authState = MutableStateFlow<AuthState>(AuthState.Guest(Instant.now()))
        val isConnected = MutableStateFlow(false)

        every { authStore.state } returns authState
        every { networkMonitor.isConnected } returns isConnected

        val coordinator = SyncCoordinator(
            authStore = authStore,
            networkMonitor = networkMonitor,
            scheduler = scheduler,
            scope = this,
        )

        coordinator.start()
        advanceUntilIdle()

        verify(exactly = 0) { scheduler.enqueue() }

        isConnected.value = true
        advanceUntilIdle()

        verify(exactly = 0) { scheduler.enqueue() }

        authState.value = AuthState.Authenticated(
            UserSummary(
                id = "user-1",
                email = "mik@example.com",
                createdAt = Instant.now().toString(),
            ),
        )
        advanceUntilIdle()

        verify(exactly = 1) { scheduler.enqueue() }
        coordinator.stop()
    }
}
