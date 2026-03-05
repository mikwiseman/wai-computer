import AppKit
import UniformTypeIdentifiers
import WaiComputerKit

enum ImportState: Equatable {
    case idle
    case importing
    case done
    case error
}

@MainActor
class MacImportViewModel: ObservableObject {
    @Published var importState: ImportState = .idle
    @Published var isImporting = false
    @Published var showError = false
    @Published var errorMessage = ""
    @Published var currentFilename = ""

    private let allowedTypes = ["mp3", "wav", "m4a", "ogg", "webm", "opus", "flac"]

    func pickAndUpload(apiClient: APIClient) async {
        let panel = NSOpenPanel()
        panel.title = "Import Audio File"
        panel.allowedContentTypes = allowedTypes.compactMap {
            .init(filenameExtension: $0)
        }
        panel.allowsMultipleSelection = false
        panel.canChooseDirectories = false

        let result = panel.runModal()
        guard result == .OK, let fileURL = panel.url else { return }

        let filename = fileURL.lastPathComponent
        currentFilename = filename
        isImporting = true
        importState = .importing

        do {
            let filename = fileURL.deletingPathExtension().lastPathComponent
            let recording = try await apiClient.createRecording(title: filename, type: .note)
            _ = try await apiClient.uploadAudio(recordingId: recording.id, fileURL: fileURL)
            importState = .done
        } catch {
            errorMessage = error.localizedDescription
            showError = true
            importState = .error
        }

        isImporting = false
    }
}
