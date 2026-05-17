package `is`.waiwai.computer.sync

import android.content.Context
import `is`.waiwai.computer.data.LiveTranscriptSegment
import `is`.waiwai.computer.data.RecordingType
import java.io.File
import java.util.concurrent.ConcurrentHashMap
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json

class LocalRecordingStore(
    context: Context,
) {
    private val baseDir = File(context.filesDir, "recordings")
    private val json = Json { prettyPrint = true; explicitNulls = false }
    private val locks = ConcurrentHashMap<String, Mutex>()

    suspend fun save(manifest: LocalRecordingManifest, segments: List<LiveTranscriptSegment> = emptyList()) {
        withRecordingLock(manifest.recordingId) {
            val dir = recordingDir(manifest.recordingId)
            dir.mkdirs()
            writeAtomically(File(dir, "manifest.json"), json.encodeToString(manifest))
            if (segments.isNotEmpty()) {
                writeAtomically(File(dir, "transcript.json"), json.encodeToString(segments))
            }
        }
    }

    suspend fun recordSaveFailure(recordingId: String, message: String) {
        val manifest = manifest(recordingId) ?: return
        save(manifest.copy(failureMessage = message, updatedAtEpochMillis = System.currentTimeMillis()))
    }

    suspend fun remove(recordingId: String) {
        withRecordingLock(recordingId) {
            recordingDir(recordingId).deleteRecursively()
        }
    }

    suspend fun listPending(): List<LocalRecordingManifest> {
        if (!baseDir.exists()) return emptyList()
        return baseDir.listFiles()
            .orEmpty()
            .filter { it.isDirectory }
            .mapNotNull { dir ->
                runCatching {
                    json.decodeFromString<LocalRecordingManifest>(File(dir, "manifest.json").readText())
                }.getOrNull()
            }
            .sortedByDescending { it.updatedAtEpochMillis }
    }

    suspend fun manifest(recordingId: String): LocalRecordingManifest? {
        val file = File(recordingDir(recordingId), "manifest.json")
        if (!file.exists()) return null
        return json.decodeFromString(file.readText())
    }

    fun recordingDir(recordingId: String): File = File(baseDir, recordingId)

    fun audioFile(recordingId: String): File = File(recordingDir(recordingId), "audio.wav")

    fun transcriptFile(recordingId: String): File = File(recordingDir(recordingId), "transcript.json")

    suspend fun loadSegments(recordingId: String): List<LiveTranscriptSegment> {
        val file = transcriptFile(recordingId)
        if (!file.exists()) return emptyList()
        return json.decodeFromString(file.readText())
    }

    suspend fun totalUsageBytes(): Long {
        if (!baseDir.exists()) return 0
        return baseDir.walkTopDown().filter { it.isFile }.sumOf { it.length() }
    }

    suspend fun clearAll() {
        baseDir.deleteRecursively()
    }

    private suspend fun withRecordingLock(recordingId: String, block: suspend () -> Unit) {
        locks.getOrPut(recordingId) { Mutex() }.withLock { block() }
    }

    private fun writeAtomically(target: File, content: String) {
        target.parentFile?.mkdirs()
        val temp = File.createTempFile(target.nameWithoutExtension, ".tmp", target.parentFile)
        temp.writeText(content)
        if (!temp.renameTo(target)) {
            temp.delete()
            throw IllegalStateException("Failed to atomically write ${target.name}")
        }
    }
}

@Serializable
data class LocalRecordingManifest(
    val recordingId: String,
    val serverRecordingId: String? = null,
    val title: String? = null,
    val recordingType: RecordingType = RecordingType.note,
    val durationSeconds: Long = 0,
    val transcript: String? = null,
    val createdAtEpochMillis: Long = System.currentTimeMillis(),
    val updatedAtEpochMillis: Long = System.currentTimeMillis(),
    val hasAudioFile: Boolean = false,
    val failureMessage: String? = null,
    val localOnly: Boolean = false,
    val requiresAuthentication: Boolean = false,
)
