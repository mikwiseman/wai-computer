import Foundation
import UniformTypeIdentifiers
import WaiComputerKit

@MainActor
class ImportViewModel: ObservableObject {
    @Published var isUploading = false
    @Published var uploadingFilename: String?
    @Published var currentFileIndex = 0
    @Published var totalFileCount = 0
    @Published private(set) var importSummary: RecordingImportSummary?
    @Published var errorMessage: String?
    @Published var showFileImporter = false

    static let allowedContentTypes: [UTType] = {
        MediaImportSupport.importableExtensions
            .compactMap { UTType(filenameExtension: $0) }
    }()

    func handleFileSelection(result: Result<[URL], Error>, apiClient: APIClient) {
        switch result {
        case .success(let fileURLs):
            Task {
                await uploadFiles(fileURLs, apiClient: apiClient)
            }
        case .failure(let error):
            errorMessage = error.userFacingMessage(context: .recording)
        }
    }

    func uploadFiles(_ fileURLs: [URL], apiClient: APIClient) async {
        guard !isUploading, !fileURLs.isEmpty else { return }

        uploadingFilename = nil
        currentFileIndex = 0
        totalFileCount = fileURLs.count
        importSummary = nil
        errorMessage = nil
        isUploading = true

        let language = LanguageManager.shared.current
        let summary = await RecordingBatchImporter.importSequentially(
            files: fileURLs,
            onProgress: { [weak self] index, total, file in
                self?.currentFileIndex = index
                self?.totalFileCount = total
                self?.uploadingFilename = file.lastPathComponent
            },
            importFile: { fileURL in
                guard fileURL.startAccessingSecurityScopedResource() else {
                    return .failure(
                        RecordingImportFailure(
                            filename: fileURL.lastPathComponent,
                            message: OnboardingL10n.text(
                                "Unable to access the selected file.",
                                "Не удалось открыть выбранный файл.",
                                language: language
                            )
                        )
                    )
                }
                defer { fileURL.stopAccessingSecurityScopedResource() }

                return await RecordingFileImporter.importFile(
                    fileURL,
                    apiClient: apiClient,
                    processingFailureFallback: OnboardingL10n.text(
                        "Couldn’t transcribe that file. Please try again.",
                        "Не удалось расшифровать файл. Попробуйте ещё раз.",
                        language: language
                    )
                )
            }
        )

        errorMessage = summary.failureMessage(language: OnboardingL10n.language(for: language))
        isUploading = false
        uploadingFilename = nil
        importSummary = summary
    }

    func consumeImportSummary() {
        importSummary = nil
    }
}
