package `is`.waiwai.computer.sync

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.pm.ServiceInfo
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.ForegroundInfo
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerFactory
import androidx.work.WorkerParameters
import `is`.waiwai.computer.R
import `is`.waiwai.computer.auth.AuthStore
import `is`.waiwai.computer.data.RecordingDetail
import `is`.waiwai.computer.data.WaiApi
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

class PendingSyncWorker(
    appContext: Context,
    params: WorkerParameters,
    private val waiApi: WaiApi,
    private val localRecordingStore: LocalRecordingStore,
    private val authStore: AuthStore,
) : CoroutineWorker(appContext, params) {
    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        setForeground(createForegroundInfo())
        val pending = localRecordingStore.listPending()
        var shouldRetry = false
        pending.forEach { manifest ->
            if (manifest.requiresAuthentication && authStore.currentAccessToken().isNullOrBlank()) {
                return@forEach
            }
            runCatching {
                syncOne(manifest)
            }.onFailure { error ->
                val updated = localRecordingStore.recordSyncFailure(
                    manifest.recordingId,
                    error.message ?: "Pending recording sync failed.",
                )
                if (updated?.syncDeadLetteredAtEpochMillis == null) {
                    shouldRetry = true
                }
            }
        }
        if (shouldRetry) Result.retry() else Result.success()
    }

    private suspend fun syncOne(manifest: LocalRecordingManifest): RecordingDetail {
        val recordingId = if (manifest.serverRecordingId.isNullOrBlank()) {
            val createdId = waiApi.createRecording(
                title = manifest.title,
                type = manifest.recordingType,
                language = "multi",
            ).id
            localRecordingStore.recordServerRecordingId(manifest.recordingId, createdId)
            createdId
        } else {
            manifest.serverRecordingId
        }
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
        PendingRecordingSyncPolicy.failureMessage(detail)?.let { error(it) }
        localRecordingStore.remove(manifest.recordingId)
        return detail
    }

    private fun createForegroundInfo(): ForegroundInfo {
        ensureChannel()
        val notification = NotificationCompat.Builder(applicationContext, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.stat_sys_upload)
            .setContentTitle(applicationContext.getString(R.string.app_name))
            .setContentText(applicationContext.getString(R.string.pending_sync_notification))
            .setOngoing(true)
            .build()
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            ForegroundInfo(
                NOTIFICATION_ID,
                notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC,
            )
        } else {
            ForegroundInfo(NOTIFICATION_ID, notification)
        }
    }

    private fun ensureChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = applicationContext.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.createNotificationChannel(
            NotificationChannel(
                CHANNEL_ID,
                applicationContext.getString(R.string.pending_sync_notification_channel),
                NotificationManager.IMPORTANCE_LOW,
            ),
        )
    }

    companion object {
        const val UNIQUE_NAME = "pendingRecordingSync"
        private const val CHANNEL_ID = "pending-recording-sync"
        private const val NOTIFICATION_ID = 2002
    }
}

class PendingSyncWorkerFactory(
    private val container: `is`.waiwai.computer.data.AppContainer,
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
                authStore = container.authStore,
            )
            else -> null
        }
    }
}

class PendingSyncWorkerScheduler(
    context: Context,
) {
    private val appContext = context.applicationContext

    fun enqueue() {
        val workManager = WorkManager.getInstance(appContext)
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
