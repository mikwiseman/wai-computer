package `is`.waiwai.say

import android.app.Application
import androidx.work.Configuration
import `is`.waiwai.say.data.AppContainer
import `is`.waiwai.say.sync.PendingSyncWorkerFactory

class WaiApplication : Application(), Configuration.Provider {
    lateinit var container: AppContainer
        private set

    override fun onCreate() {
        super.onCreate()
        container = AppContainer(this)
        container.bootstrap()
    }

    override val workManagerConfiguration: Configuration
        get() = Configuration.Builder()
            .setWorkerFactory(PendingSyncWorkerFactory(container))
            .build()
}
