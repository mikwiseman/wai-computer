package `is`.waiwai.say.library

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Delete
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SwipeToDismissBox
import androidx.compose.material3.SwipeToDismissBoxValue
import androidx.compose.material3.rememberSwipeToDismissBoxState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import `is`.waiwai.say.R
import `is`.waiwai.say.data.AppContainer
import `is`.waiwai.say.data.RecordingStatus
import `is`.waiwai.say.ui.recordingStatusLabel
import `is`.waiwai.say.ui.recordingTypeLabel
import `is`.waiwai.say.ui.components.BannerCard
import `is`.waiwai.say.ui.components.BannerVariant
import `is`.waiwai.say.ui.components.EmptyState

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LibraryScreen(
    modifier: Modifier = Modifier,
    container: AppContainer,
    isGuest: Boolean,
    onSwitchToRecord: () -> Unit,
    onOpenRecording: (String, Boolean) -> Unit,
) {
    val viewModel = remember(container, isGuest) {
        LibraryViewModel(container.waiApi, container.localRecordingStore, isGuest)
    }
    val uiState by viewModel.uiState.collectAsState()
    var pendingDelete by remember { mutableStateOf<LibraryItemUiModel?>(null) }

    Scaffold(modifier = modifier) { padding ->
        PullToRefreshBox(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding),
            isRefreshing = uiState.isRefreshing,
            onRefresh = viewModel::refresh,
        ) {
            Box(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(horizontal = 24.dp),
                contentAlignment = Alignment.TopCenter,
            ) {
                when {
                    uiState.isLoading -> {
                        CircularProgressIndicator(modifier = Modifier.padding(top = 64.dp))
                    }
                    uiState.items.isEmpty() -> {
                        EmptyState(
                            title = stringResource(R.string.library_empty_title),
                            body = stringResource(R.string.library_empty_body),
                            actionLabel = stringResource(R.string.library_record_cta),
                            onAction = onSwitchToRecord,
                            modifier = Modifier.padding(top = 64.dp),
                        )
                    }
                    else -> {
                        LazyColumn(
                            modifier = Modifier.widthIn(max = 560.dp),
                            verticalArrangement = Arrangement.spacedBy(12.dp),
                        ) {
                            item {
                                Column(
                                    modifier = Modifier.padding(vertical = 24.dp),
                                    verticalArrangement = Arrangement.spacedBy(8.dp),
                                ) {
                                    Text(
                                        text = stringResource(R.string.tab_library),
                                        style = MaterialTheme.typography.headlineMedium,
                                        fontWeight = FontWeight.Bold,
                                    )
                                    Text(
                                        text = stringResource(R.string.library_pull_to_refresh),
                                        style = MaterialTheme.typography.bodyMedium,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                    AnimatedVisibility(visible = uiState.error != null) {
                                        BannerCard(
                                            title = uiState.error.orEmpty(),
                                            body = null,
                                            variant = BannerVariant.Error,
                                        )
                                    }
                                }
                            }
                            items(uiState.items, key = { it.id }) { item ->
                                val dismissState = rememberSwipeToDismissBoxState(
                                    confirmValueChange = { value ->
                                        if (value == SwipeToDismissBoxValue.EndToStart) {
                                            pendingDelete = item
                                            false
                                        } else {
                                            true
                                        }
                                    },
                                )
                                SwipeToDismissBox(
                                    state = dismissState,
                                    backgroundContent = {
                                        DeleteBackground()
                                    },
                                    enableDismissFromStartToEnd = false,
                                    enableDismissFromEndToStart = true,
                                ) {
                                    LibraryItemCard(
                                        item = item,
                                        onClick = { onOpenRecording(item.id, item.localOnly) },
                                    )
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    if (pendingDelete != null) {
        AlertDialog(
            onDismissRequest = { pendingDelete = null },
            title = { Text(stringResource(R.string.library_delete_confirm_title)) },
            text = { Text(stringResource(R.string.library_delete_confirm_body)) },
            confirmButton = {
                TextButton(
                    onClick = {
                        val item = pendingDelete ?: return@TextButton
                        viewModel.delete(item.id, item.localOnly)
                        pendingDelete = null
                    },
                ) {
                    Text(stringResource(R.string.library_delete))
                }
            },
            dismissButton = {
                TextButton(onClick = { pendingDelete = null }) {
                    Text(stringResource(R.string.common_cancel))
                }
            },
        )
    }
}

@Composable
private fun LibraryItemCard(
    item: LibraryItemUiModel,
    onClick: () -> Unit,
) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick),
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.Top,
            ) {
                Column(
                    modifier = Modifier.weight(1f),
                    verticalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    Text(
                        text = item.title ?: stringResource(R.string.detail_untitled),
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = FontWeight.SemiBold,
                    )
                    Text(
                        text = item.relativeTimeLabel,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Text(
                    text = item.durationLabel,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                )
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                AssistChip(
                    onClick = onClick,
                    label = { Text(recordingTypeLabel(item.type)) },
                )
                AssistChip(
                    onClick = onClick,
                    label = {
                        Text(
                            if (item.localOnly) {
                                stringResource(R.string.library_local_only)
                            } else {
                                recordingStatusLabel(item.status)
                            },
                        )
                    },
                )
            }
            if (!item.failureMessage.isNullOrBlank() && item.status == RecordingStatus.Failed) {
                HorizontalDivider()
                Text(
                    text = item.failureMessage,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                )
            }
        }
    }
}

@Composable
private fun DeleteBackground() {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .padding(bottom = 12.dp),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(24.dp),
            horizontalArrangement = Arrangement.End,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(
                imageVector = Icons.Outlined.Delete,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.error,
            )
            Text(
                text = stringResource(R.string.library_delete),
                modifier = Modifier.padding(start = 8.dp),
                color = MaterialTheme.colorScheme.error,
                fontWeight = FontWeight.SemiBold,
            )
        }
    }
}
