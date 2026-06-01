import Foundation
import WaiComputerKit

enum TranscriptAvailability: Equatable {
    case content
    case savedLocally
    case processing
    case empty

    static func resolve(
        segments: [Segment],
        status: RecordingStatus,
        localRecoveryManifest: RecordingBackupManifest?
    ) -> TranscriptAvailability {
        if !segments.isEmpty {
            return .content
        }

        if let localRecoveryManifest,
           status != .failed,
           localRecoveryManifest.syncState != .remoteReady {
            return .savedLocally
        }

        switch status {
        case .pendingUpload, .uploading, .processing:
            return .processing
        case .ready, .failed:
            return .empty
        }
    }
}

@MainActor
class RecordingDetailViewModel: ObservableObject {
    @Published var detail: RecordingDetail?
    @Published var isLoading = false
    @Published var error: String?
    @Published var localRecoveryManifest: RecordingBackupManifest?
    @Published private var generatingSummaryRecordingId: String?

    private var loadGeneration = 0

    var transcriptAvailability: TranscriptAvailability {
        guard let detail else { return .empty }
        return TranscriptAvailability.resolve(
            segments: detail.segments,
            status: detail.status,
            localRecoveryManifest: localRecoveryManifest
        )
    }

    func isGeneratingSummary(for recordingId: String) -> Bool {
        generatingSummaryRecordingId == recordingId
    }

    func loadDetail(recordingId: String, apiClient: APIClient, showLoading: Bool = true) async {
        loadGeneration += 1
        let generation = loadGeneration
        let isSwitchingRecording = detail?.id != nil && detail?.id != recordingId
        if isSwitchingRecording {
            detail = nil
            localRecoveryManifest = nil
        }
        if showLoading {
            isLoading = true
        }
        error = nil

        defer {
            if showLoading, generation == loadGeneration {
                isLoading = false
            }
        }

        do {
            let loadedDetail = try await apiClient.getRecording(id: recordingId)
            guard generation == loadGeneration else { return }
            applyFetchedDetail(loadedDetail)
        } catch {
            guard generation == loadGeneration else { return }
            self.error = error.userFacingMessage(context: .library)
        }
    }

    /// Async-job summary generation: kick off the job, patch local state so the
    /// UI flips to the in-progress indicator, then poll detail until it settles.
    func startSummaryGeneration(recordingId id: String, apiClient: APIClient) async {
        generatingSummaryRecordingId = id
        defer {
            if generatingSummaryRecordingId == id {
                generatingSummaryRecordingId = nil
            }
        }

        do {
            let state = try await apiClient.startSummaryGeneration(recordingId: id)
            if detail?.id == id {
                detail = detail?.withSummaryGeneration(state)
            }
            await refreshPendingDetailIfNeeded(recordingId: id, apiClient: apiClient)
        } catch {
            self.error = error.userFacingMessage(context: .library)
        }
    }

    func refreshPendingDetailIfNeeded(recordingId: String, apiClient: APIClient) async {
        guard detail?.id == recordingId else { return }
        guard shouldAutoRefresh(for: detail) else { return }

        while !Task.isCancelled,
              detail?.id == recordingId,
              shouldAutoRefresh(for: detail) {
            let delay: Duration = detail?.summaryGeneration?.isActive == true
                ? .seconds(2)
                : .seconds(detail?.status == .processing ? 4 : 2)
            try? await Task.sleep(for: delay)
            guard !Task.isCancelled else { return }
            await loadDetail(recordingId: recordingId, apiClient: apiClient, showLoading: false)
        }
    }

