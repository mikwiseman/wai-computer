package `is`.waiwai.say.recording

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.provider.Settings
import android.view.HapticFeedbackConstants
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.runtime.produceState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import `is`.waiwai.say.R
import `is`.waiwai.say.data.AppContainer
import `is`.waiwai.say.data.Folder
import `is`.waiwai.say.ui.components.BannerCard
import `is`.waiwai.say.ui.components.BannerVariant
import `is`.waiwai.say.ui.components.RecordButton
import `is`.waiwai.say.ui.components.StatusRing

@Composable
fun RecordingScreen(
    modifier: Modifier = Modifier,
    container: AppContainer,
    isGuest: Boolean,
    viewModel: RecordingViewModel? = null,
) {
    val context = LocalContext.current
    val view = LocalView.current
    val resolvedViewModel = viewModel ?: remember(container) {
        RecordingViewModel(
            application = context.applicationContext as android.app.Application,
            authStore = container.authStore,
            settingsStore = container.settingsStore,
            waiApi = container.waiApi,
            localRecordingStore = container.localRecordingStore,
            syncScheduler = `is`.waiwai.say.sync.PendingSyncWorkerScheduler(context),
        )
    }
    val uiState by resolvedViewModel.uiState.collectAsState()
    var selectedFolderId by rememberSaveable { mutableStateOf<String?>(null) }
    var showFolderPicker by rememberSaveable { mutableStateOf(false) }
    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted ->
        resolvedViewModel.startRecording(granted, selectedFolderId)
    }
    val latestPhase by rememberUpdatedState(uiState.phase)
    val folders by produceState(initialValue = emptyList<Folder>(), container, isGuest) {
        value = if (isGuest) {
            emptyList()
        } else {
            runCatching { container.waiApi.listFolders() }.getOrDefault(emptyList())
        }
    }
    val selectedFolderName = folders.firstOrNull { it.id == selectedFolderId }?.name
        ?: stringResource(R.string.record_folder_none)

    LaunchedEffect(latestPhase) {
        when (latestPhase) {
            Phase.Recording -> {
                view.performHapticFeedback(HapticFeedbackConstants.KEYBOARD_TAP)
                view.announceForAccessibility(context.getString(R.string.status_recording_started))
            }
            Phase.Finalizing -> {
                view.performHapticFeedback(HapticFeedbackConstants.KEYBOARD_TAP)
                view.announceForAccessibility(context.getString(R.string.status_recording_stopped))
            }
            else -> Unit
        }
    }

    Column(
        modifier = modifier
            .fillMaxSize()
            .padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = stringResource(R.string.tab_record),
                style = MaterialTheme.typography.headlineMedium,
                fontWeight = FontWeight.Bold,
            )
            if (!isGuest) {
                TextButton(onClick = { showFolderPicker = true }) {
                    Text(
                        text = stringResource(R.string.record_folder_picker_label, selectedFolderName),
                    )
                }
            }
        }
        StatusRing(
            phase = uiState.phase,
            modifier = Modifier.semantics {
                contentDescription = context.getString(R.string.record_status_ring)
            },
        )
        Text(
            text = formatDuration(uiState.durationSeconds),
            style = MaterialTheme.typography.displaySmall,
            fontWeight = FontWeight.Bold,
            modifier = Modifier.semantics {
                contentDescription = context.getString(
                    R.string.record_duration_content_description,
                )
            },
        )
        if (uiState.liveTranscriptionOffline) {
            BannerCard(
                title = stringResource(R.string.record_live_offline_title),
                body = stringResource(R.string.record_live_offline_body),
                variant = BannerVariant.Warning,
            )
        }
        if (uiState.connectionState is ConnectionState.Reconnecting) {
            val reconnecting = uiState.connectionState as ConnectionState.Reconnecting
            BannerCard(
                title = stringResource(R.string.record_reconnecting),
                body = stringResource(
                    R.string.record_reconnecting_body,
                    reconnecting.attempt,
                    reconnecting.max,
                ),
                variant = BannerVariant.Warning,
            )
        }
        LiveTranscriptView(
            modifier = Modifier.widthIn(max = 560.dp),
            transcript = if (isGuest) "" else uiState.transcript,
            placeholder = if (isGuest) {
                stringResource(R.string.record_guest_locked)
            } else {
                when (uiState.phase) {
                    Phase.Preparing -> stringResource(R.string.record_preparing)
                    Phase.Recording -> stringResource(R.string.record_listening)
                    Phase.Finalizing -> stringResource(R.string.record_saving)
                    Phase.Idle -> stringResource(R.string.record_tap_to_start)
                }
            },
        )
        RecordButton(
            phase = uiState.phase,
            onClick = {
                if (uiState.phase == Phase.Recording) {
                    resolvedViewModel.stopRecording()
                } else {
                    val granted = ContextCompat.checkSelfPermission(
                        context,
                        Manifest.permission.RECORD_AUDIO,
                    ) == PackageManager.PERMISSION_GRANTED
                    if (granted) {
                        resolvedViewModel.startRecording(true, selectedFolderId)
                    } else {
                        permissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
                    }
                }
            },
        )
        Text(
            text = if (isGuest) {
                stringResource(R.string.record_status_caption_guest)
            } else {
                when (uiState.phase) {
                    Phase.Idle -> stringResource(R.string.record_status_caption_idle)
                    Phase.Preparing -> stringResource(R.string.record_status_caption_preparing)
                    Phase.Recording -> stringResource(R.string.record_status_caption_recording)
                    Phase.Finalizing -> stringResource(R.string.record_status_caption_finalizing)
                }
            },
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        val errorMessage = uiState.error
        if (errorMessage != null) {
            BannerCard(
                title = errorMessage,
                body = null,
                variant = BannerVariant.Error,
            )
            Button(
                onClick = {
                    context.startActivity(
                        Intent(
                            Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                            Uri.fromParts("package", context.packageName, null),
                        ),
                    )
                },
            ) {
                Text(stringResource(R.string.record_enable_mic))
            }
        }
    }

    if (showFolderPicker) {
        AlertDialog(
            onDismissRequest = { showFolderPicker = false },
            title = { Text(stringResource(R.string.record_folder)) },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    TextButton(
                        onClick = {
                            selectedFolderId = null
                            showFolderPicker = false
                        },
                    ) {
                        Text(stringResource(R.string.record_folder_none))
                    }
                    folders.forEach { folder ->
                        TextButton(
                            onClick = {
                                selectedFolderId = folder.id
                                showFolderPicker = false
                            },
                        ) {
                            Text(folder.name)
                        }
                    }
                }
            },
            confirmButton = {},
            dismissButton = {
                TextButton(onClick = { showFolderPicker = false }) {
                    Text(stringResource(R.string.common_cancel))
                }
            },
        )
    }
}

private fun formatDuration(durationSeconds: Long): String {
    val minutes = durationSeconds / 60
    val seconds = durationSeconds % 60
    return "%02d:%02d".format(minutes, seconds)
}
