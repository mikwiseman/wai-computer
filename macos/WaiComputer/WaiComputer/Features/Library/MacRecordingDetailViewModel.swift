import Foundation
import WaiComputerKit

@MainActor
class MacRecordingDetailViewModel: ObservableObject {
    enum Tab: Hashable {
        case transcript, summary
    }

    @Published var recordingDetail: RecordingDetail?
    @Published var isLoading = false
    @Published var error: String?
    @Published var selectedTab: Tab = .transcript
    @Published private var generatingSummaryRecordingId: String?

    private var loadGeneration = 0

    init(initialDetail: RecordingDetail? = nil) {
        recordingDetail = initialDetail
    }

    func isGeneratingSummary(for recordingId: String) -> Bool {
        generatingSummaryRecordingId == recordingId
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
            selectedTab = .transcript
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
            guard generation == loadGeneration else { return }
            recordingDetail = detail
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
        guard shouldAutoRefresh(for: recordingDetail?.status) else { return }

        while !Task.isCancelled,
              recordingDetail?.id == recordingId,
              shouldAutoRefresh(for: recordingDetail?.status) {
            try? await Task.sleep(for: .seconds(recordingDetail?.status == .processing ? 4 : 2))
            guard !Task.isCancelled else { return }
            await load(
                recordingId: recordingId,
                apiClient: apiClient,
                fixtureDetail: fixtureDetail,
                showLoading: false
            )
        }
    }

    func generateSummary(recordingId id: String, apiClient: APIClient) async {
        generatingSummaryRecordingId = id
        defer {
            if generatingSummaryRecordingId == id {
                generatingSummaryRecordingId = nil
            }
        }

        do {
            _ = try await apiClient.generateSummary(recordingId: id)
            let detail = try await apiClient.getRecording(id: id)
            if recordingDetail?.id == id {
                recordingDetail = detail
                selectedTab = .summary
            }
        } catch {
            self.error = error.userFacingMessage(context: .library)
        }
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
            recordingDetail = try await apiClient.getRecording(id: id)
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
            recordingDetail = try await apiClient.getRecording(id: id)
            return true
        } catch {
            self.error = error.userFacingMessage(context: .library)
            return false
        }
    }

    private func shouldAutoRefresh(for status: RecordingStatus?) -> Bool {
        switch status {
        case .pendingUpload, .uploading, .processing:
            return true
        case .ready, .failed, .none:
            return false
        }
    }
}
