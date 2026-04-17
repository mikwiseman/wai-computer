package `is`.waiwai.say.library

import android.content.Intent
import android.media.MediaPlayer
import android.net.Uri
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.ArrowBack
import androidx.compose.material.icons.outlined.ExpandLess
import androidx.compose.material.icons.outlined.ExpandMore
import androidx.compose.material.icons.outlined.MoreVert
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import `is`.waiwai.say.R
import `is`.waiwai.say.data.ActionItem
import `is`.waiwai.say.data.RecordingDetail
import `is`.waiwai.say.data.RecordingHighlight
import `is`.waiwai.say.data.RecordingStatus
import `is`.waiwai.say.data.Segment
import `is`.waiwai.say.sync.LocalRecordingManifest
import `is`.waiwai.say.ui.actionStatusLabel
import `is`.waiwai.say.ui.formatDateTime
import `is`.waiwai.say.ui.formatDuration
import `is`.waiwai.say.ui.priorityLabel
import `is`.waiwai.say.ui.recordingStatusLabel
import `is`.waiwai.say.ui.recordingTypeLabel
import `is`.waiwai.say.ui.components.BannerCard
import `is`.waiwai.say.ui.components.BannerVariant

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun RecordingDetailScreen(
    modifier: Modifier = Modifier,
    viewModel: RecordingDetailViewModel,
    isGuest: Boolean,
    onBack: () -> Unit,
    onRequestSignIn: () -> Unit,
) {
    val uiState by viewModel.uiState.collectAsState()
    val detail = uiState.detail
    val localManifest = uiState.localManifest
    val context = LocalContext.current

    var editableTitle by rememberSaveable(detail?.title, localManifest?.title) {
        mutableStateOf(detail?.title ?: localManifest?.title.orEmpty())
    }
    var showOverflow by remember { mutableStateOf(false) }
    var showMoveDialog by remember { mutableStateOf(false) }
    var showDeleteDialog by remember { mutableStateOf(false) }
    var mediaPlayer by remember { mutableStateOf<MediaPlayer?>(null) }
    var isPlaying by remember { mutableStateOf(false) }

    DisposableEffect(Unit) {
        onDispose {
            mediaPlayer?.release()
        }
    }

    Scaffold(
        modifier = modifier,
        topBar = {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 12.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    IconButton(onClick = onBack) {
                        Icon(Icons.Outlined.ArrowBack, contentDescription = stringResource(R.string.common_back))
                    }
                    Text(
                        text = editableTitle.ifBlank { stringResource(R.string.detail_untitled) },
                        style = MaterialTheme.typography.titleLarge,
                        fontWeight = FontWeight.SemiBold,
                    )
                }
                if (detail != null || localManifest != null) {
                    Row {
                        IconButton(onClick = { showOverflow = true }) {
                            Icon(Icons.Outlined.MoreVert, contentDescription = stringResource(R.string.common_close))
                        }
                        DropdownMenu(
                            expanded = showOverflow,
                            onDismissRequest = { showOverflow = false },
                        ) {
                            DropdownMenuItem(
                                text = { Text(stringResource(R.string.detail_share)) },
                                onClick = {
                                    showOverflow = false
                                    shareRecording(context, detail, localManifest)
                                },
                            )
                            if (detail != null) {
                                DropdownMenuItem(
                                    text = { Text(stringResource(R.string.detail_move)) },
                                    onClick = {
                                        showOverflow = false
                                        showMoveDialog = true
                                    },
                                )
                            }
                            DropdownMenuItem(
                                text = { Text(stringResource(R.string.library_delete)) },
                                onClick = {
                                    showOverflow = false
                                    showDeleteDialog = true
                                },
                            )
                        }
                    }
                }
            }
        },
    ) { padding ->
        when {
            uiState.isLoading -> {
                Row(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(padding),
                    horizontalArrangement = Arrangement.Center,
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    CircularProgressIndicator()
                }
            }
            uiState.error != null -> {
                Column(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(padding)
                        .padding(24.dp),
                ) {
                    BannerCard(
                        title = uiState.error.orEmpty(),
                        body = null,
                        variant = BannerVariant.Error,
                    )
                }
            }
            localManifest != null && (detail == null || isGuest) -> {
                LocalRecordingDetailContent(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(padding)
                        .padding(horizontal = 24.dp),
                    manifest = localManifest,
                    audioAvailable = viewModel.audioFile() != null,
                    isPlaying = isPlaying,
                    onTogglePlayback = {
                        val audioFile = viewModel.audioFile() ?: return@LocalRecordingDetailContent
                        if (isPlaying) {
                            mediaPlayer?.pause()
                            isPlaying = false
                        } else {
                            val player = mediaPlayer ?: MediaPlayer().also { created ->
                                created.setDataSource(context, Uri.fromFile(audioFile))
                                created.prepare()
                                created.setOnCompletionListener {
                                    isPlaying = false
                                }
                                mediaPlayer = created
                            }
                            player.start()
                            isPlaying = true
                        }
                    },
                    onRequestSignIn = onRequestSignIn,
                )
            }
            detail != null -> {
                AuthenticatedRecordingDetailContent(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(padding)
                        .padding(horizontal = 24.dp),
                    detail = detail,
                    localManifest = localManifest,
                    editableTitle = editableTitle,
                    isRetryingUpload = uiState.isRetryingUpload,
                    onTitleChange = { editableTitle = it },
                    onSaveTitle = { viewModel.updateTitle(editableTitle) },
                    onToggleActionItem = viewModel::toggleActionItem,
                    onRetryUpload = viewModel::retryUpload,
                )
            }
        }
    }

    if (showMoveDialog && detail != null) {
        AlertDialog(
            onDismissRequest = { showMoveDialog = false },
            title = { Text(stringResource(R.string.detail_move_title)) },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    TextButton(
                        onClick = {
                            viewModel.moveToFolder(null)
                            showMoveDialog = false
                        },
                    ) {
                        Text(stringResource(R.string.record_folder_none))
                    }
                    uiState.folders.forEach { folder ->
                        TextButton(
                            onClick = {
                                viewModel.moveToFolder(folder.id)
                                showMoveDialog = false
                            },
                        ) {
                            Text(folder.name)
                        }
                    }
                }
            },
            confirmButton = {},
            dismissButton = {
                TextButton(onClick = { showMoveDialog = false }) {
                    Text(stringResource(R.string.common_cancel))
                }
            },
        )
    }

    if (showDeleteDialog) {
        AlertDialog(
            onDismissRequest = { showDeleteDialog = false },
            title = { Text(stringResource(R.string.library_delete_confirm_title)) },
            text = { Text(stringResource(R.string.detail_delete_confirm_body)) },
            confirmButton = {
                TextButton(
                    onClick = {
                        viewModel.deleteRecording(onBack)
                        showDeleteDialog = false
                    },
                ) {
                    Text(stringResource(R.string.library_delete))
                }
            },
            dismissButton = {
                TextButton(onClick = { showDeleteDialog = false }) {
                    Text(stringResource(R.string.common_cancel))
                }
            },
        )
    }
}

