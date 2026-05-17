package `is`.waiwai.computer.data

import android.app.Application
import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.ProcessLifecycleOwner
import `is`.waiwai.computer.BuildConfig
import `is`.waiwai.computer.auth.AuthStore
import `is`.waiwai.computer.monitoring.SentryHelper
import `is`.waiwai.computer.sync.LocalRecordingStore
import `is`.waiwai.computer.sync.NetworkMonitor
import `is`.waiwai.computer.sync.PendingSyncWorkerScheduler
import `is`.waiwai.computer.sync.SyncCoordinator
import java.io.File
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

class AppContainer(
    application: Application,
    settingsStoreOverride: SettingsStore? = null,
    secureTokenStoreOverride: SecureTokenStore? = null,
    transportOverride: ApiTransport? = null,
    authStoreOverride: AuthStore? = null,
    waiApiOverride: WaiApi? = null,
    localRecordingStoreOverride: LocalRecordingStore? = null,
    networkMonitorOverride: NetworkMonitor? = null,
    syncSchedulerOverride: PendingSyncWorkerScheduler? = null,
    syncCoordinatorOverride: SyncCoordinator? = null,
    private val sentryDsnOverride: String? = null,
) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val dataStore = PreferenceDataStoreFactory.create(
        scope = scope,
        produceFile = {
            File(application.filesDir.parentFile, "datastore/wai_settings.preferences_pb")
        },
    )

    val settingsStore = settingsStoreOverride ?: SettingsStore(dataStore)
    private val secureTokenStore = secureTokenStoreOverride ?: SecureTokenStore(application)
    private val transport = transportOverride ?: ApiTransport(settingsStore)
    val authStore = authStoreOverride ?: AuthStore(
        settingsStore = settingsStore,
        secureTokenStore = secureTokenStore,
        transport = transport,
    )
    val waiApi = waiApiOverride ?: WaiApi(transport = transport, authStore = authStore)
    val localRecordingStore = localRecordingStoreOverride ?: LocalRecordingStore(application)
    val networkMonitor = networkMonitorOverride ?: NetworkMonitor(application)
    private val syncScheduler = syncSchedulerOverride ?: PendingSyncWorkerScheduler(application)
    val syncCoordinator = syncCoordinatorOverride ?: SyncCoordinator(
        authStore = authStore,
        networkMonitor = networkMonitor,
        scheduler = syncScheduler,
    )

    fun bootstrap() {
        val sentryDsn = sentryDsnOverride ?: BuildConfig.SENTRY_DSN
        if (sentryDsn.isNotBlank()) {
            SentryHelper.start(sentryDsn)
        }

        scope.launch {
            authStore.bootstrap()
            syncCoordinator.start()
        }

        ProcessLifecycleOwner.get().lifecycle.addObserver(
            object : DefaultLifecycleObserver {
                override fun onStart(owner: LifecycleOwner) {
                    scope.launch {
                        authStore.bootstrap()
                        syncScheduler.enqueue()
                    }
                }
            },
        )
    }

    fun enqueuePendingSync() {
        syncScheduler.enqueue()
    }
}
