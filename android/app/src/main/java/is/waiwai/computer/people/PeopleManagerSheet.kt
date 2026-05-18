package `is`.waiwai.computer.people

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Delete
import androidx.compose.material.icons.outlined.Edit
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import `is`.waiwai.computer.R
import `is`.waiwai.computer.data.Person
import `is`.waiwai.computer.ui.TestTags
import `is`.waiwai.computer.ui.components.BannerCard
import `is`.waiwai.computer.ui.components.BannerVariant
import `is`.waiwai.computer.ui.components.EmptyState

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PeopleManagerSheet(
    viewModel: PeopleManagerViewModel,
    onDismiss: () -> Unit,
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val uiState by viewModel.uiState.collectAsState()
    var renamingPerson by remember { mutableStateOf<Person?>(null) }
    var renameDraft by remember { mutableStateOf("") }
    var deletingPerson by remember { mutableStateOf<Person?>(null) }

    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = sheetState,
        modifier = Modifier.testTag(TestTags.SpeakersSheet),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 24.dp, vertical = 16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(
                text = stringResource(R.string.settings_speakers),
                style = MaterialTheme.typography.headlineSmall,
                fontWeight = FontWeight.SemiBold,
            )
            Text(
                text = stringResource(R.string.settings_speakers_subtitle),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )

            if (uiState.error != null) {
                BannerCard(
                    title = uiState.error.orEmpty(),
                    body = null,
                    variant = BannerVariant.Error,
                )
            }

            when {
                uiState.isLoading -> {
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.Center,
                    ) {
                        CircularProgressIndicator()
                    }
                }
                uiState.people.isEmpty() -> {
                    EmptyState(
                        title = stringResource(R.string.speakers_empty_title),
                        body = stringResource(R.string.speakers_empty_body),
                        actionLabel = null,
                        onAction = null,
                    )
                }
                else -> {
                    LazyColumn(
                        modifier = Modifier
                            .fillMaxWidth()
                            .heightIn(max = 360.dp),
                        verticalArrangement = Arrangement.spacedBy(4.dp),
                    ) {
                        items(uiState.people, key = { it.id }) { person ->
                            PersonRow(
                                person = person,
                                isPending = uiState.pendingActionId == person.id,
                                onRename = {
                                    renamingPerson = person
                                    renameDraft = person.displayName
                                },
                                onDelete = { deletingPerson = person },
                            )
                        }
                    }
                }
            }

            TextButton(onClick = onDismiss, modifier = Modifier.fillMaxWidth()) {
                Text(stringResource(R.string.common_done))
            }
        }
    }

    if (renamingPerson != null) {
        AlertDialog(
            onDismissRequest = { renamingPerson = null },
            title = { Text(stringResource(R.string.speakers_rename_title)) },
            text = {
                OutlinedTextField(
                    value = renameDraft,
                    onValueChange = { renameDraft = it },
                    modifier = Modifier.fillMaxWidth(),
                    singleLine = true,
                )
            },
            confirmButton = {
                TextButton(
                    enabled = renameDraft.isNotBlank(),
                    onClick = {
                        renamingPerson?.let { viewModel.rename(it.id, renameDraft) }
                        renamingPerson = null
                    },
                ) {
                    Text(stringResource(R.string.common_save))
                }
            },
            dismissButton = {
                TextButton(onClick = { renamingPerson = null }) {
                    Text(stringResource(R.string.common_cancel))
                }
            },
        )
    }

    if (deletingPerson != null) {
        AlertDialog(
            onDismissRequest = { deletingPerson = null },
            title = { Text(stringResource(R.string.speakers_delete_confirm_title)) },
            text = { Text(stringResource(R.string.speakers_delete_confirm_body)) },
            confirmButton = {
                TextButton(onClick = {
                    deletingPerson?.let { viewModel.delete(it.id) }
                    deletingPerson = null
                }) {
                    Text(
                        text = stringResource(R.string.library_delete),
                        color = MaterialTheme.colorScheme.error,
                    )
                }
            },
            dismissButton = {
                TextButton(onClick = { deletingPerson = null }) {
                    Text(stringResource(R.string.common_cancel))
                }
            },
        )
    }
}

@Composable
private fun PersonRow(
    person: Person,
    isPending: Boolean,
    onRename: () -> Unit,
    onDelete: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 4.dp)
            .testTag(TestTags.speakerItem(person.id)),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(text = person.displayName)
            Text(
                text = stringResource(R.string.speakers_voiceprints, person.voiceprintCount),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        if (isPending) {
            CircularProgressIndicator(modifier = Modifier.padding(end = 8.dp))
        }
        IconButton(onClick = onRename) {
            Icon(Icons.Outlined.Edit, contentDescription = stringResource(R.string.folders_rename))
        }
        IconButton(onClick = onDelete) {
            Icon(
                Icons.Outlined.Delete,
                contentDescription = stringResource(R.string.library_delete),
                tint = MaterialTheme.colorScheme.error,
            )
        }
    }
}
