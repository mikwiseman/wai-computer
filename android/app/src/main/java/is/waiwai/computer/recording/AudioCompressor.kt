package `is`.waiwai.computer.recording

import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaFormat
import android.media.MediaMuxer
import java.io.File
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder

/** Result of compressing a recording before upload. */
data class CompressedAudio(val file: File, val byteCount: Long, val durationSeconds: Long)

/** Parsed PCM layout of a WAV file. */
data class WavFormat(
    val sampleRate: Int,
    val channels: Int,
    val dataOffset: Long,
    val dataLength: Long,
)

/**
 * Transcodes the recorded PCM WAV to AAC `.m4a` before upload. Raw 16 kHz mono
 * PCM is ~110 MB/hour and trips the 200 MB upload ceiling for recordings over
 * ~1h49m; AAC at speech bitrates is ~22 MB/hour. AAC encoding via [MediaCodec]
 * is available from API 16, so no minSdk bump is required.
 */
object AudioCompressor {

    private const val TIMEOUT_US = 10_000L
    private const val MAX_INPUT_SIZE = 64 * 1024

    /** Cheap RIFF/WAVE sniff so imported non-WAV uploads pass through untouched. */
    fun isWav(file: File): Boolean {
        if (file.length() < 12) return false
        RandomAccessFile(file, "r").use { raf ->
            val head = ByteArray(12)
            if (raf.read(head) < 12) return false
            return String(head, 0, 4, Charsets.US_ASCII) == "RIFF" &&
                String(head, 8, 4, Charsets.US_ASCII) == "WAVE"
        }
    }

    /** Walks RIFF chunks to read format + locate PCM data. Tolerates extra chunks. */
    fun readWavFormat(file: File): WavFormat {
        RandomAccessFile(file, "r").use { raf ->
            val riff = ByteArray(4).also { raf.readFully(it) }
            require(String(riff, Charsets.US_ASCII) == "RIFF") { "Not a RIFF file" }
            raf.skipBytes(4) // overall RIFF size
            val wave = ByteArray(4).also { raf.readFully(it) }
            require(String(wave, Charsets.US_ASCII) == "WAVE") { "Not a WAVE file" }

            var sampleRate = 0
            var channels = 0
            var haveFmt = false
            val tag = ByteArray(4)

            while (true) {
                if (raf.read(tag) < 4) throw IllegalArgumentException("WAV missing 'data' chunk")
                val size = readUInt32LE(raf)
                when (String(tag, Charsets.US_ASCII)) {
                    "fmt " -> {
                        val fmt = ByteArray(16).also { raf.readFully(it) }
                        val bb = ByteBuffer.wrap(fmt).order(ByteOrder.LITTLE_ENDIAN)
                        bb.short // audio format (PCM = 1)
                        channels = bb.short.toInt() and 0xFFFF
                        sampleRate = bb.int
                        haveFmt = true
                        val skip = size - 16 + (size and 1L) // remainder + pad byte
                        if (skip > 0) raf.seek(raf.filePointer + skip)
                    }
                    "data" -> {
                        require(haveFmt) { "WAV 'data' chunk preceded 'fmt '" }
                        require(channels >= 1) { "WAV has no channels" }
                        return WavFormat(sampleRate, channels, raf.filePointer, size)
                    }
                    else -> raf.seek(raf.filePointer + size + (size and 1L))
                }
            }
        }
    }

