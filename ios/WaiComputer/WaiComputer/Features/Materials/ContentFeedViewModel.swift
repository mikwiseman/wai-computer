import Foundation
import UniformTypeIdentifiers
import WaiComputerKit

/// Drives the iOS Materials feed (the captured-items inbox): add-anything
/// capture, kind filtering, the item list, and multi-select → compare. Mirrors
/// the macOS MacContentFeedViewModel; the per-item detail loads itself on push.
@MainActor
final class ContentFeedViewModel: ObservableObject {
    @Published var entries: [ItemListEntry] = []
    @Published var kind: String?
    @Published var isLoading = false
    @Published var isAdding = false
    @Published var isUploadingFile = false
    @Published var errorMessage: String?
    @Published var statusMessage: String?

    // Unified "search everything" (recordings + items)
    @Published var query = ""
    @Published var searchResults: [UnifiedHit] = []
    @Published var isSearching = false

    // Multi-select → compare
    @Published var isSelecting = false
    @Published var compareSelection: Set<String> = []
    @Published var isComparing = false
    @Published var createdComparisonId: String?

    let apiClient: APIClient
    let folderId: String?

    init(apiClient: APIClient, folderId: String? = nil) {
        self.apiClient = apiClient
        self.folderId = folderId
    }

    static let importContentTypes: [UTType] = {
        var types: [UTType] = [
            .pdf, .plainText, .html, .rtf, .commaSeparatedText, .json, .audio, .movie
        ]
        for ext in ["md", "doc", "docx", "pptx", "xlsx", "mkv", "webm", "opus", "ogg"] {
            if let type = UTType(filenameExtension: ext) {
                types.append(type)
            }
        }
        return types
    }()

    func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            entries = try await apiClient.listItems(kind: kind, folderId: folderId).items
            errorMessage = nil
        } catch {
            errorMessage = error.userFacingMessage(context: .generic)
        }
    }

    func loadScreenshotFixtures() {
        #if DEBUG
        entries = IOSScreenshotFixtures.itemListResponse.items.filter { item in
            (folderId == nil || item.folderId == folderId)
                && (kind == nil || item.kind == kind)
        }
        isLoading = false
        isAdding = false
        isUploadingFile = false
        errorMessage = nil
        statusMessage = nil
        query = ""
        searchResults = []
        isSearching = false
        isSelecting = false
        compareSelection = []
        isComparing = false
        createdComparisonId = nil
        #endif
    }

    func setKind(_ newKind: String?) async {
        kind = newKind
        #if DEBUG
        if IOSTestingMode.current.isScreenshot {
            loadScreenshotFixtures()
            return
        }
        #endif
        await load()
    }

    private static func isURL(_ text: String) -> Bool {
        let lowered = text.lowercased()
        return lowered.hasPrefix("http://") || lowered.hasPrefix("https://")
    }

    /// Capture a pasted link or note. Returns the created item id on success.
    @discardableResult
    func add(_ text: String) async -> String? {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, !isAdding else { return nil }
        isAdding = true
        defer { isAdding = false }
        do {
            let created: Item
            if Self.isURL(trimmed) {
                created = try await apiClient.createItem(
                    source: "url",
                    kind: "article",
                    url: trimmed,
                    folderId: folderId
                )
            } else {
                created = try await apiClient.createItem(
                    source: "paste",
                    kind: "note",
                    body: trimmed,
                    folderId: folderId
                )
            }
            await load()
            return created.id
        } catch {
            errorMessage = error.userFacingMessage(context: .generic)
            return nil
        }
    }

    @discardableResult
    func uploadFile(_ fileURL: URL) async -> ItemUploadOutcome? {
        guard !isAdding, !isUploadingFile else { return nil }
        guard fileURL.startAccessingSecurityScopedResource() else {
            errorMessage = OnboardingL10n.text(
                "Unable to access the selected file.",
                "Не удалось открыть выбранный файл.",
                language: LanguageManager.shared.current
            )
            return nil
        }
        defer { fileURL.stopAccessingSecurityScopedResource() }

        isUploadingFile = true
        defer { isUploadingFile = false }

        let filename = fileURL.lastPathComponent
        do {
            let outcome = try await apiClient.uploadItem(fileURL: fileURL, folderId: folderId)
            switch outcome {
            case .item:
                statusMessage = OnboardingL10n.text(
                    folderId == nil
                        ? "Added \(filename) to Inbox."
                        : "Added \(filename) to this folder.",
                    folderId == nil
                        ? "\(filename) добавлен в Инбокс."
                        : "\(filename) добавлен в эту папку.",
                    language: LanguageManager.shared.current
                )
                await load()
            case .recording:
                statusMessage = OnboardingL10n.text(
                    folderId == nil
                        ? "Added \(filename) to Inbox. Transcription has started."
                        : "Added \(filename) to this folder. Transcription has started.",
                    folderId == nil
                        ? "\(filename) добавлен в Инбокс. Расшифровка началась."
                        : "\(filename) добавлен в эту папку. Расшифровка началась.",
                    language: LanguageManager.shared.current
                )
            }
            errorMessage = nil
            return outcome
        } catch {
            errorMessage = error.userFacingMessage(context: .generic)
            return nil
        }
    }

    var isSearchActive: Bool {
        !query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    /// Unified search across recordings + items (RRF). Empty query clears results.
    func search() async {
        let q = query.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !q.isEmpty else {
            searchResults = []
            errorMessage = nil
            return
        }
        isSearching = true
        defer { isSearching = false }
        do {
            searchResults = try await apiClient.unifiedSearch(query: q).results
            errorMessage = nil
        } catch {
            searchResults = []
            errorMessage = error.userFacingMessage(context: .generic)
        }
    }

    func delete(_ id: String) async {
        do {
            try await apiClient.deleteItem(id: id)
            entries.removeAll { $0.id == id }
        } catch {
            errorMessage = error.userFacingMessage(context: .generic)
        }
    }

    @discardableResult
    func moveItem(_ id: String, to folderId: String?) async -> Bool {
        do {
            _ = try await apiClient.moveItem(id: id, folderId: folderId)
            statusMessage = OnboardingL10n.text(
                folderId == nil ? "Removed from folder." : "Moved to folder.",
                folderId == nil ? "Убрано из папки." : "Перемещено в папку.",
                language: LanguageManager.shared.current
            )
            errorMessage = nil
            await load()
            return true
        } catch {
            errorMessage = error.userFacingMessage(context: .generic)
            return false
        }
    }

    // MARK: - Compare

    func toggleSelecting() {
        isSelecting.toggle()
        if !isSelecting { compareSelection.removeAll() }
    }

    func toggleCompare(_ id: String) {
        if compareSelection.contains(id) {
            compareSelection.remove(id)
        } else {
            compareSelection.insert(id)
        }
    }

    var canCompare: Bool { compareSelection.count >= 2 }

    func compareSelected() async {
        guard canCompare, !isComparing else { return }
        isComparing = true
        defer { isComparing = false }
        do {
            let set = try await apiClient.createComparison(itemIds: Array(compareSelection))
            createdComparisonId = set.id
            isSelecting = false
            compareSelection.removeAll()
        } catch {
            errorMessage = error.userFacingMessage(context: .generic)
        }
    }
}
