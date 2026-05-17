package `is`.waiwai.computer.ui

import android.text.format.DateUtils
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import `is`.waiwai.computer.R
import `is`.waiwai.computer.data.ActionItemPriority
import `is`.waiwai.computer.data.ActionItemStatus
import `is`.waiwai.computer.data.RecordingStatus
import `is`.waiwai.computer.data.RecordingType
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.format.FormatStyle

@Composable
fun recordingTypeLabel(type: RecordingType): String = when (type) {
    RecordingType.meeting -> stringResource(R.string.recording_type_meeting)
    RecordingType.note -> stringResource(R.string.recording_type_note)
    RecordingType.reflection -> stringResource(R.string.recording_type_reflection)
}

@Composable
fun recordingStatusLabel(status: RecordingStatus): String = when (status) {
    RecordingStatus.Ready -> stringResource(R.string.status_ready)
    RecordingStatus.Processing -> stringResource(R.string.status_processing)
    RecordingStatus.PendingUpload -> stringResource(R.string.status_pending_upload)
    RecordingStatus.Uploading -> stringResource(R.string.status_uploading)
    RecordingStatus.Failed -> stringResource(R.string.status_failed)
}

@Composable
fun actionStatusLabel(status: ActionItemStatus): String = when (status) {
    ActionItemStatus.Pending -> stringResource(R.string.action_status_pending)
    ActionItemStatus.InProgress -> stringResource(R.string.action_status_in_progress)
    ActionItemStatus.Completed -> stringResource(R.string.action_status_completed)
    ActionItemStatus.Cancelled -> stringResource(R.string.action_status_cancelled)
}

@Composable
fun priorityLabel(priority: ActionItemPriority?): String = when (priority) {
    ActionItemPriority.high -> stringResource(R.string.priority_high)
    ActionItemPriority.medium -> stringResource(R.string.priority_medium)
    ActionItemPriority.low -> stringResource(R.string.priority_low)
    null -> stringResource(R.string.detail_none)
}

fun formatDuration(durationSeconds: Long): String {
    val minutes = durationSeconds / 60
    val seconds = durationSeconds % 60
    return "%02d:%02d".format(minutes, seconds)
}

fun formatRelativeTime(isoInstant: String?): String {
    val instant = runCatching { isoInstant?.let(Instant::parse) }.getOrNull() ?: return isoInstant.orEmpty()
    return DateUtils.getRelativeTimeSpanString(
        instant.toEpochMilli(),
        System.currentTimeMillis(),
        DateUtils.MINUTE_IN_MILLIS,
        DateUtils.FORMAT_ABBREV_RELATIVE,
    ).toString()
}

fun formatDateTime(isoInstant: String?): String {
    val instant = runCatching { isoInstant?.let(Instant::parse) }.getOrNull() ?: return isoInstant.orEmpty()
    return DateTimeFormatter.ofLocalizedDateTime(FormatStyle.MEDIUM)
        .withZone(ZoneId.systemDefault())
        .format(instant)
}
