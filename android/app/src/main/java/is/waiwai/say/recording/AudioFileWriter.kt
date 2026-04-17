package `is`.waiwai.say.recording

import java.io.File
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

class AudioFileWriter(
    private val file: File,
    private val sampleRate: Int = 16_000,
    private val channels: Int = 1,
) {
    private val mutex = Mutex()
    private val randomAccessFile: RandomAccessFile
    private var totalBytesWritten: Long = 0

    init {
        file.parentFile?.mkdirs()
        randomAccessFile = RandomAccessFile(file, "rw")
        randomAccessFile.setLength(0)
        randomAccessFile.write(ByteArray(44))
    }

    suspend fun write(samples: ShortArray) {
        val buffer = ByteBuffer.allocate(samples.size * 2).order(ByteOrder.LITTLE_ENDIAN)
        samples.forEach(buffer::putShort)
        mutex.withLock {
            randomAccessFile.seek(44 + totalBytesWritten)
            randomAccessFile.write(buffer.array())
            totalBytesWritten += buffer.array().size
        }
    }

    suspend fun finalizeFile() {
        mutex.withLock {
            randomAccessFile.seek(0)
            randomAccessFile.write(buildHeader(totalBytesWritten.toInt()))
            randomAccessFile.close()
        }
    }

    fun durationSeconds(): Long {
        val bytesPerSecond = sampleRate * channels * 2
        return if (bytesPerSecond == 0) 0 else totalBytesWritten / bytesPerSecond
    }

    private fun buildHeader(dataSize: Int): ByteArray {
        val buffer = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN)
        buffer.put("RIFF".toByteArray())
        buffer.putInt(36 + dataSize)
        buffer.put("WAVE".toByteArray())
        buffer.put("fmt ".toByteArray())
        buffer.putInt(16)
        buffer.putShort(1)
        buffer.putShort(channels.toShort())
        buffer.putInt(sampleRate)
        buffer.putInt(sampleRate * channels * 2)
        buffer.putShort((channels * 2).toShort())
        buffer.putShort(16)
        buffer.put("data".toByteArray())
        buffer.putInt(dataSize)
        return buffer.array()
    }
}
