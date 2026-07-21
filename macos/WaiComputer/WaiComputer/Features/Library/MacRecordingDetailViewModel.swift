import AVFoundation
import Foundation
import WaiComputerKit

enum MacTranscriptAvailability: Equatable {
    case content
    case savedLocally
    case processing
    case empty
    case failed

    static func resolve(
        segments: [Segment],
        status: RecordingStatus,
        localRecoveryManifest: RecordingBackupManifest?
    ) -> MacTranscriptAvailability {
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
        case .failed:
            return .failed
        case .ready:
            return .empty
        }
    }
}

@MainActor
protocol MacSummaryAudioPlaying: AnyObject {
    var duration: TimeInterval { get }

    func prepareToPlay() -> Bool
    func play() -> Bool
    func stop()
}

extension AVAudioPlayer: MacSummaryAudioPlaying {}

enum MacSummaryAudioPlayback {
    static func makePlayer(data: Data) throws -> any MacSummaryAudioPlaying {
        try AVAudioPlayer(data: data)
    }
}

@MainActor
class MacRecordingDetailViewModel: ObservableObject {
    @Published var recordingDetail: RecordingDetail? {
        didSet { recordingDetailRevision += 1 }
    }
    @Published var isLoading = false
    @Published var error: String?
    @Published var localRecoveryManifest: RecordingBackupManifest?
    @Published private var generatingSummaryRecordingId: String?
    @Published private var generatingSummaryAudioRecordingId: String?
    @Published private var downloadingSummaryAudioRecordingId: String?
    @Published private var playingSummaryAudioRecordingId: String?

    private let makeSummaryAudioPlayer: (Data) throws -> any MacSummaryAudioPlaying
    private var summaryAudioPlayer: (any MacSummaryAudioPlaying)?
    private var summaryAudioPlaybackToken = UUID()
    private var loadGeneration = 0

    // Memoized transcript turns. `mergeTurns` sorts + groups (O(n log n)); it used
    // to re-run on every SwiftUI body pass (selection, the auto-refresh poll,
    // summary-audio state) which was a major scroll-jank source on long
    // transcripts. Recording detail mutations bump `recordingDetailRevision`,
    // keeping the per-body cache key constant-time even for long transcripts.
    private var recordingDetailRevision = 0
    private var cachedTurns: [TranscriptTurn] = []
    private var cachedTurnsKey: MacTranscriptTurnsCacheKey?

    private struct MacTranscriptTurnsCacheKey: Equatable {
        let languageCode: String
        let revision: Int
    }

    init(
        initialDetail: RecordingDetail? = nil,
        summaryAudioPlayerFactory: @escaping (Data) throws -> any MacSummaryAudioPlaying = MacSummaryAudioPlayback.makePlayer
    ) {
        recordingDetail = initialDetail
        makeSummaryAudioPlayer = summaryAudioPlayerFactory
    }

    var transcriptAvailability: MacTranscriptAvailability {
        guard let detail = recordingDetail else { return .empty }
        return MacTranscriptAvailability.resolve(
            segments: detail.segments,
            status: detail.status,
            localRecoveryManifest: localRecoveryManifest
        )
    }

