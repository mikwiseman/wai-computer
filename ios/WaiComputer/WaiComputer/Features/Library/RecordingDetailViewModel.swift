import AVFoundation
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
    @Published private var generatingSummaryAudioRecordingId: String?
    @Published private var downloadingSummaryAudioRecordingId: String?
    @Published private var playingSummaryAudioRecordingId: String?

    private var summaryAudioPlayer: AVAudioPlayer?
    private var summaryAudioPlaybackToken = UUID()
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

    func isGeneratingSummaryAudio(for recordingId: String) -> Bool {
        generatingSummaryAudioRecordingId == recordingId
    }

    func isDownloadingSummaryAudio(for recordingId: String) -> Bool {
        downloadingSummaryAudioRecordingId == recordingId
    }

    func isPlayingSummaryAudio(for recordingId: String) -> Bool {
        playingSummaryAudioRecordingId == recordingId
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

    /// Async-job summary generation: kick off the job and patch local state so
    /// the UI flips to the in-progress indicator. Polling is owned by the
    /// `.task(id: detailRefreshKey)` observer in `RecordingDetailView`: patching
    /// `detail` with `withSummaryGeneration(state)` changes the refresh key,
    /// which re-arms that single polling loop. Do NOT also poll here, or two
    /// loops run concurrently and systematically drop each other's results.
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
        } catch {
            self.error = error.userFacingMessage(context: .library)
        }
    }

    func startSummaryAudioGeneration(recordingId id: String, apiClient: APIClient) async {
        generatingSummaryAudioRecordingId = id
        defer {
            if generatingSummaryAudioRecordingId == id {
                generatingSummaryAudioRecordingId = nil
            }
        }

        do {
            let state = try await apiClient.startRecordingSummaryAudio(recordingId: id)
            if detail?.id == id {
                detail = detail?.withSummaryAudio(state)
            }
        } catch {
            self.error = error.userFacingMessage(context: .library)
        }
    }

    /// Download the generated summary audio and play it (or stop it if already
    /// playing). Mirrors `MacRecordingDetailViewModel.playOrStopSummaryAudio`,
    /// with the iOS-specific `AVAudioSession` playback category so the audio is
    /// audible even with the ring/silent switch in silent mode.
    func playOrStopSummaryAudio(recordingId id: String, apiClient: APIClient) async {
        if playingSummaryAudioRecordingId == id {
            stopSummaryAudioPlayback(recordingId: id)
            return
        }

        downloadingSummaryAudioRecordingId = id
        defer {
            if downloadingSummaryAudioRecordingId == id {
                downloadingSummaryAudioRecordingId = nil
            }
        }

        do {
            let data = try await apiClient.downloadRecordingSummaryAudio(recordingId: id)
            guard detail?.id == id else { return }
            try playSummaryAudioData(data, sourceId: id)
        } catch {
            self.error = error.userFacingMessage(context: .library)
        }
    }

    private func playSummaryAudioData(_ data: Data, sourceId: String) throws {
        try AVAudioSession.sharedInstance().setCategory(.playback)
        try AVAudioSession.sharedInstance().setActive(true)

        let player = try AVAudioPlayer(data: data)
        player.prepareToPlay()
        guard player.play() else {
            throw NSError(
                domain: "IOSSummaryAudioPlayback",
                code: 1,
                userInfo: [NSLocalizedDescriptionKey: "Could not play summary audio."]
            )
        }

        summaryAudioPlayer?.stop()
        summaryAudioPlayer = player
        playingSummaryAudioRecordingId = sourceId

        let token = UUID()
        summaryAudioPlaybackToken = token
        let duration = max(player.duration, 0)
        Task { @MainActor [weak self] in
            if duration > 0 {
                try? await Task.sleep(nanoseconds: UInt64((duration + 0.25) * 1_000_000_000))
            } else {
                try? await Task.sleep(for: .seconds(1))
            }
            guard self?.summaryAudioPlaybackToken == token else { return }
            self?.playingSummaryAudioRecordingId = nil
            self?.summaryAudioPlayer = nil
        }
    }

    private func stopSummaryAudioPlayback(recordingId: String) {
        guard playingSummaryAudioRecordingId == recordingId else { return }
        summaryAudioPlaybackToken = UUID()
        summaryAudioPlayer?.stop()
        summaryAudioPlayer = nil
        playingSummaryAudioRecordingId = nil
    }

    func refreshPendingDetailIfNeeded(recordingId: String, apiClient: APIClient) async {
        guard detail?.id == recordingId else { return }
        guard shouldAutoRefresh(for: detail) else { return }

        while !Task.isCancelled,
              detail?.id == recordingId,
              shouldAutoRefresh(for: detail) {
            let delay: Duration = detail?.summaryGeneration?.isActive == true
                || detail?.summaryAudio?.isActive == true
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

        // The PATCH is the source of truth for success. Once it returns, the
        // rename has been persisted server-side, so reflect it locally right
        // away and report success — even if the follow-up detail refresh fails.
        do {
            _ = try await apiClient.updateRecording(id: id, title: trimmed)
        } catch {
            self.error = error.userFacingMessage(context: .library)
            return false
        }

        if detail?.id == id {
            detail = detail?.withTitle(trimmed)
        }

        // Best-effort refresh of the full detail; a failure here must NOT turn a
        // successful rename into a reported failure. Surface it as a dismissible
        // banner instead and keep the locally-applied title.
        do {
            applyFetchedDetail(try await apiClient.getRecording(id: id))
        } catch {
            self.error = error.userFacingMessage(context: .library)
        }
        return true
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
        if detail?.summaryAudio?.isActive == true {
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
                    summaryAudio: detail.summaryAudio,
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
