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

        var recordingId: String?
        do {
            let filename = fileURL.deletingPathExtension().lastPathComponent
            let recording = try await apiClient.createRecording(title: filename, type: .note)
            recordingId = recording.id
            let detail = try await apiClient.uploadAudio(recordingId: recording.id, fileURL: fileURL)

            if detail.status == .failed || detail.failureMessage?.isEmpty == false {
                errorMessage = UserFacingErrorFormatter.displayMessage(
                    detail.failureMessage,
                    fallback: "We couldn't transcribe that audio file right now. Please try again in a moment.",
                    context: .recording
                )
                showError = true
                importState = .error
            } else {
                importState = .done
            }
        } catch {
            if let recordingId {
                try? await apiClient.deleteRecording(id: recordingId, permanent: true)
            }
            errorMessage = error.userFacingMessage(context: .recording)
            showError = true
            importState = .error
        }

        isImporting = false
    }
}
