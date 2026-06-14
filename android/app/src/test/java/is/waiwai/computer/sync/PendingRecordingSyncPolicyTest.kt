package `is`.waiwai.computer.sync

import `is`.waiwai.computer.data.RecordingDetail
import `is`.waiwai.computer.data.RecordingStatus
import java.time.Instant
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class PendingRecordingSyncPolicyTest {
    @Test
    fun `accepted server statuses can remove local payload`() {
        assertNull(PendingRecordingSyncPolicy.failureMessage(detail(RecordingStatus.Processing)))
        assertNull(PendingRecordingSyncPolicy.failureMessage(detail(RecordingStatus.Ready)))
    }

    @Test
    fun `failed server status keeps local payload`() {
        assertEquals(
            "Unsupported codec",
            PendingRecordingSyncPolicy.failureMessage(
                detail(RecordingStatus.Failed, failureMessage = "Unsupported codec"),
            ),
        )
    }

    @Test
    fun `failed server status without message gets stable local error`() {
        assertEquals(
            "Server rejected pending recording sync.",
            PendingRecordingSyncPolicy.failureMessage(detail(RecordingStatus.Failed)),
        )
    }

    private fun detail(
        status: RecordingStatus,
        failureMessage: String? = null,
    ) = RecordingDetail(
        id = "rec-1",
        status = status,
        failureMessage = failureMessage,
        createdAt = Instant.now().toString(),
    )
}
