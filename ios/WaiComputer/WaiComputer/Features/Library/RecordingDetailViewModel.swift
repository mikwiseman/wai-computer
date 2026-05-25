import Foundation
import WaiComputerKit

@MainActor
class RecordingDetailViewModel: ObservableObject {
    @Published var detail: RecordingDetail?
    @Published var isLoading = false
    @Published var error: String?

    private var loadGeneration = 0

    func loadDetail(recordingId: String, apiClient: APIClient, showLoading: Bool = true) async {
        loadGeneration += 1
        let generation = loadGeneration
        let isSwitchingRecording = detail?.id != nil && detail?.id != recordingId
        if isSwitchingRecording {
            detail = nil
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
            detail = loadedDetail
        } catch {
            guard generation == loadGeneration else { return }
            self.error = error.userFacingMessage(context: .library)
        }
    }

    func generateSummary(recordingId: String, apiClient: APIClient) async {
        let generation = loadGeneration
        isLoading = true
        defer {
            if generation == loadGeneration {
                isLoading = false
            }
        }

        do {
            _ = try await apiClient.generateSummary(recordingId: recordingId)
            let loadedDetail = try await apiClient.getRecording(id: recordingId)
            guard generation == loadGeneration else { return }
            detail = loadedDetail
        } catch {
            guard generation == loadGeneration else { return }
            self.error = error.userFacingMessage(context: .library)
        }
    }

    func refreshPendingDetailIfNeeded(recordingId: String, apiClient: APIClient) async {
        guard detail?.id == recordingId else { return }
        guard shouldAutoRefresh(for: detail?.status) else { return }

        while !Task.isCancelled,
              detail?.id == recordingId,
              shouldAutoRefresh(for: detail?.status) {
            try? await Task.sleep(for: .seconds(detail?.status == .processing ? 4 : 2))
            guard !Task.isCancelled else { return }
            await loadDetail(recordingId: recordingId, apiClient: apiClient, showLoading: false)
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

    func loadScreenshotFixture(recordingId: String) {
        #if DEBUG
        loadGeneration += 1
        detail = IOSScreenshotFixtures.detail
        isLoading = false
        error = nil
        #endif
    }
}
