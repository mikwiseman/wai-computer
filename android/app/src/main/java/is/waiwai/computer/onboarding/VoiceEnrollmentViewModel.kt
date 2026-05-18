package `is`.waiwai.computer.onboarding

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import androidx.core.content.ContextCompat
import `is`.waiwai.computer.data.WaiApi
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

private const val SAMPLE_RATE = 16_000
private const val MAX_DURATION_S = 20.0

data class VoiceUiState(
    val state: State = State.Idle,
    val elapsedSeconds: Double = 0.0,
    val hasPermission: Boolean = false,
    val errorMessage: String? = null,
) {
    enum class State { Idle, Recording, Recorded, Uploading }

    val progress: Float get() = (elapsedSeconds / MAX_DURATION_S).coerceIn(0.0, 1.0).toFloat()
    val canRecord: Boolean get() = state == State.Idle && hasPermission

    val statusLabel: String
        get() = when (state) {
            State.Idle -> if (hasPermission) "Press the mic to start" else "Grant microphone access first"
            State.Recording -> "Recording… ${elapsedSeconds.toInt()}s / ${MAX_DURATION_S.toInt()}s"
            State.Recorded -> "Recorded ${elapsedSeconds.toInt()}s. Use it or re-record."
            State.Uploading -> "Uploading voice signature…"
        }
}

/**
 * Lightweight voice-enrollment view model. Owns its own coroutine scope so it can survive
 * the composable's recompositions (we drive it via `remember`, not Hilt, to keep
 * onboarding self-contained).
 */
class VoiceEnrollmentViewModel(
    private val waiApi: WaiApi,
    private val context: Context,
) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)

    private val _uiState = MutableStateFlow(VoiceUiState())
    val uiState: StateFlow<VoiceUiState> = _uiState.asStateFlow()

    private var recordJob: Job? = null
    private var capturedPcm: ByteArray? = null

    fun onPermissionResult(granted: Boolean) {
        _uiState.update { it.copy(hasPermission = granted) }
    }

    fun start() {
        if (_uiState.value.state == VoiceUiState.State.Recording) return
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO)
            != PackageManager.PERMISSION_GRANTED
        ) {
            _uiState.update { it.copy(errorMessage = "Microphone permission required.") }
            return
        }
        _uiState.update {
            it.copy(state = VoiceUiState.State.Recording, elapsedSeconds = 0.0, errorMessage = null)
        }
        capturedPcm = null

        recordJob = scope.launch(Dispatchers.IO) {
            val buffer = ByteArrayOutputStream()
            val minBuffer = AudioRecord.getMinBufferSize(
                SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
            )
            val bufferSize = maxOf(minBuffer * 2, 8_192)
            val record = AudioRecord.Builder()
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

            try {
                record.startRecording()
                val frame = ShortArray(1600)
                val started = System.nanoTime()
                while (_uiState.value.state == VoiceUiState.State.Recording) {
                    val read = record.read(frame, 0, frame.size)
                    if (read > 0) {
                        val bytes = ByteBuffer.allocate(read * 2).order(ByteOrder.LITTLE_ENDIAN)
                        for (i in 0 until read) bytes.putShort(frame[i])
                        buffer.write(bytes.array())
                    }
                    val elapsed = (System.nanoTime() - started) / 1_000_000_000.0
                    _uiState.update { it.copy(elapsedSeconds = elapsed) }
                    if (elapsed >= MAX_DURATION_S) break
                }
            } catch (error: Throwable) {
                _uiState.update {
                    it.copy(state = VoiceUiState.State.Idle, errorMessage = error.message)
                }
            } finally {
                runCatching {
                    record.stop()
                    record.release()
                }
                if (_uiState.value.state == VoiceUiState.State.Recording) {
                    capturedPcm = buffer.toByteArray()
                    _uiState.update { it.copy(state = VoiceUiState.State.Recorded) }
                }
            }
        }
    }

    fun stop() {
        if (_uiState.value.state != VoiceUiState.State.Recording) return
        _uiState.update { it.copy(state = VoiceUiState.State.Recorded) }
    }

    fun reset() {
        recordJob?.cancel()
        capturedPcm = null
        _uiState.update {
            VoiceUiState(hasPermission = it.hasPermission)
        }
    }

    fun submit(onDone: () -> Unit) {
        val pcm = capturedPcm ?: return
        _uiState.update { it.copy(state = VoiceUiState.State.Uploading) }
        scope.launch {
            try {
                val wav = wrapPcmAsWav(pcm, sampleRate = SAMPLE_RATE)
                waiApi.enrollVoice(audio = wav, filename = "enrollment.wav", mimeType = "audio/wav")
                onDone()
            } catch (error: Throwable) {
                _uiState.update {
                    it.copy(state = VoiceUiState.State.Recorded, errorMessage = error.message)
                }
            }
        }
    }
}

/// Wrap raw PCM-16 mono bytes in a WAV container so the backend can decode without ffmpeg quirks.
private fun wrapPcmAsWav(pcm: ByteArray, sampleRate: Int): ByteArray {
    val channels = 1
    val bitsPerSample = 16
    val byteRate = sampleRate * channels * bitsPerSample / 8
    val totalDataLen = pcm.size + 36
    val header = ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN).apply {
        put("RIFF".toByteArray())
        putInt(totalDataLen)
        put("WAVE".toByteArray())
        put("fmt ".toByteArray())
        putInt(16) // PCM chunk size
        putShort(1) // PCM format
        putShort(channels.toShort())
        putInt(sampleRate)
        putInt(byteRate)
        putShort((channels * bitsPerSample / 8).toShort())
        putShort(bitsPerSample.toShort())
        put("data".toByteArray())
        putInt(pcm.size)
    }.array()
    return header + pcm
}

