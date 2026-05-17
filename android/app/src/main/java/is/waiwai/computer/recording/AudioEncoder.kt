package `is`.waiwai.computer.recording

import java.nio.ByteBuffer
import java.nio.ByteOrder

class AudioEncoder {
    fun encode(samples: ShortArray): ByteArray {
        val buffer = ByteBuffer.allocate(samples.size * 2).order(ByteOrder.LITTLE_ENDIAN)
        samples.forEach { sample -> buffer.putShort(sample) }
        return buffer.array()
    }
}
