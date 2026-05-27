import Foundation
import os
import Sentry

public extension Notification.Name {
    static let pendingRecordingSyncDidFinish = Notification.Name("pendingRecordingSyncDidFinish")
    static let pendingRecordingRecoveryNotice = Notification.Name("pendingRecordingRecoveryNotice")
}

public actor PendingRecordingSyncCoordinator {
    public static let shared = PendingRecordingSyncCoordinator()

    private let log = Logger(subsystem: "is.waiwai.computer", category: "sync")

    private var syncTask: Task<Void, Never>?
    private var retrySleepTask: Task<Void, Never>?
    private var retryImmediatelyAfterCurrentPass = false

    public func scheduleSync(using apiClient: APIClient) {
        guard syncTask == nil else {
            Task { [weak self] in
                await self?.clearAuthBlockedBackupsIfNeeded(using: apiClient)
            }
            if retrySleepTask != nil {
                log.info("Waking sync backoff delay (external trigger)")
                wakePendingRetryDelay()
            } else {
                retryImmediatelyAfterCurrentPass = true
            }
            return
        }

        log.info("Starting sync loop")
        syncTask = Task { [weak self] in
            await self?.clearAuthBlockedBackupsIfNeeded(using: apiClient)
            await self?.runSyncLoop(using: apiClient)
        }
    }

    private func runSyncLoop(using apiClient: APIClient) async {
        defer {
            syncTask = nil
            retryImmediatelyAfterCurrentPass = false
            wakePendingRetryDelay()
            log.info("Sync loop ended")
        }

        var attempt = 0

        while !Task.isCancelled {
            let pendingCount = (try? RecordingBackupStore.listBackups().count) ?? 0
            guard pendingCount > 0 else {
                log.info("No pending backups, exiting sync loop")
                return
            }

            log.info("Sync pass attempt \(attempt), \(pendingCount) pending backups")
            let remainingCount = await syncAllBackups(using: apiClient)
            guard remainingCount > 0 else {
                if retryImmediatelyAfterCurrentPass {
                    retryImmediatelyAfterCurrentPass = false
                    attempt = 0
                    log.info("Retrying sync immediately after successful pass")
                    continue
                }
                log.info("All backups synced successfully")
                return
            }

            if retryImmediatelyAfterCurrentPass {
                retryImmediatelyAfterCurrentPass = false
                attempt = 0
                log.info("Resetting attempt counter (immediate retry requested)")
                continue
            }

            attempt += 1

            // Exponential backoff: 5s, 10s, 20s, 40s, 80s, capped at 300s (5 min).
            let delay = min(300, 5 * Int(pow(2.0, Double(min(attempt - 1, 6)))))
            log.info("Sync pass done, \(remainingCount) remaining. Retrying in \(delay)s (attempt \(attempt))")
            SentryHelper.addBreadcrumb(
                category: "sync",
                message: "sync retry backoff",
                data: ["attempt": attempt, "remaining": remainingCount, "delaySeconds": delay]
            )
            await waitForRetryDelay(seconds: delay)
        }
    }

    @discardableResult
    private func syncAllBackups(using apiClient: APIClient) async -> Int {
        let backups = (try? RecordingBackupStore.listBackups()) ?? []
        guard !backups.isEmpty else { return 0 }

        var remaining = 0

        for backup in backups {
            let manifest = try? RecordingBackupStore.manifest(recordingId: backup.recordingId)
            if manifest?.syncState == .localRecording {
                log.info("Skipping in-progress recording backup \(backup.recordingId)")
                continue
            }
            if manifest?.syncState == .permanentFailure {
                continue
            }
            if manifest?.syncState == .authenticationRequired {
                continue
            }
            if manifest?.syncState == .remoteReady {
                continue
            }
            let didSync = await sync(backup: backup, using: apiClient)
            if !didSync {
                remaining += 1
            }
        }

        return remaining
    }

    private func sync(backup: RecordingBackup, using apiClient: APIClient) async -> Bool {
        do {
            let manifest = try RecordingBackupStore.manifest(recordingId: backup.recordingId)
            let hasAudioFile = FileManager.default.fileExists(atPath: backup.audioFileURL.path)
                && (manifest?.hasAudioFile ?? true)
            try RecordingBackupStore.recordSyncAttempt(recordingId: backup.recordingId)

            let detail: RecordingDetail?
            if manifest?.syncState == .serverProcessing {
                log.info("Polling server processing status for recording \(backup.recordingId)")
                detail = try await apiClient.getRecording(id: backup.recordingId)
            } else if hasAudioFile {
                log.info("Uploading audio for recording \(backup.recordingId)")
                let durationSeconds = Int((manifest?.durationSeconds ?? 0).rounded())
                detail = try await apiClient.uploadAudio(
                    recordingId: backup.recordingId,
                    fileURL: backup.audioFileURL,
                    clientDurationSeconds: durationSeconds > 0 ? durationSeconds : nil
                )
            } else if manifest != nil {
                log.info("Syncing transcript for recording \(backup.recordingId)")
                let segments = try segmentsForSync(recordingId: backup.recordingId, manifest: manifest)
                let durationSeconds = Int((manifest?.durationSeconds ?? 0).rounded())
                detail = try await apiClient.saveLiveTranscript(
                    recordingId: backup.recordingId,
                    segments: segments,
                    durationSeconds: durationSeconds
                )
            } else {
                log.warning("No manifest for recording \(backup.recordingId), skipping")
                _ = try? RecordingBackupStore.recordSaveFailure(
                    recordingId: backup.recordingId,
                    message: "Saved locally and waiting to sync."
                )
                return false
            }

            if let detail, detail.status == .failed {
                log.warning("Server returned failed status for recording \(backup.recordingId)")
                try RecordingBackupStore.markRetryableFailure(
                    recordingId: backup.recordingId,
                    message: UserFacingErrorFormatter.displayMessage(
                        detail.failureMessage,
                        fallback: "We couldn't finish saving your recording right now. We'll keep trying in the background.",
                        context: .recording
                    ),
                    failureCode: detail.failureCode
                )
                return false
            }

            if let detail, detail.status != .ready {
                log.info(
                    "Server accepted recording \(backup.recordingId) with status \(detail.status.rawValue)"
                )
                if detail.status == .processing || detail.status == .uploading {
                    try RecordingBackupStore.markServerProcessing(recordingId: backup.recordingId)
                }
                return false
            }

            try RecordingBackupStore.removeRecording(recordingId: backup.recordingId)
            log.info("Recording \(backup.recordingId) synced successfully")
            SentryHelper.addBreadcrumb(
                category: "backup",
                message: "pending recording synced",
                data: ["recordingId": backup.recordingId]
            )
            NotificationCenter.default.post(
                name: .pendingRecordingSyncDidFinish,
                object: nil,
                userInfo: ["recordingId": backup.recordingId]
            )
            return true
        } catch let apiError as APIError {
            log.error("Sync failed for \(backup.recordingId) with API error")
            switch apiError {
            case .unauthorized:
                _ = try? RecordingBackupStore.recordSaveFailure(
                    recordingId: backup.recordingId,
                    message: "Please sign in again to sync this recording."
                )
                try? RecordingBackupStore.markAuthenticationRequired(recordingId: backup.recordingId)
                log.error("Marked \(backup.recordingId) as authentication-required")
            case .httpError(let statusCode, _) where statusCode == 413:
                _ = try? RecordingBackupStore.recordSaveFailure(
                    recordingId: backup.recordingId,
                    message: "This recording is too large to upload."
                )
                try? RecordingBackupStore.markPermanentFailure(recordingId: backup.recordingId)
                log.error("Marked \(backup.recordingId) as permanent failure (too large)")
            default:
                _ = try? RecordingBackupStore.recordSaveFailure(
                    recordingId: backup.recordingId,
                    message: apiError.userFacingMessage(context: .recording)
                )
            }
            return false
        } catch {
            log.error("Sync failed for \(backup.recordingId)")
            _ = try? RecordingBackupStore.recordSaveFailure(
                recordingId: backup.recordingId,
                message: error.userFacingMessage(context: .recording)
            )
            return false
        }
    }

    private func segmentsForSync(
        recordingId: String,
        manifest: RecordingBackupManifest?
    ) throws -> [LiveTranscriptSegment] {
        let persistedSegments = try RecordingBackupStore.segments(recordingId: recordingId)
        if !persistedSegments.isEmpty {
            return persistedSegments
        }

        guard let transcript = manifest?.transcript?.trimmingCharacters(in: .whitespacesAndNewlines),
              !transcript.isEmpty else {
            return []
        }

        let durationSeconds = max(Int((manifest?.durationSeconds ?? 0).rounded()), 1)
        return [
            LiveTranscriptSegment(
                text: transcript,
                speaker: nil,
                isFinal: true,
                startMs: 0,
                endMs: durationSeconds * 1000,
                confidence: 1
            )
        ]
    }

    private func waitForRetryDelay(seconds: Int) async {
        let sleepTask = Task<Void, Never> {
            try? await Task.sleep(for: .seconds(seconds))
        }
        retrySleepTask = sleepTask
        await sleepTask.value
        retrySleepTask = nil
    }

    private func wakePendingRetryDelay() {
        retrySleepTask?.cancel()
        retrySleepTask = nil
    }

    private func clearAuthBlockedBackupsIfNeeded(using apiClient: APIClient) async {
        guard await apiClient.getAccessToken() != nil else { return }

        let backups = (try? RecordingBackupStore.listBackups()) ?? []
        for backup in backups {
            guard let manifest = try? RecordingBackupStore.manifest(recordingId: backup.recordingId),
                  manifest.requiresAuthentication else {
                continue
            }

            try? RecordingBackupStore.clearAuthenticationRequired(recordingId: backup.recordingId)
            log.info("Re-enabled sync for \(backup.recordingId) after session refresh")
        }
    }
}
