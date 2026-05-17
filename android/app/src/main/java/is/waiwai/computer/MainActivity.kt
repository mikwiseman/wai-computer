package `is`.waiwai.computer

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import `is`.waiwai.computer.ui.WaiAndroidApp
import `is`.waiwai.computer.ui.theme.WaiTheme

class MainActivity : ComponentActivity() {
    private var pendingMagicLinkToken by mutableStateOf<String?>(null)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        pendingMagicLinkToken = parseMagicToken(intent)

        val container = (application as WaiComputerApplication).container
        setContent {
            WaiTheme {
                WaiAndroidApp(
                    container = container,
                    pendingMagicLinkToken = pendingMagicLinkToken,
                    onMagicLinkConsumed = { pendingMagicLinkToken = null },
                )
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        pendingMagicLinkToken = parseMagicToken(intent)
    }

    private fun parseMagicToken(intent: Intent?): String? {
        val data = intent?.data ?: return null
        if (data.scheme != "waicomputer") return null
        val isCurrentAndroidLink = data.host == "magic"
        val isLegacySharedLink = data.host == "auth" && data.path == "/verify"
        if (!isCurrentAndroidLink && !isLegacySharedLink) return null
        return data.getQueryParameter("token")
    }
}
