package is.waiwai.say

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import is.waiwai.say.data.SettingsStore
import is.waiwai.say.data.WaiApi
import is.waiwai.say.ui.WaiAndroidApp

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val settingsStore = SettingsStore(applicationContext)
        val api = WaiApi(settingsStore)

        setContent {
            WaiAndroidApp(api = api, settingsStore = settingsStore)
        }
    }
}
