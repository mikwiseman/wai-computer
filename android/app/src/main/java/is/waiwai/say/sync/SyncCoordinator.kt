package `is`.waiwai.say.sync

import `is`.waiwai.say.auth.AuthState
import `is`.waiwai.say.auth.AuthStore
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.launch

class SyncCoordinator(
    private val authStore: AuthStore,
    private val networkMonitor: NetworkMonitor,
    private val scheduler: PendingSyncWorkerScheduler,
    private val scope: CoroutineScope = CoroutineScope(SupervisorJob() + Dispatchers.IO),
) {
    private var job: Job? = null

    fun start() {
        if (job != null) return
        job = scope.launch {
            combine(authStore.state, networkMonitor.isConnected) { state, connected ->
                state to connected
            }.collectLatest { (state, connected) ->
                if (connected && state is AuthState.Authenticated) {
                    scheduler.enqueue()
                }
            }
        }
    }

    suspend fun stop() {
        job?.cancelAndJoin()
        job = null
    }
}
