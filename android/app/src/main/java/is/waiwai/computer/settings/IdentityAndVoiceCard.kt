package `is`.waiwai.computer.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import `is`.waiwai.computer.auth.AuthState
import `is`.waiwai.computer.data.AppContainer
import `is`.waiwai.computer.data.UpdateIdentityRequest
import `is`.waiwai.computer.data.UserIdentity
import `is`.waiwai.computer.data.VoiceSharingState
import kotlinx.coroutines.launch

/// Settings card for the user's public identity and the voice-sharing
/// directory toggle. Mirrors the macOS / iOS / web sections so that flipping
/// the toggle on requires confirmation that surfaces exactly what is shared.
@Composable
fun IdentityAndVoiceCard(
    container: AppContainer,
    authState: AuthState,
) {
    if (authState !is AuthState.Authenticated) {
        return
    }

    val scope = rememberCoroutineScope()
    var identity by remember { mutableStateOf<UserIdentity?>(null) }
    var sharing by remember { mutableStateOf<VoiceSharingState?>(null) }
    var firstName by remember { mutableStateOf("") }
    var lastName by remember { mutableStateOf("") }
    var error by remember { mutableStateOf<String?>(null) }
    var saving by remember { mutableStateOf(false) }
    var toggling by remember { mutableStateOf(false) }
    var showConfirm by remember { mutableStateOf(false) }

    suspend fun loadAll() {
        try {
            identity = container.waiApi.getIdentity()
            firstName = identity?.firstName.orEmpty()
            lastName = identity?.lastName.orEmpty()
            sharing = container.waiApi.getVoiceSharing()
            error = null
        } catch (cause: Throwable) {
            error = cause.localizedMessage ?: "Couldn't load identity settings."
        }
    }

    LaunchedEffect(authState) {
        loadAll()
    }

    fun saveNames() {
        if (saving) return
        saving = true
        scope.launch {
            try {
                identity = container.waiApi.updateIdentity(
                    UpdateIdentityRequest(firstName = firstName, lastName = lastName),
                )
                firstName = identity?.firstName.orEmpty()
                lastName = identity?.lastName.orEmpty()
                sharing = container.waiApi.getVoiceSharing()
                error = null
            } catch (cause: Throwable) {
                error = cause.localizedMessage ?: "Couldn't save your name."
            } finally {
                saving = false
            }
        }
    }

    fun flipSharing(enabled: Boolean) {
        if (toggling) return
        toggling = true
        scope.launch {
            try {
                sharing = if (enabled) {
                    container.waiApi.enableVoiceSharing()
                } else {
                    container.waiApi.disableVoiceSharing()
                }
                error = null
            } catch (cause: Throwable) {
                error = cause.localizedMessage
                    ?: if (enabled) "Couldn't turn on voice sharing." else "Couldn't turn off voice sharing."
            } finally {
                toggling = false
            }
        }
    }

    val state = sharing
    val canToggle = state?.canEnable == true
    val isOn = state?.enabled == true

    val previewName = listOf(firstName, lastName)
        .map { it.trim() }
        .filter { it.isNotEmpty() }
        .joinToString(" ")
        .ifEmpty { "your name" }

    Column(verticalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.fillMaxWidth()) {
        Text(
            text = "Used as your display name in other users' recordings when sharing is on.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )

        OutlinedTextField(
            value = firstName,
            onValueChange = { firstName = it },
            label = { Text("First name") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        OutlinedTextField(
            value = lastName,
            onValueChange = { lastName = it },
            label = { Text("Last name") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        TextButton(
            onClick = { saveNames() },
            enabled = !saving,
        ) {
            Text(if (saving) "Saving…" else "Save name")
        }

        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text(
                text = "Share my voice in the WaiComputer directory",
                modifier = Modifier.weight(1f),
            )
            Switch(
                checked = isOn,
                enabled = (canToggle || isOn) && !toggling,
                onCheckedChange = { newValue ->
                    if (newValue) {
                        showConfirm = true
                    } else {
                        flipSharing(false)
                    }
                },
            )
        }

        val subtitle = when {
            state == null -> ""
            state.enabled -> state.sharedName?.let { "Visible to others as \"$it\"." } ?: "On."
            state.canEnable -> "Off. Other users will not see your name in their recordings."
            !state.hasVoiceprint && (!state.hasFirstName || !state.hasLastName) ->
                "Add a first and last name AND enroll your voice to enable sharing."
            !state.hasVoiceprint -> "Enroll your voice to enable sharing."
            else -> "Add a first and last name to enable sharing."
        }
        if (subtitle.isNotEmpty()) {
            Text(
                text = subtitle,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }

        if (error != null) {
            Text(
                text = error.orEmpty(),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error,
            )
        }
    }

    if (showConfirm) {
        AlertDialog(
            onDismissRequest = { showConfirm = false },
            title = { Text("Share your voice in WaiComputer?") },
            text = {
                Text(
                    "Other WaiComputer users will see \"$previewName\" in their " +
                        "recordings when your voice is detected. We share your name and " +
                        "a voice fingerprint only — never your audio or transcripts. " +
                        "You can turn this off any time.",
                )
            },
            confirmButton = {
                TextButton(onClick = {
                    showConfirm = false
                    flipSharing(true)
                }) {
                    Text("Share")
                }
            },
            dismissButton = {
                TextButton(onClick = { showConfirm = false }) {
                    Text("Cancel")
                }
            },
        )
    }
}
