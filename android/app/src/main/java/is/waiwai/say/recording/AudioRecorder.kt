package `is`.waiwai.say.recording

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import androidx.core.content.ContextCompat
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.launch

interface AudioRecorder {
    val isRecording: Boolean
    fun start(): Flow<ShortArray>
    suspend fun stop()
}

class AndroidAudioRecorder(
    private val context: Context,
) : AudioRecorder {
    @Volatile
    private var recorder: AudioRecord? = null

    @Volatile
    override var isRecording: Boolean = false
        private set

    override fun start(): Flow<ShortArray> = callbackFlow {
        check(
            ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) ==
                PackageManager.PERMISSION_GRANTED,
        ) { "Microphone permission denied" }

        val minBuffer = AudioRecord.getMinBufferSize(
            SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
        )
        val bufferSize = maxOf(minBuffer * 2, 5_120)
        val audioRecord = AudioRecord.Builder()
            .setAudioSource(MediaRecorder.AudioSource.VOICE_RECOGNITION)
            .setAudioFormat(
                AudioFormat.Builder()
                    .setSampleRate(SAMPLE_RATE)
                    .setChannelMask(AudioFormat.CHANNEL_IN_MONO)
                    .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                    .build(),
            )
            .setBufferSizeInBytes(bufferSize)
            .build()

        recorder = audioRecord
        isRecording = true
        audioRecord.startRecording()

        val readerJob = launch(Dispatchers.IO) {
            val frameSize = 1600
            while (isRecording) {
                val frame = ShortArray(frameSize)
                val read = audioRecord.read(frame, 0, frame.size)
                when {
                    read > 0 -> trySend(frame.copyOf(read))
                    read == AudioRecord.ERROR_DEAD_OBJECT -> {
                        close(IllegalStateException("AudioRecord became invalid."))
                        return@launch
                    }
                    read < 0 -> {
                        close(IllegalStateException("AudioRecord read failed: $read"))
                        return@launch
                    }
                }
            }
        }

        awaitClose {
            isRecording = false
            readerJob.cancel()
            recorder?.runCatching {
                stop()
                release()
            }
            recorder = null
        }
    }

    override suspend fun stop() {
        isRecording = false
        recorder?.runCatching { stop() }
    }

    companion object {
        private const val SAMPLE_RATE = 16_000
    }
}
