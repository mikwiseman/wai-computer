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
        ["mp3", "wav", "m4a", "ogg", "webm", "opus", "flac"]
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
            errorMessage = "Unable to access the selected file."
            return
        }
        defer { fileURL.stopAccessingSecurityScopedResource() }

        let filename = fileURL.deletingPathExtension().lastPathComponent
        uploadingFilename = filename
        isUploading = true

        var recordingId: String?
        do {
            let recording = try await apiClient.createRecording(title: filename, type: .note)
            recordingId = recording.id
            let detail = try await apiClient.uploadAudio(recordingId: recording.id, fileURL: fileURL)

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
