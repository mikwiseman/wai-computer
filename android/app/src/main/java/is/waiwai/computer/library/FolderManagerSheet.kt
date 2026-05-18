package `is`.waiwai.computer.library

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
import androidx.compose.material3.Button
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
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import `is`.waiwai.computer.R
import `is`.waiwai.computer.data.Folder
import `is`.waiwai.computer.ui.TestTags
import `is`.waiwai.computer.ui.components.BannerCard
import `is`.waiwai.computer.ui.components.BannerVariant
import `is`.waiwai.computer.ui.components.EmptyState

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun FolderManagerSheet(
    viewModel: FolderManagerViewModel,
    onDismiss: () -> Unit,
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val uiState by viewModel.uiState.collectAsState()
    var draftName by rememberSaveable { mutableStateOf("") }
    var renamingFolder by remember { mutableStateOf<Folder?>(null) }
    var renameDraft by remember { mutableStateOf("") }
    var deletingFolder by remember { mutableStateOf<Folder?>(null) }

    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = sheetState,
        modifier = Modifier.testTag(TestTags.FoldersSheet),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 24.dp, vertical = 16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(
                text = stringResource(R.string.settings_folders),
                style = MaterialTheme.typography.headlineSmall,
                fontWeight = FontWeight.SemiBold,
            )
            Text(
                text = stringResource(R.string.settings_folders_subtitle),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )

            if (uiState.error != null) {
                BannerCard(
                    title = uiState.error.orEmpty(),
                    body = null,
                    variant = BannerVariant.Error,
                )
                LaunchedEffect(uiState.error) {
                    // user can re-trigger; auto-clear stale text on next action
                }
            }

            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                OutlinedTextField(
                    value = draftName,
                    onValueChange = { draftName = it },
                    modifier = Modifier
                        .weight(1f)
                        .testTag(TestTags.FoldersNameField),
                    label = { Text(stringResource(R.string.folders_new_placeholder)) },
                    singleLine = true,
                )
                Button(
                    enabled = draftName.isNotBlank(),
                    onClick = {
                        viewModel.create(draftName)
                        draftName = ""
                    },
                    modifier = Modifier.testTag(TestTags.FoldersAddButton),
                ) {
                    Text(stringResource(R.string.folders_add))
                }
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
                uiState.folders.isEmpty() -> {
                    EmptyState(
                        title = stringResource(R.string.folders_empty_title),
                        body = stringResource(R.string.folders_empty_body),
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
                        items(uiState.folders, key = { it.id }) { folder ->
                            FolderRow(
                                folder = folder,
                                isPending = uiState.pendingActionId == folder.id,
                                onRename = {
                                    renamingFolder = folder
                                    renameDraft = folder.name
                                },
                                onDelete = { deletingFolder = folder },
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

    if (renamingFolder != null) {
        AlertDialog(
            onDismissRequest = { renamingFolder = null },
            title = { Text(stringResource(R.string.folders_rename_title)) },
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
                        renamingFolder?.let { viewModel.rename(it.id, renameDraft) }
                        renamingFolder = null
                    },
                ) {
                    Text(stringResource(R.string.common_save))
                }
            },
            dismissButton = {
                TextButton(onClick = { renamingFolder = null }) {
                    Text(stringResource(R.string.common_cancel))
                }
            },
        )
    }

    if (deletingFolder != null) {
        AlertDialog(
            onDismissRequest = { deletingFolder = null },
            title = { Text(stringResource(R.string.folders_delete_confirm_title)) },
            text = { Text(stringResource(R.string.folders_delete_confirm_body)) },
            confirmButton = {
                TextButton(onClick = {
                    deletingFolder?.let { viewModel.delete(it.id) }
                    deletingFolder = null
                }) {
                    Text(
                        text = stringResource(R.string.library_delete),
                        color = MaterialTheme.colorScheme.error,
                    )
                }
            },
            dismissButton = {
                TextButton(onClick = { deletingFolder = null }) {
                    Text(stringResource(R.string.common_cancel))
                }
            },
        )
    }
}

@Composable
private fun FolderRow(
    folder: Folder,
    isPending: Boolean,
    onRename: () -> Unit,
    onDelete: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 4.dp)
            .testTag(TestTags.folderItem(folder.id)),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = folder.name,
            modifier = Modifier.weight(1f),
        )
        if (isPending) {
            CircularProgressIndicator(modifier = Modifier.padding(end = 8.dp))
        }
        IconButton(onClick = onRename) {
            Icon(Icons.Outlined.Edit, contentDescription = stringResource(R.string.folders_rename))
        }
        IconButton(
            onClick = onDelete,
            modifier = Modifier.testTag(TestTags.folderDeleteButton(folder.id)),
        ) {
            Icon(
                Icons.Outlined.Delete,
                contentDescription = stringResource(R.string.library_delete),
                tint = MaterialTheme.colorScheme.error,
            )
        }
    }
}
