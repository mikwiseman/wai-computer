package `is`.waiwai.computer.recording

import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class AudioCompressorTest {

    private fun writeWav(file: File, sampleRate: Int, channels: Int, dataBytes: Int) {
        val header = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN)
        header.put("RIFF".toByteArray())
        header.putInt(36 + dataBytes)
        header.put("WAVE".toByteArray())
        header.put("fmt ".toByteArray())
        header.putInt(16)
        header.putShort(1)
        header.putShort(channels.toShort())
        header.putInt(sampleRate)
        header.putInt(sampleRate * channels * 2)
        header.putShort((channels * 2).toShort())
        header.putShort(16)
        header.put("data".toByteArray())
        header.putInt(dataBytes)
        file.writeBytes(header.array() + ByteArray(dataBytes))
    }

    @Test
    fun isWav_trueForRiffWave() {
        val f = File.createTempFile("rec", ".wav").apply { deleteOnExit() }
        writeWav(f, 16_000, 1, 320)
        assertTrue(AudioCompressor.isWav(f))
    }

    @Test
    fun isWav_falseForNonWav() {
        val f = File.createTempFile("clip", ".bin").apply { deleteOnExit() }
        f.writeBytes("ID3 not a wav at all".toByteArray())
        assertFalse(AudioCompressor.isWav(f))
    }

    @Test
    fun readWavFormat_parsesCanonicalMonoHeader() {
        val f = File.createTempFile("rec", ".wav").apply { deleteOnExit() }
        writeWav(f, 16_000, 1, 32_000) // 1 s of 16 kHz mono int16
        val fmt = AudioCompressor.readWavFormat(f)
        assertEquals(16_000, fmt.sampleRate)
        assertEquals(1, fmt.channels)
        assertEquals(44L, fmt.dataOffset)
        assertEquals(32_000L, fmt.dataLength)
    }

    @Test
    fun readWavFormat_parsesStereoHeader() {
        val f = File.createTempFile("rec", ".wav").apply { deleteOnExit() }
        writeWav(f, 48_000, 2, 9600)
        val fmt = AudioCompressor.readWavFormat(f)
        assertEquals(48_000, fmt.sampleRate)
        assertEquals(2, fmt.channels)
        assertEquals(9600L, fmt.dataLength)
    }

    @Test
    fun readWavFormat_throwsOnNonRiff() {
        val f = File.createTempFile("bad", ".wav").apply { deleteOnExit() }
        f.writeBytes(ByteArray(64))
        assertThrows(IllegalArgumentException::class.java) {
            AudioCompressor.readWavFormat(f)
        }
    }
}