    /// Merged, render-ready transcript turns — memoized (see `cachedTurns`). The
    /// view calls this once per body pass; the work only happens when the cache
    /// key (recording detail revision + language) changes.
    func transcriptTurns(languageCode: String) -> [TranscriptTurn] {
        let segments = recordingDetail?.segments ?? []
        let key = MacTranscriptTurnsCacheKey(languageCode: languageCode, revision: recordingDetailRevision)
        if key == cachedTurnsKey {
            return cachedTurns
        }
        let turns = TranscriptRendering.mergeTurns(segments, languageCode: languageCode)
        cachedTurns = turns
        cachedTurnsKey = key
        return turns
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

    func load(
        recordingId: String,
        apiClient: APIClient,
        fixtureDetail: (() async -> RecordingDetail?)? = nil,
        showLoading: Bool = true
    ) async {
        loadGeneration += 1
        let generation = loadGeneration
        let isSwitchingRecording = recordingDetail?.id != nil && recordingDetail?.id != recordingId
        if isSwitchingRecording {
            recordingDetail = nil
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
            let detail: RecordingDetail
            if let fixture = await fixtureDetail?() {
                detail = fixture
            } else {
                detail = try await apiClient.getRecording(id: recordingId)
            }
            // Local-recovery reads decode backup JSON from disk; keep them off
            // the main actor — this load repeats every 2-4s while processing.
            let localRecovery = await Task.detached(priority: .userInitiated) {
                Self.localRecoveryDetail(for: detail)
            }.value
            guard generation == loadGeneration else { return }
            applyFetchedDetail(localRecovery)
        } catch {
            guard generation == loadGeneration else { return }
            self.error = error.userFacingMessage(context: .library)
        }
    }

    func refreshPendingDetailIfNeeded(
        recordingId: String,
        apiClient: APIClient,
        fixtureDetail: (() async -> RecordingDetail?)? = nil
    ) async {
        guard recordingDetail?.id == recordingId else { return }
        guard shouldAutoRefresh(detail: recordingDetail) else { return }

        while !Task.isCancelled,
              recordingDetail?.id == recordingId,
              shouldAutoRefresh(detail: recordingDetail) {
            let delay: Duration = recordingDetail?.summaryGeneration?.isActive == true
                || recordingDetail?.summaryAudio?.isActive == true
                ? .seconds(2)
                : .seconds(recordingDetail?.status == .processing ? 4 : 2)
            try? await Task.sleep(for: delay)
            guard !Task.isCancelled else { return }
            await load(
                recordingId: recordingId,
                apiClient: apiClient,
                fixtureDetail: fixtureDetail,
                showLoading: false
            )
        }
    }

    func startSummaryGeneration(recordingId id: String, apiClient: APIClient) async {
        generatingSummaryRecordingId = id
        defer {
            if generatingSummaryRecordingId == id {
                generatingSummaryRecordingId = nil
            }
        }

        do {
            let state = try await apiClient.startSummaryGeneration(recordingId: id)
            if recordingDetail?.id == id {
                recordingDetail = recordingDetail?.withSummaryGeneration(state)
            }
            await refreshPendingDetailIfNeeded(recordingId: id, apiClient: apiClient)
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
            if recordingDetail?.id == id {
                recordingDetail = recordingDetail?.withSummaryAudio(state)
            }
            await refreshPendingDetailIfNeeded(recordingId: id, apiClient: apiClient)
        } catch {
            self.error = error.userFacingMessage(context: .library)
        }
    }

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
            guard recordingDetail?.id == id else { return }
            try playSummaryAudioData(data, sourceId: id)
        } catch {
            self.error = error.userFacingMessage(context: .library)
        }
    }

    func generateSummary(recordingId id: String, apiClient: APIClient) async {
        await startSummaryGeneration(recordingId: id, apiClient: apiClient)
    }

    func deleteRecording(apiClient: APIClient, permanent: Bool = false) async -> Bool {
        guard let id = recordingDetail?.id else { return false }
        do {
            try await apiClient.deleteRecording(id: id, permanent: permanent)
            return true
        } catch {
            self.error = error.userFacingMessage(context: .library)
            return false
        }
    }

    func restoreRecording(apiClient: APIClient) async -> Bool {
        guard let id = recordingDetail?.id else { return false }
        do {
            _ = try await apiClient.restoreRecording(id: id)
            return true
        } catch {
            self.error = error.userFacingMessage(context: .library)
            return false
        }
    }

    func moveRecording(to folderId: String?, apiClient: APIClient) async -> Bool {
        guard let id = recordingDetail?.id else { return false }
        do {
            _ = try await apiClient.moveRecording(id: id, folderId: folderId)
            let refreshed = try await apiClient.getRecording(id: id)
            applyFetchedDetail(Self.localRecoveryDetail(for: refreshed))
            return true
        } catch {
            self.error = error.userFacingMessage(context: .library)
            return false
        }
    }

    func renameRecording(_ newTitle: String, apiClient: APIClient) async -> Bool {
        guard let id = recordingDetail?.id else { return false }
        let trimmed = newTitle.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return false }
        do {
            _ = try await apiClient.updateRecording(id: id, title: trimmed)
            let refreshed = try await apiClient.getRecording(id: id)
            applyFetchedDetail(Self.localRecoveryDetail(for: refreshed))
            return true
        } catch {
            self.error = error.userFacingMessage(context: .library)
            return false
        }
    }

    private func shouldAutoRefresh(detail: RecordingDetail?) -> Bool {
        if detail?.summaryGeneration?.isActive == true {
            return true
        }
        if detail?.summaryAudio?.isActive == true {
            return true
        }
        if detail?.automaticTitlePending == true {
            return true
        }

        switch detail?.status {
        case .pendingUpload, .uploading, .processing:
            return true
        case .ready, .failed, .none:
            return false
        }
    }

    private func playSummaryAudioData(_ data: Data, sourceId: String) throws {
        let player = try makeSummaryAudioPlayer(data)
        _ = player.prepareToPlay()
        guard player.play() else {
            throw NSError(
                domain: "MacSummaryAudioPlayback",
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

    private func applyFetchedDetail(_ localRecovery: LocalRecoveryResolution) {
        // Polls return byte-identical payloads most ticks; skipping the publish
        // keeps the memoized turn cache valid and avoids re-rendering a long
        // transcript for a no-op.
        if recordingDetail != localRecovery.detail {
            recordingDetail = localRecovery.detail
        }
        if localRecoveryManifest != localRecovery.manifest {
            localRecoveryManifest = localRecovery.manifest
        }
        if let recoveryError = localRecovery.error {
            self.error = recoveryError.userFacingMessage(context: .library)
        }
    }

    struct LocalRecoveryResolution: Sendable {
        let detail: RecordingDetail
        let manifest: RecordingBackupManifest?
        let error: Error?
    }

    nonisolated private static func localRecoveryDetail(
        for detail: RecordingDetail
    ) -> LocalRecoveryResolution {
        do {
            guard let manifest = try RecordingBackupStore.manifest(recordingId: detail.id) else {
                return LocalRecoveryResolution(detail: detail, manifest: nil, error: nil)
            }

            guard detail.segments.isEmpty else {
                return LocalRecoveryResolution(detail: detail, manifest: manifest, error: nil)
            }

            let segments: [Segment]
            do {
                segments = try localSegments(recordingId: detail.id, manifest: manifest)
            } catch {
                return LocalRecoveryResolution(detail: detail, manifest: manifest, error: error)
            }
            guard !segments.isEmpty else {
                return LocalRecoveryResolution(detail: detail, manifest: manifest, error: nil)
            }

            return LocalRecoveryResolution(
                detail: RecordingDetail(
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
                manifest: manifest,
                error: nil
            )
        } catch {
            return LocalRecoveryResolution(detail: detail, manifest: nil, error: error)
        }
    }

    nonisolated private static func localSegments(
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
}