    /**
     * Transcodes [source] (PCM WAV) to AAC-LC in an `.m4a` at [dest], preserving
     * sample rate + channel count. Streams the source so multi-hour recordings
     * don't load fully into memory. Overwrites [dest] if present.
     */
    fun compressWavToM4a(source: File, dest: File, bitRate: Int = 48_000): CompressedAudio {
        val wav = readWavFormat(source)
        require(wav.dataLength > 0) { "WAV contains no PCM data" }
        if (dest.exists()) dest.delete()

        val mediaFormat = MediaFormat.createAudioFormat(
            MediaFormat.MIMETYPE_AUDIO_AAC, wav.sampleRate, wav.channels,
        ).apply {
            setInteger(MediaFormat.KEY_AAC_PROFILE, MediaCodecInfo.CodecProfileLevel.AACObjectLC)
            setInteger(MediaFormat.KEY_BIT_RATE, bitRate)
            setInteger(MediaFormat.KEY_MAX_INPUT_SIZE, MAX_INPUT_SIZE)
        }

        val codec = MediaCodec.createEncoderByType(MediaFormat.MIMETYPE_AUDIO_AAC)
        val muxer = MediaMuxer(dest.absolutePath, MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4)
        val bytesPerFrame = 2 * wav.channels

        try {
            codec.configure(mediaFormat, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
            codec.start()

            RandomAccessFile(source, "r").use { raf ->
                raf.seek(wav.dataOffset)
                var remaining = wav.dataLength
                var framesRead = 0L
                var trackIndex = -1
                var muxerStarted = false
                var inputDone = false
                val info = MediaCodec.BufferInfo()

                while (true) {
                    if (!inputDone) {
                        val inIndex = codec.dequeueInputBuffer(TIMEOUT_US)
                        if (inIndex >= 0) {
                            val inBuf = codec.getInputBuffer(inIndex)!!.apply { clear() }
                            val toRead = minOf(inBuf.capacity().toLong(), remaining).toInt()
                            var filled = 0
                            if (toRead > 0) {
                                val chunk = ByteArray(toRead)
                                val n = raf.read(chunk, 0, toRead)
                                if (n > 0) {
                                    inBuf.put(chunk, 0, n)
                                    filled = n
                                }
                            }
                            val ptsUs = framesRead * 1_000_000L / wav.sampleRate
                            if (filled <= 0) {
                                codec.queueInputBuffer(inIndex, 0, 0, ptsUs, MediaCodec.BUFFER_FLAG_END_OF_STREAM)
                                inputDone = true
                            } else {
                                codec.queueInputBuffer(inIndex, 0, filled, ptsUs, 0)
                                remaining -= filled
                                framesRead += (filled / bytesPerFrame).toLong()
                            }
                        }
                    }

                    when (val outIndex = codec.dequeueOutputBuffer(info, TIMEOUT_US)) {
                        MediaCodec.INFO_OUTPUT_FORMAT_CHANGED -> {
                            trackIndex = muxer.addTrack(codec.outputFormat)
                            muxer.start()
                            muxerStarted = true
                        }
                        MediaCodec.INFO_TRY_AGAIN_LATER -> Unit
                        else -> if (outIndex >= 0) {
                            val outBuf = codec.getOutputBuffer(outIndex)!!
                            if (info.flags and MediaCodec.BUFFER_FLAG_CODEC_CONFIG != 0) {
                                info.size = 0 // codec config is consumed by addTrack, not muxed
                            }
                            if (info.size > 0 && muxerStarted) {
                                outBuf.position(info.offset)
                                outBuf.limit(info.offset + info.size)
                                muxer.writeSampleData(trackIndex, outBuf, info)
                            }
                            codec.releaseOutputBuffer(outIndex, false)
                            if (info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0) break
                        }
                    }
                }
            }
        } finally {
            runCatching { codec.stop() }
            codec.release()
            runCatching { muxer.stop() }
            muxer.release()
        }

        val durationSeconds = wav.dataLength / bytesPerFrame / wav.sampleRate
        return CompressedAudio(dest, dest.length(), durationSeconds)
    }

    private fun readUInt32LE(raf: RandomAccessFile): Long {
        val b = ByteArray(4).also { raf.readFully(it) }
        return (b[0].toLong() and 0xFF) or
            ((b[1].toLong() and 0xFF) shl 8) or
            ((b[2].toLong() and 0xFF) shl 16) or
            ((b[3].toLong() and 0xFF) shl 24)
    }
}
