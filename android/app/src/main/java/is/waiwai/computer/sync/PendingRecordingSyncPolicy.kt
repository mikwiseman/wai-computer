package `is`.waiwai.computer.sync

import `is`.waiwai.computer.data.RecordingDetail
import `is`.waiwai.computer.data.RecordingStatus

internal object PendingRecordingSyncPolicy {
    fun failureMessage(detail: RecordingDetail): String? {
        detail.failureMessage?.trim()?.takeIf { it.isNotEmpty() }?.let { return it }
        return if (detail.status == RecordingStatus.Failed) {
            "Server rejected pending recording sync."
        } else {
            null
        }
    }
}
