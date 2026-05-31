package `is`.waiwai.computer.recording

import android.media.MediaExtractor
import android.media.MediaFormat
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.sin
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class AudioCompressorInstrumentedTest {

    private val cacheDir: File
        get() = InstrumentationRegistry.getInstrumentation().targetContext.cacheDir

    private fun writeSineWav(name: String, seconds: Double, sampleRate: Int = 16_000, channels: Int = 1): File {
        val frames = (sampleRate * seconds).toInt()
        val pcm = ByteBuffer.allocate(frames * channels * 2).order(ByteOrder.LITTLE_ENDIAN)
        for (n in 0 until frames) {
            val sample = (sin(2.0 * Math.PI * 440.0 * n / sampleRate) * 32767).toInt().toShort()
            repeat(channels) { pcm.putShort(sample) }
        }
        val data = pcm.array()
        val header = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN)
        header.put("RIFF".toByteArray())
        header.putInt(36 + data.size)
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
        header.putInt(data.size)
        return File(cacheDir, name).apply { writeBytes(header.array() + data) }
    }

    @Test
    fun compressWavToM4a_producesSmallerDecodableAac() {
        val src = writeSineWav("compressor-src.wav", seconds = 3.0)
        val dst = File(cacheDir, "compressor-out.m4a")
        try {
            val result = AudioCompressor.compressWavToM4a(src, dst, bitRate = 48_000)

            assertTrue("output exists", dst.exists())
            assertTrue("AAC smaller than raw PCM", dst.length() < src.length())
            assertEquals(3L, result.durationSeconds)

            val extractor = MediaExtractor()
            extractor.setDataSource(dst.absolutePath)
            try {
                assertTrue("has an audio track", extractor.trackCount >= 1)
                val format = extractor.getTrackFormat(0)
                assertEquals(MediaFormat.MIMETYPE_AUDIO_AAC, format.getString(MediaFormat.KEY_MIME))
                assertEquals(16_000, format.getInteger(MediaFormat.KEY_SAMPLE_RATE))
                assertEquals(1, format.getInteger(MediaFormat.KEY_CHANNEL_COUNT))
            } finally {
                extractor.release()
            }
        } finally {
            src.delete()
            dst.delete()
        }
    }
}
