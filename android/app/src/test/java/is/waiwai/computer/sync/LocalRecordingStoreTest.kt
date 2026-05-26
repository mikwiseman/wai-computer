package `is`.waiwai.computer.sync

import android.content.Context
import `is`.waiwai.computer.data.LiveTranscriptSegment
import io.mockk.every
import io.mockk.mockk
import kotlin.io.path.createTempDirectory
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class LocalRecordingStoreTest {
    @Test
    fun `save list and remove roundtrip`() = runTest {
        val tempRoot = createTempDirectory("waicomputer-local-store").toFile()
        val context = mockk<Context>()
        every { context.filesDir } returns tempRoot

        val store = LocalRecordingStore(context)
        store.save(
            manifest = LocalRecordingManifest(
                recordingId = "rec-1",
                title = "Local note",
                durationSeconds = 42,
                hasAudioFile = true,
                localOnly = true,
            ),
            segments = listOf(
                LiveTranscriptSegment(text = "hello", isFinal = true, startMs = 0, endMs = 500),
            ),
        )

        val manifests = store.listPending()
        assertEquals(1, manifests.size)
        assertEquals("rec-1", manifests.first().recordingId)
        assertTrue(store.audioFile("rec-1").parentFile?.exists() == true)
        assertEquals(1, store.loadSegments("rec-1").size)

        store.remove("rec-1")
        assertNull(store.manifest("rec-1"))
    }

    @Test
    fun `server id is persisted before retryable upload work`() = runTest {
        val tempRoot = createTempDirectory("waicomputer-local-store").toFile()
        val context = mockk<Context>()
        every { context.filesDir } returns tempRoot

        val store = LocalRecordingStore(context)
        store.save(LocalRecordingManifest(recordingId = "rec-2", title = "Retry me"))

        val updated = store.recordServerRecordingId("rec-2", "server-2")

        assertEquals("server-2", updated?.serverRecordingId)
        assertEquals("server-2", store.manifest("rec-2")?.serverRecordingId)
        assertEquals("server-2", store.listPending().single().serverRecordingId)
    }

    @Test
    fun `repeated sync failures move recording out of pending queue`() = runTest {
        val tempRoot = createTempDirectory("waicomputer-local-store").toFile()
        val context = mockk<Context>()
        every { context.filesDir } returns tempRoot

        val store = LocalRecordingStore(context)
        store.save(LocalRecordingManifest(recordingId = "rec-3", title = "Poison item"))

        repeat(5) {
            store.recordSyncFailure("rec-3", "upload failed")
        }

        val manifest = store.manifest("rec-3")
        assertEquals(5, manifest?.syncFailureCount)
        assertEquals("upload failed", manifest?.failureMessage)
        assertTrue(manifest?.syncDeadLetteredAtEpochMillis != null)
        assertTrue(store.listPending().isEmpty())
    }
}
