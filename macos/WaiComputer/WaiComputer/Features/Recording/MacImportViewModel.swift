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
    @Published var currentFileIndex = 0
    @Published var totalFileCount = 0

    private let allowedTypes = MediaImportSupport.importableExtensions

    func pickAndUpload(apiClient: APIClient) async {
        let language = LanguageManager.shared.current
        let panel = NSOpenPanel()
        panel.title = RecordingCopy.importPanelTitle(language: language)
        panel.allowedContentTypes = allowedTypes.compactMap {
            .init(filenameExtension: $0)
        }
        panel.allowsMultipleSelection = true
        panel.canChooseDirectories = false

        let result = panel.runModal()
        guard result == .OK, !panel.urls.isEmpty else { return }
        await uploadFiles(panel.urls, apiClient: apiClient)
    }

    func uploadFiles(_ fileURLs: [URL], apiClient: APIClient) async {
        guard !isImporting, !fileURLs.isEmpty else { return }

        currentFilename = ""
        currentFileIndex = 0
        totalFileCount = fileURLs.count
        errorMessage = ""
        showError = false
        isImporting = true
        importState = .importing

        let language = LanguageManager.shared.current
        let summary = await RecordingBatchImporter.importSequentially(
            files: fileURLs,
            onProgress: { [weak self] index, total, file in
                self?.currentFileIndex = index
                self?.totalFileCount = total
                self?.currentFilename = file.lastPathComponent
            },
            importFile: { fileURL in
                await RecordingFileImporter.importFile(
                    fileURL,
                    apiClient: apiClient,
                    processingFailureFallback: RecordingCopy.importProcessingFailedFallback(
                        language: language
                    )
                )
            }
        )

        importState = summary.importedCount > 0 ? .done : .error
        if let message = summary.failureMessage(language: OnboardingL10n.language(for: language)) {
            errorMessage = message
            showError = true
        }
        isImporting = false
    }
}
