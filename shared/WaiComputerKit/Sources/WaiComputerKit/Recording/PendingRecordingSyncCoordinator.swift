import Foundation
import Sentry

public extension Notification.Name {
    static let pendingRecordingSyncDidFinish = Notification.Name("pendingRecordingSyncDidFinish")
    static let pendingRecordingRecoveryNotice = Notification.Name("pendingRecordingRecoveryNotice")
}

public actor PendingRecordingSyncCoordinator {
    public static let shared = PendingRecordingSyncCoordinator()

    private var syncTask: Task<Void, Never>?
    private var retrySleepTask: Task<Void, Never>?
    private var retryImmediatelyAfterCurrentPass = false

    public func scheduleSync(using apiClient: APIClient) {
        guard syncTask == nil else {
            if retrySleepTask != nil {
                wakePendingRetryDelay()
            } else {
                retryImmediatelyAfterCurrentPass = true
            }
            return
        }

        syncTask = Task { [weak self] in
            await self?.runSyncLoop(using: apiClient)
        }
    }

    private func runSyncLoop(using apiClient: APIClient) async {
        defer {
            syncTask = nil
            retryImmediatelyAfterCurrentPass = false
            wakePendingRetryDelay()
        }

        var attempt = 0

        while !Task.isCancelled {
            let pendingCount = (try? RecordingBackupStore.listBackups().count) ?? 0
            guard pendingCount > 0 else { return }

            let remainingCount = await syncAllBackups(using: apiClient)
            guard remainingCount > 0 else { return }

            if retryImmediatelyAfterCurrentPass {
                retryImmediatelyAfterCurrentPass = false
                continue
            }

            attempt += 1
            let delay = min(60, 5 * attempt)
            await waitForRetryDelay(seconds: delay)
        }
    }

    @discardableResult
    private func syncAllBackups(using apiClient: APIClient) async -> Int {
        let backups = (try? RecordingBackupStore.listBackups()) ?? []
        guard !backups.isEmpty else { return 0 }

        var remaining = 0

        for backup in backups {
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
            let segments = try segmentsForSync(recordingId: backup.recordingId, manifest: manifest)
            let hasAudioFile = FileManager.default.fileExists(atPath: backup.audioFileURL.path)
                && (manifest?.hasAudioFile ?? true)

            let detail: RecordingDetail?
            if hasAudioFile {
                detail = try await apiClient.uploadAudio(recordingId: backup.recordingId, fileURL: backup.audioFileURL)
            } else if manifest != nil {
                let durationSeconds = Int((manifest?.durationSeconds ?? 0).rounded())
                detail = try await apiClient.saveLiveTranscript(
                    recordingId: backup.recordingId,
                    segments: segments,
                    durationSeconds: durationSeconds
                )
            } else {
                _ = try? RecordingBackupStore.recordSaveFailure(
                    recordingId: backup.recordingId,
                    message: "Saved locally and waiting to sync."
                )
                return false
            }

            if let detail, detail.status == .failed {
                _ = try? RecordingBackupStore.recordSaveFailure(
                    recordingId: backup.recordingId,
                    message: UserFacingErrorFormatter.displayMessage(
                        detail.failureMessage,
                        fallback: "We couldn't finish saving your recording right now. We'll keep trying in the background.",
                        context: .recording
                    )
                )
                return false
            }

            try RecordingBackupStore.removeRecording(recordingId: backup.recordingId)
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
        } catch {
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
}
