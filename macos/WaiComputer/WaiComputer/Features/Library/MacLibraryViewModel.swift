import Foundation
import WaiComputerKit

@MainActor
class MacLibraryViewModel: ObservableObject {
    @Published var recordings: [Recording] = []
    @Published var isLoading = false
    @Published var error: String?

    func filteredRecordings(for type: RecordingType?) -> [Recording] {
        guard let type = type else { return recordings }
        return recordings.filter { $0.type == type }
    }

    func loadRecordings(apiClient: APIClient) async {
        isLoading = true
        error = nil

        do {
            recordings = try await apiClient.listRecordings(limit: 100)
        } catch {
            self.error = error.localizedDescription
        }

        isLoading = false
    }

    func deleteRecording(id: String, apiClient: APIClient) async {
        do {
            try await apiClient.deleteRecording(id: id)
            recordings.removeAll { $0.id == id }
        } catch {
            self.error = error.localizedDescription
        }
    }
}
