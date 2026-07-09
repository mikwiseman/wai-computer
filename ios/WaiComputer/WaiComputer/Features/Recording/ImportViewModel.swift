import Foundation
import UniformTypeIdentifiers
import WaiComputerKit

@MainActor
class ImportViewModel: ObservableObject {
    @Published var isUploading = false
    @Published var uploadingFilename: String?
    @Published var completedRecording: Recording?
    @Published var errorMessage: String?
    @Published var showFileImporter = false

    static let allowedContentTypes: [UTType] = {
        MediaImportSupport.importableExtensions
            .compactMap { UTType(filenameExtension: $0) }
    }()

    func handleFileSelection(result: Result<URL, Error>, apiClient: APIClient) {
        switch result {
        case .success(let fileURL):
            Task {
                await uploadFile(fileURL: fileURL, apiClient: apiClient)
            }
        case .failure(let error):
            errorMessage = error.userFacingMessage(context: .recording)
        }
    }

    private func uploadFile(fileURL: URL, apiClient: APIClient) async {
        guard fileURL.startAccessingSecurityScopedResource() else {
            errorMessage = OnboardingL10n.text(
                "Unable to access the selected file.",
                "Не удалось открыть выбранный файл.",
                language: LanguageManager.shared.current
            )
            return
        }
        defer { fileURL.stopAccessingSecurityScopedResource() }

        let filename = fileURL.deletingPathExtension().lastPathComponent
        uploadingFilename = filename
        isUploading = true

        // Videos upload as their audio track when AVFoundation can extract it
        // locally — a fraction of the bytes over cellular. Containers it can't
        // read upload whole; the server's ffmpeg pipeline extracts.
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
            let recording = try await apiClient.createRecording(title: filename, type: .note)
            recordingId = recording.id
            let detail = try await apiClient.uploadAudio(recordingId: recording.id, fileURL: uploadURL)

            if detail.status == .failed || detail.failureMessage?.isEmpty == false {
                let message = UserFacingErrorFormatter.displayMessage(
                    detail.failureMessage,
                    fallback: "Couldn't transcribe that audio file. Please try again.",
                    context: .recording
                )
                errorMessage = message
            } else {
                completedRecording = recording
            }
        } catch {
            if let recordingId {
                try? await apiClient.deleteRecording(id: recordingId, permanent: true)
            }
            errorMessage = error.userFacingMessage(context: .recording)
        }

        isUploading = false
        uploadingFilename = nil
    }

    func reset() {
        completedRecording = nil
        errorMessage = nil
        isUploading = false
        uploadingFilename = nil
    }
}
