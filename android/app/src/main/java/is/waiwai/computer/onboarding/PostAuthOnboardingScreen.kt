package `is`.waiwai.computer.onboarding

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import `is`.waiwai.computer.data.WaiApi

private const val PROMPT_TEXT =
    "Hi, I'm setting up Wai Computer. It records meetings, calls, and ideas through my day " +
        "so I don't have to remember them all. Wai listens, transcribes the people I talk to, " +
        "and keeps the moments that matter."

@Composable
fun PostAuthOnboardingScreen(
    waiApi: WaiApi,
    onDone: () -> Unit,
) {
    val context = LocalContext.current
    val viewModel = remember { VoiceEnrollmentViewModel(waiApi = waiApi, context = context) }
    val uiState by viewModel.uiState.collectAsState()

    val permissionLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission(),
    ) { granted ->
        viewModel.onPermissionResult(granted)
        if (granted) viewModel.start()
    }

    LaunchedEffect(Unit) {
        val hasPermission = ContextCompat.checkSelfPermission(
            context,
            Manifest.permission.RECORD_AUDIO,
        ) == PackageManager.PERMISSION_GRANTED
        viewModel.onPermissionResult(hasPermission)
    }

    Surface(modifier = Modifier.fillMaxSize()) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(horizontal = 24.dp, vertical = 32.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Top,
        ) {
            Text(
                text = "Teach Wai your voice",
                style = MaterialTheme.typography.headlineMedium,
                fontWeight = FontWeight.SemiBold,
            )
            Spacer(Modifier.height(8.dp))
            Text(
                text = "Read the prompt for ~20 seconds. Wai will recognise you in future meetings automatically.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(24.dp))
            Surface(
                modifier = Modifier.fillMaxWidth(),
                shape = RoundedCornerShape(14.dp),
                tonalElevation = 1.dp,
            ) {
                Text(
                    text = PROMPT_TEXT,
                    modifier = Modifier.padding(16.dp),
                    style = MaterialTheme.typography.bodyLarge,
                )
            }
            Spacer(Modifier.height(24.dp))

            val canTapRecord = uiState.state == VoiceUiState.State.Idle ||
                uiState.state == VoiceUiState.State.Recording
            Box(
                modifier = Modifier
                    .size(88.dp)
                    .clip(CircleShape)
                    .clickable(enabled = canTapRecord) {
                        if (!uiState.hasPermission) {
                            permissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
                        } else if (uiState.state == VoiceUiState.State.Recording) {
                            viewModel.stop()
                        } else {
                            viewModel.start()
                        }
                    },
                contentAlignment = Alignment.Center,
            ) {
                Surface(
                    shape = CircleShape,
                    color = if (uiState.state == VoiceUiState.State.Recording) Color.Red
                    else MaterialTheme.colorScheme.primary,
                    modifier = Modifier.size(88.dp),
                ) {
                    Box(contentAlignment = Alignment.Center) {
                        Text(
                            text = if (uiState.state == VoiceUiState.State.Recording) "Stop"
                            else "Record",
                            color = Color.White,
                            fontWeight = FontWeight.SemiBold,
                        )
                    }
                }
            }

            Spacer(Modifier.height(16.dp))
            LinearProgressIndicator(
                progress = { uiState.progress },
                modifier = Modifier.fillMaxWidth(),
            )
            Spacer(Modifier.height(8.dp))
            Text(
                text = uiState.statusLabel,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            uiState.errorMessage?.let {
                Spacer(Modifier.height(8.dp))
                Text(it, color = Color.Red, style = MaterialTheme.typography.bodySmall)
            }
            Spacer(Modifier.height(24.dp))

            if (uiState.state == VoiceUiState.State.Recorded) {
                Button(
                    onClick = { viewModel.submit(onDone) },
                    enabled = uiState.state != VoiceUiState.State.Uploading,
                    modifier = Modifier.fillMaxWidth(),
                ) { Text("Use this take") }
                Spacer(Modifier.height(8.dp))
                TextButton(onClick = { viewModel.reset() }) { Text("Re-record") }
            }
            if (uiState.state == VoiceUiState.State.Uploading) {
                CircularProgressIndicator()
                Spacer(Modifier.height(8.dp))
                Text("Uploading…")
            }

            Spacer(Modifier.height(24.dp))
            TextButton(onClick = onDone) { Text("Skip for now") }
            Spacer(Modifier.height(16.dp))
            Text(
                text = "We store a 192-number signature, not your audio. The recording is deleted after the signature is created.",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}
