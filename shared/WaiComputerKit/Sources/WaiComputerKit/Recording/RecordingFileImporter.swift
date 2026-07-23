import Foundation

public struct RecordingImportFailure: Error, Equatable, Sendable {
    public let filename: String
    public let message: String

    public init(filename: String, message: String) {
        self.filename = filename
        self.message = message
    }
}

public struct RecordingImportSummary: Equatable, Sendable {
    public let totalCount: Int
    public let recordings: [Recording]
    public let failures: [RecordingImportFailure]

    public init(
        totalCount: Int,
        recordings: [Recording],
        failures: [RecordingImportFailure]
    ) {
        self.totalCount = totalCount
        self.recordings = recordings
        self.failures = failures
    }

    public var importedCount: Int {
        recordings.count
    }

    /// Opening the detail automatically remains useful for one imported file.
    /// A batch stays in the library so the user can see every new recording.
    public var singleRecording: Recording? {
        totalCount == 1 && failures.isEmpty ? recordings.first : nil
    }

    public func failureMessage(language: OnboardingL10n.Language) -> String? {
        guard !failures.isEmpty else { return nil }

        let heading: String
        switch language {
        case .english:
            heading = importedCount > 0
                ? "Imported \(importedCount) of \(totalCount) files."
                : "No files were imported."
        case .russian:
            heading = importedCount > 0
                ? "Импортировано: \(importedCount) из \(totalCount)."
                : "Не удалось импортировать ни одного файла."
        }

        let failureHeading: String
        switch language {
        case .english:
            failureHeading = "Couldn’t import:"
        case .russian:
            failureHeading = "Не удалось импортировать:"
        }

        let details = failures
            .map { "• \($0.filename) — \($0.message)" }
            .joined(separator: "\n")
        return "\(heading)\n\n\(failureHeading)\n\(details)"
    }
}

public enum RecordingBatchImporter {
    /// Runs imports one at a time. Serial execution keeps memory and network
    /// use predictable for large media files, while collecting every failure
    /// so one bad file never prevents the remaining files from importing.
    @MainActor
    public static func importSequentially(
        files: [URL],
        onProgress: (_ index: Int, _ total: Int, _ file: URL) -> Void,
        importFile: (URL) async -> Result<Recording, RecordingImportFailure>
    ) async -> RecordingImportSummary {
        var recordings: [Recording] = []
        var failures: [RecordingImportFailure] = []

        for (offset, file) in files.enumerated() {
            onProgress(offset + 1, files.count, file)
            switch await importFile(file) {
            case .success(let recording):
                recordings.append(recording)
            case .failure(let failure):
                failures.append(failure)
            }
        }

        return RecordingImportSummary(
            totalCount: files.count,
            recordings: recordings,
            failures: failures
        )
    }
}

public enum RecordingFileImporter {
    public static func importFile(
        _ fileURL: URL,
        apiClient: APIClient,
        processingFailureFallback: String
    ) async -> Result<Recording, RecordingImportFailure> {
        let filename = fileURL.lastPathComponent
        let title = fileURL.deletingPathExtension().lastPathComponent

        // Reduce AVFoundation-readable videos to their audio track before
        // upload. Other supported containers stay intact for server demuxing.
        var uploadURL = fileURL
        var extractedTempURL: URL?
        if MediaImportSupport.isVideoExtension(fileURL.pathExtension),
           let extracted = await MediaAudioExtractor.extractAudioForUpload(source: fileURL) {
            uploadURL = extracted
            extractedTempURL = extracted
        }
        defer {
            if let extractedTempURL {
                try? FileManager.default.removeItem(at: extractedTempURL)
            }
        }

        var recordingId: String?
        do {
            let recording = try await apiClient.createRecording(
                title: title,
                titleMode: .preserve,
                type: .note
            )
            recordingId = recording.id
            let detail = try await apiClient.uploadAudio(
                recordingId: recording.id,
                fileURL: uploadURL
            )

            if detail.status == .failed || detail.failureMessage?.isEmpty == false {
                return .failure(
                    RecordingImportFailure(
                        filename: filename,
                        message: UserFacingErrorFormatter.displayMessage(
                            detail.failureMessage,
                            fallback: processingFailureFallback,
                            context: .recording
                        )
                    )
                )
            }
            return .success(recording)
        } catch {
            if let recordingId {
                try? await apiClient.deleteRecording(id: recordingId, permanent: true)
            }
            return .failure(
                RecordingImportFailure(
                    filename: filename,
                    message: error.userFacingMessage(context: .recording)
                )
            )
        }
    }
}
