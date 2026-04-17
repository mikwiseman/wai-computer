package `is`.waiwai.say.sync

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerFactory
import androidx.work.WorkerParameters
import `is`.waiwai.say.data.RecordingDetail
import `is`.waiwai.say.data.WaiApi
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

class PendingSyncWorker(
    appContext: Context,
    params: WorkerParameters,
    private val waiApi: WaiApi,
    private val localRecordingStore: LocalRecordingStore,
) : CoroutineWorker(appContext, params) {
    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        val pending = localRecordingStore.listPending()
        pending.forEach { manifest ->
            runCatching {
                syncOne(manifest)
            }.onFailure {
                return@withContext Result.retry()
            }
        }
        Result.success()
    }

    private suspend fun syncOne(manifest: LocalRecordingManifest): RecordingDetail {
        val recordingId = manifest.serverRecordingId
            ?: waiApi.createRecording(
                title = manifest.title,
                type = manifest.recordingType,
                language = "multi",
            ).id
        val audio = localRecordingStore.audioFile(manifest.recordingId)
        val detail = if (audio.exists()) {
            waiApi.uploadAudio(recordingId, audio)
        } else {
            val segments = localRecordingStore.loadSegments(manifest.recordingId)
            if (segments.isNotEmpty()) {
                waiApi.saveLiveTranscript(
                    recordingId = recordingId,
                    segments = segments,
                    durationSeconds = manifest.durationSeconds.toInt(),
                )
            } else {
                waiApi.getRecording(recordingId)
            }
        }
        localRecordingStore.remove(manifest.recordingId)
        return detail
    }

    companion object {
        const val UNIQUE_NAME = "pendingRecordingSync"
    }
}

class PendingSyncWorkerFactory(
    private val container: `is`.waiwai.say.data.AppContainer,
) : WorkerFactory() {
    override fun createWorker(
        appContext: Context,
        workerClassName: String,
        workerParameters: WorkerParameters,
    ): androidx.work.ListenableWorker? {
        return when (workerClassName) {
            PendingSyncWorker::class.java.name -> PendingSyncWorker(
                appContext = appContext,
                params = workerParameters,
                waiApi = container.waiApi,
                localRecordingStore = container.localRecordingStore,
            )
            else -> null
        }
    }
}

class PendingSyncWorkerScheduler(
    context: Context,
) {
    private val workManager = WorkManager.getInstance(context)

    fun enqueue() {
        val request = OneTimeWorkRequestBuilder<PendingSyncWorker>()
            .setConstraints(
                androidx.work.Constraints.Builder()
                    .setRequiredNetworkType(NetworkType.CONNECTED)
                    .build(),
            )
            .build()
        workManager.enqueueUniqueWork(
            PendingSyncWorker.UNIQUE_NAME,
            ExistingWorkPolicy.KEEP,
            request,
        )
    }
}
