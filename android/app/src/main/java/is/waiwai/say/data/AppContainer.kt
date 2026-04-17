package `is`.waiwai.say.data

import android.app.Application
import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.ProcessLifecycleOwner
import `is`.waiwai.say.BuildConfig
import `is`.waiwai.say.auth.AuthStore
import `is`.waiwai.say.monitoring.SentryHelper
import `is`.waiwai.say.sync.LocalRecordingStore
import `is`.waiwai.say.sync.NetworkMonitor
import `is`.waiwai.say.sync.PendingSyncWorkerScheduler
import `is`.waiwai.say.sync.SyncCoordinator
import java.io.File
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch

class AppContainer(
    application: Application,
) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val dataStore = PreferenceDataStoreFactory.create(
        scope = scope,
        produceFile = {
            File(application.filesDir.parentFile, "datastore/wai_settings.preferences_pb")
        },
    )

    val settingsStore = SettingsStore(dataStore)
    private val secureTokenStore = SecureTokenStore(application)
    private val transport = ApiTransport(settingsStore)
    val authStore = AuthStore(
        settingsStore = settingsStore,
        secureTokenStore = secureTokenStore,
        transport = transport,
    )
    val waiApi = WaiApi(transport = transport, authStore = authStore)
    val localRecordingStore = LocalRecordingStore(application)
    val networkMonitor = NetworkMonitor(application)
    private val syncScheduler = PendingSyncWorkerScheduler(application)
    val syncCoordinator = SyncCoordinator(
        authStore = authStore,
        networkMonitor = networkMonitor,
        scheduler = syncScheduler,
    )

    fun bootstrap() {
        if (BuildConfig.SENTRY_DSN.isNotBlank()) {
            SentryHelper.start(BuildConfig.SENTRY_DSN)
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
}