    func renameRecording(_ newTitle: String, apiClient: APIClient) async -> Bool {
        guard let id = detail?.id else { return false }
        let trimmed = newTitle.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return false }
        do {
            _ = try await apiClient.updateRecording(id: id, title: trimmed)
            applyFetchedDetail(try await apiClient.getRecording(id: id))
            return true
        } catch {
            self.error = error.userFacingMessage(context: .library)
            return false
        }
    }

    /// Returns the exported content as a String for the caller to bridge to a
    /// temp file URL and present via ShareLink.
    func exportRecording(format: String, locale: String?, apiClient: APIClient) async -> String? {
        guard let id = detail?.id else { return nil }
        do {
            return try await apiClient.exportRecording(id: id, format: format, locale: locale)
        } catch {
            self.error = error.userFacingMessage(context: .library)
            return nil
        }
    }

    func createShareLink(apiClient: APIClient) async -> URL? {
        guard let id = detail?.id else { return nil }
        do {
            let link = try await apiClient.createRecordingShareLink(id: id)
            return link.url
        } catch {
            self.error = error.userFacingMessage(context: .library)
            return nil
        }
    }

    private func shouldAutoRefresh(for detail: RecordingDetail?) -> Bool {
        if detail?.summaryGeneration?.isActive == true {
            return true
        }
        switch detail?.status {
        case .pendingUpload, .uploading, .processing:
            return true
        case .ready, .failed, .none:
            return false
        }
    }

    private func applyFetchedDetail(_ detail: RecordingDetail) {
        let localRecovery = localRecoveryDetail(for: detail)
        self.detail = localRecovery.detail
        localRecoveryManifest = localRecovery.manifest
        if let recoveryError = localRecovery.error {
            self.error = recoveryError.userFacingMessage(context: .library)
        }
    }

    private func localRecoveryDetail(for detail: RecordingDetail) -> (
        detail: RecordingDetail,
        manifest: RecordingBackupManifest?,
        error: Error?
    ) {
        do {
            guard let manifest = try RecordingBackupStore.manifest(recordingId: detail.id) else {
                return (detail, nil, nil)
            }

            guard detail.segments.isEmpty else {
                return (detail, manifest, nil)
            }

            let segments: [Segment]
            do {
                segments = try localSegments(recordingId: detail.id, manifest: manifest)
            } catch {
                return (detail, manifest, error)
            }
            guard !segments.isEmpty else {
                return (detail, manifest, nil)
            }

            return (
                RecordingDetail(
                    id: detail.id,
                    title: detail.title,
                    type: detail.type,
                    audioUrl: detail.audioUrl,
                    status: detail.status,
                    failureCode: detail.failureCode,
                    failureMessage: detail.failureMessage,
                    uploadedAt: detail.uploadedAt,
                    durationSeconds: detail.durationSeconds,
                    language: detail.language,
                    folderId: detail.folderId,
                    deletedAt: detail.deletedAt,
                    starredAt: detail.starredAt,
                    createdAt: detail.createdAt,
                    segments: segments,
                    summary: detail.summary,
                    summaryGeneration: detail.summaryGeneration,
                    actionItems: detail.actionItems,
                    highlights: detail.highlights
                ),
                manifest,
                nil
            )
        } catch {
            return (detail, nil, error)
        }
    }

    private func localSegments(
        recordingId: String,
        manifest: RecordingBackupManifest
    ) throws -> [Segment] {
        let storedSegments = try RecordingBackupStore.segments(recordingId: recordingId)
            .enumerated()
            .compactMap { index, segment -> Segment? in
                let text = segment.text.trimmingCharacters(in: .whitespacesAndNewlines)
                guard !text.isEmpty else { return nil }

                return Segment(
                    id: "\(recordingId)-local-\(index)",
                    speaker: segment.speaker,
                    rawLabel: segment.speaker,
                    content: text,
                    startMs: segment.startMs,
                    endMs: segment.endMs,
                    confidence: segment.confidence
                )
            }

        if !storedSegments.isEmpty {
            return storedSegments
        }

        guard let transcript = manifest.transcript?.trimmingCharacters(in: .whitespacesAndNewlines),
              !transcript.isEmpty else {
            return []
        }

        let durationMs = max(Int(manifest.durationSeconds.rounded()), 1) * 1000
        return [
            Segment(
                id: "\(recordingId)-local-transcript",
                content: transcript,
                startMs: 0,
                endMs: durationMs,
                confidence: 1
            )
        ]
    }

    func loadScreenshotFixture(recordingId: String) {
        #if DEBUG
        loadGeneration += 1
        detail = IOSScreenshotFixtures.detail
        localRecoveryManifest = nil
        isLoading = false
        error = nil
        #endif
    }
}
