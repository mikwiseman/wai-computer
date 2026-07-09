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

    private let allowedTypes = MediaImportSupport.importableExtensions

    func pickAndUpload(apiClient: APIClient) async {
        let language = LanguageManager.shared.current
        let panel = NSOpenPanel()
        panel.title = RecordingCopy.importPanelTitle(language: language)
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

        // Videos upload as their audio track when AVFoundation can extract it
        // locally (mp4/mov/m4v) — a fraction of the bytes. Containers it can't
        // read (mkv/avi/…) upload whole; the server's ffmpeg pipeline extracts.
        var uploadURL = fileURL
        var extractedTempURL: URL?
        if MediaImportSupport.isVideoExtension(fileURL.pathExtension) {
            if let extracted = await MediaAudioExtractor.extractAudioForUpload(source: fileURL) {
                uploadURL = extracted
                extractedTempURL = extracted
            }
        }
        defer {
            if let extractedTempURL {
                try? FileManager.default.removeItem(at: extractedTempURL)
            }
        }

        var recordingId: String?
        do {
            let filename = fileURL.deletingPathExtension().lastPathComponent
            let recording = try await apiClient.createRecording(title: filename, type: .note)
            recordingId = recording.id
            let detail = try await apiClient.uploadAudio(recordingId: recording.id, fileURL: uploadURL)

            if detail.status == .failed || detail.failureMessage?.isEmpty == false {
                errorMessage = UserFacingErrorFormatter.displayMessage(
                    detail.failureMessage,
                    fallback: RecordingCopy.importProcessingFailedFallback(language: language),
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