@Composable
private fun LocalRecordingDetailContent(
    modifier: Modifier,
    manifest: LocalRecordingManifest,
    audioAvailable: Boolean,
    isPlaying: Boolean,
    onTogglePlayback: () -> Unit,
    onRequestSignIn: () -> Unit,
) {
    LazyColumn(
        modifier = modifier.widthIn(max = 560.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        item {
            BannerCard(
                title = stringResource(R.string.library_local_only),
                body = stringResource(R.string.record_guest_locked),
                variant = BannerVariant.Info,
            )
        }
        item {
            ExpandableSectionCard(
                title = stringResource(R.string.detail_summary),
                initiallyExpanded = true,
            ) {
                Text(
                    text = manifest.title ?: stringResource(R.string.detail_untitled),
                    style = MaterialTheme.typography.titleLarge,
                    fontWeight = FontWeight.SemiBold,
                )
                Text("${stringResource(R.string.detail_duration)}: ${formatDuration(manifest.durationSeconds)}")
                Text("${stringResource(R.string.detail_created_at)}: ${formatDateTime(java.time.Instant.ofEpochMilli(manifest.createdAtEpochMillis).toString())}")
                if (audioAvailable) {
                    Button(onClick = onTogglePlayback) {
                        Text(
                            if (isPlaying) {
                                stringResource(R.string.detail_pause_audio)
                            } else {
                                stringResource(R.string.detail_play_audio)
                            },
                        )
                    }
                }
                Button(onClick = onRequestSignIn, modifier = Modifier.fillMaxWidth()) {
                    Text(stringResource(R.string.detail_sign_in_to_transcribe))
                }
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun AuthenticatedRecordingDetailContent(
    modifier: Modifier,
    detail: RecordingDetail,
    localManifest: LocalRecordingManifest?,
    editableTitle: String,
    isRetryingUpload: Boolean,
    onTitleChange: (String) -> Unit,
    onSaveTitle: () -> Unit,
    onToggleActionItem: (String, `is`.waiwai.say.data.ActionItemStatus) -> Unit,
    onRetryUpload: () -> Unit,
) {
    LazyColumn(
        modifier = modifier.widthIn(max = 560.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        item {
            Column(
                modifier = Modifier.padding(top = 8.dp, bottom = 4.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                if (detail.status == RecordingStatus.Processing) {
                    BannerCard(
                        title = stringResource(R.string.detail_processing),
                        body = stringResource(R.string.detail_processing_body),
                        variant = BannerVariant.Warning,
                    )
                }
                if (detail.status == RecordingStatus.Failed) {
                    BannerCard(
                        title = detail.failureMessage ?: stringResource(R.string.detail_failed_message),
                        body = localManifest?.failureMessage,
                        variant = BannerVariant.Error,
                    )
                    if (localManifest != null) {
                        Button(onClick = onRetryUpload, enabled = !isRetryingUpload) {
                            Text(
                                if (isRetryingUpload) {
                                    stringResource(R.string.detail_processing)
                                } else {
                                    stringResource(R.string.detail_failed_retry)
                                },
                            )
                        }
                    }
                }
            }
        }
        item {
            ExpandableSectionCard(title = stringResource(R.string.detail_title), initiallyExpanded = true) {
                OutlinedTextField(
                    value = editableTitle,
                    onValueChange = onTitleChange,
                    modifier = Modifier.fillMaxWidth(),
                    label = { Text(stringResource(R.string.detail_title)) },
                )
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Button(onClick = onSaveTitle) {
                        Text(stringResource(R.string.common_save))
                    }
                    AssistChip(
                        onClick = {},
                        label = { Text(recordingTypeLabel(detail.type)) },
                    )
                    AssistChip(
                        onClick = {},
                        label = { Text(recordingStatusLabel(detail.status)) },
                    )
                }
                Text("${stringResource(R.string.detail_duration)}: ${formatDuration(detail.durationSeconds?.toLong() ?: 0L)}")
                Text("${stringResource(R.string.detail_created_at)}: ${formatDateTime(detail.createdAt)}")
            }
        }
        item {
            ExpandableSectionCard(title = stringResource(R.string.detail_transcript), initiallyExpanded = true) {
                TranscriptSection(detail.segments)
            }
        }
        item {
            ExpandableSectionCard(title = stringResource(R.string.detail_summary), initiallyExpanded = true) {
                SummarySection(detail)
            }
        }
        item {
            ExpandableSectionCard(title = stringResource(R.string.detail_action_items), initiallyExpanded = true) {
                ActionItemsSection(detail.actionItems, onToggleActionItem)
            }
        }
        item {
            ExpandableSectionCard(title = stringResource(R.string.detail_highlights), initiallyExpanded = true) {
                HighlightsSection(detail.highlights)
            }
        }
    }
}

@Composable
private fun ExpandableSectionCard(
    title: String,
    initiallyExpanded: Boolean,
    content: @Composable ColumnScope.() -> Unit,
) {
    var expanded by rememberSaveable(title) { mutableStateOf(initiallyExpanded) }
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clickable { expanded = !expanded },
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = title,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.SemiBold,
                )
                Icon(
                    imageVector = if (expanded) Icons.Outlined.ExpandLess else Icons.Outlined.ExpandMore,
                    contentDescription = null,
                )
            }
            if (expanded) {
                HorizontalDivider()
                Column(verticalArrangement = Arrangement.spacedBy(12.dp), content = content)
            }
        }
    }
}

@Composable
private fun TranscriptSection(segments: List<Segment>) {
    if (segments.isEmpty()) {
        Text(stringResource(R.string.detail_no_transcript))
        return
    }
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        segments.forEach { segment ->
            Card {
                Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(
                        text = segment.speaker ?: stringResource(R.string.detail_speaker),
                        style = MaterialTheme.typography.labelLarge,
                        fontWeight = FontWeight.SemiBold,
                    )
                    Text(text = segment.content)
                }
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun SummarySection(detail: RecordingDetail) {
    val summary = detail.summary
    if (summary == null) {
        Text(stringResource(R.string.detail_no_summary))
        return
    }
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text(summary.summary ?: stringResource(R.string.detail_no_summary))
        summary.keyPoints.orEmpty().forEach { point ->
            Text("• $point")
        }
        if (summary.topics.orEmpty().isNotEmpty()) {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                summary.topics.orEmpty().forEach { topic ->
                    AssistChip(onClick = {}, label = { Text(topic) })
                }
            }
        }
        if (summary.peopleMentioned.orEmpty().isNotEmpty()) {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                summary.peopleMentioned.orEmpty().forEach { person ->
                    AssistChip(onClick = {}, label = { Text(person) })
                }
            }
        }
        summary.decisions.orEmpty().forEach { decision ->
            Card {
                Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(decision.decision, fontWeight = FontWeight.SemiBold)
                    if (!decision.context.isNullOrBlank()) {
                        Text(decision.context)
                    }
                }
            }
        }
    }
}

