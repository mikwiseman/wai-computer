package `is`.waiwai.computer.recording

import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class AudioFileWriterTest {
    @Test
    fun `finalize writes wav header with data size`() = runTest {
        val file = File.createTempFile("audio-writer", ".wav")
        val writer = AudioFileWriter(file)
        writer.write(shortArrayOf(1, 2, 3, 4))
        writer.finalizeFile()

        val bytes = file.readBytes()
        assertEquals("RIFF", String(bytes.copyOfRange(0, 4)))
        assertEquals("WAVE", String(bytes.copyOfRange(8, 12)))

        val header = ByteBuffer.wrap(bytes, 40, 4).order(ByteOrder.LITTLE_ENDIAN)
        assertEquals(8, header.int)
        assertTrue(bytes.size >= 52)
    }
}
