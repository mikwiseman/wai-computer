package `is`.waiwai.say.sync

import android.content.Context
import `is`.waiwai.say.data.LiveTranscriptSegment
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
        val tempRoot = createTempDirectory("waisay-local-store").toFile()
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
}