@Composable
private fun ActionItemsSection(
    items: List<ActionItem>,
    onToggleActionItem: (String, `is`.waiwai.say.data.ActionItemStatus) -> Unit,
) {
    if (items.isEmpty()) {
        Text(stringResource(R.string.detail_no_action_items))
        return
    }
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        items.forEach { item ->
            Card {
                Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(item.task, fontWeight = FontWeight.SemiBold)
                    Text("${stringResource(R.string.detail_owner)}: ${item.owner ?: stringResource(R.string.detail_unassigned)}")
                    Text("${stringResource(R.string.detail_due_date)}: ${item.dueDate ?: stringResource(R.string.detail_none)}")
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.SpaceBetween,
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column {
                            Text("${stringResource(R.string.detail_priority)}: ${priorityLabel(item.priority)}")
                            Text(actionStatusLabel(item.status))
                        }
                        Switch(
                            checked = item.status == `is`.waiwai.say.data.ActionItemStatus.Completed,
                            onCheckedChange = { onToggleActionItem(item.id, item.status) },
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun HighlightsSection(highlights: List<RecordingHighlight>) {
    if (highlights.isEmpty()) {
        Text(stringResource(R.string.detail_no_highlights))
        return
    }
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        highlights.forEach { highlight ->
            Card {
                Column(modifier = Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(highlight.title, fontWeight = FontWeight.SemiBold)
                    Text(highlight.category, color = MaterialTheme.colorScheme.primary)
                    if (!highlight.description.isNullOrBlank()) {
                        Text(highlight.description)
                    }
                }
            }
        }
    }
}

private fun shareRecording(
    context: android.content.Context,
    detail: RecordingDetail?,
    localManifest: LocalRecordingManifest?,
) {
    val text = buildString {
        if (detail != null) {
            appendLine(detail.title ?: context.getString(R.string.app_name))
            appendLine()
            detail.summary?.summary?.let {
                appendLine(it)
                appendLine()
            }
            detail.segments.forEach { segment ->
                appendLine("${segment.speaker ?: context.getString(R.string.detail_speaker)}: ${segment.content}")
            }
        } else if (localManifest != null) {
            appendLine(localManifest.title ?: context.getString(R.string.app_name))
            appendLine()
            appendLine(context.getString(R.string.detail_local_recording))
            localManifest.transcript?.let {
                appendLine()
                appendLine(it)
            }
        }
    }.trim()

    if (text.isBlank()) return
    context.startActivity(
        Intent.createChooser(
            Intent(Intent.ACTION_SEND).apply {
                type = "text/plain"
                putExtra(Intent.EXTRA_SUBJECT, context.getString(R.string.detail_share_subject))
                putExtra(Intent.EXTRA_TEXT, text)
            },
            null,
        ),
    )
}
