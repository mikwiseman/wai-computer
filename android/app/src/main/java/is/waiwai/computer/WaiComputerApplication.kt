package `is`.waiwai.computer

import android.app.Application
import androidx.work.Configuration
import `is`.waiwai.computer.data.AppContainer
import `is`.waiwai.computer.sync.PendingSyncWorkerFactory

class WaiComputerApplication : Application(), Configuration.Provider {
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
