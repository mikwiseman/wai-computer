import Foundation
import UniformTypeIdentifiers
import WaiComputerKit

struct PendingInboxUploadFile: Equatable {
    let url: URL
    let filename: String
    let byteCount: Int64?
    let typeDescription: String?
}

struct MacInboxRowsRevision: Equatable {
    let value: Int
    let appendedFromIndex: Int?

    init(value: Int = 0, appendedFromIndex: Int? = nil) {
        self.value = value
        self.appendedFromIndex = appendedFromIndex
    }

    func replacingRows() -> MacInboxRowsRevision {
        MacInboxRowsRevision(value: value + 1, appendedFromIndex: nil)
    }

    func appendingRows(from index: Int) -> MacInboxRowsRevision {
        MacInboxRowsRevision(value: value + 1, appendedFromIndex: index)
    }
}

enum InboxUploadPhase: Equatable {
    case idle
    case selected
    case preparing(String)
    case uploading(String)
    case processing(String)
    case added(String)
    case failed(String)

    var isWorking: Bool {
        switch self {
        case .preparing, .uploading:
            return true
        case .idle, .selected, .processing, .added, .failed:
            return false
        }
    }

    var isError: Bool {
        switch self {
        case .failed:
            return true
        case .idle, .selected, .preparing, .uploading, .processing, .added:
            return false
        }
    }

    var message: String? {
        switch self {
        case .idle, .selected:
            return nil
        case .preparing(let message),
             .uploading(let message),
             .processing(let message),
             .added(let message),
             .failed(let message):
            return message
        }
    }
}

@MainActor
final class MacInboxViewModel: ObservableObject {
    @Published var rows: [InboxRow] = []
    @Published var sourceKind: InboxSourceKind?
    @Published var nextCursor: String?
    @Published var isLoading = false
    @Published var isLoadingMore = false
    @Published var isAdding = false
    @Published var draft = ""
    @Published var errorMessage: String?
    @Published var statusMessage: String?
    @Published var selectedUploadFile: PendingInboxUploadFile?
    @Published var uploadPhase: InboxUploadPhase = .idle
    private(set) var rowsRevision = MacInboxRowsRevision()

    let apiClient: APIClient
    private var folderId: String?
    private var selectedUploadFileHasScopedAccess = false

    init(apiClient: APIClient, sourceKind: InboxSourceKind? = nil, folderId: String? = nil) {
        self.apiClient = apiClient
        self.sourceKind = sourceKind
        self.folderId = folderId
    }

    func configureScope(sourceKind: InboxSourceKind?, folderId: String?) async {
        guard self.sourceKind != sourceKind || self.folderId != folderId else { return }
        self.sourceKind = sourceKind
        self.folderId = folderId
        nextCursor = nil
        await load()
    }

    /// Stale-response guard. Rapid segment/filter switches start overlapping
    /// loads (the MainActor is released at the network await), and whichever
    /// resolved last used to win — painting the wrong filter's rows and
    /// installing its cursor. Only the newest request may land results.
    private var loadGeneration = 0

    func load() async {
        loadGeneration += 1
        let generation = loadGeneration
        isLoading = true
        defer {
            // A newer load owns the spinner now — don't flip it off under it.
            if generation == loadGeneration {
                isLoading = false
            }
        }
        do {
            let response = try await apiClient.listInbox(
                sourceKind: sourceKind,
                folderId: folderId,
                limit: 50
            )
            guard generation == loadGeneration else { return }
            errorMessage = nil
            rowsRevision = rowsRevision.replacingRows()
            rows = response.rows
            nextCursor = response.nextCursor
        } catch {
            guard generation == loadGeneration else { return }
            errorMessage = error.localizedDescription
        }
    }

    func loadMore() async {
        guard let nextCursor, !isLoadingMore else { return }
        let generation = loadGeneration
        isLoadingMore = true
        defer { isLoadingMore = false }
        do {
            let response = try await apiClient.listInbox(
                sourceKind: sourceKind,
                folderId: folderId,
                limit: 50,
                cursor: nextCursor
            )
            guard generation == loadGeneration else { return }
            errorMessage = nil
            rowsRevision = rowsRevision.appendingRows(from: rows.count)
            rows.append(contentsOf: response.rows)
            self.nextCursor = response.nextCursor
        } catch {
            guard generation == loadGeneration else { return }
            errorMessage = error.localizedDescription
        }
    }

    func setSourceKind(_ next: InboxSourceKind?) async {
        sourceKind = next
        nextCursor = nil
        await load()
    }

    func addDraft() async -> InboxDetailRef? {
        let trimmed = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, !isAdding else { return nil }
        isAdding = true
        defer { isAdding = false }
        do {
            let created: Item
            let isURL = trimmed.lowercased().hasPrefix("http://")
                || trimmed.lowercased().hasPrefix("https://")
            if trimmed.lowercased().hasPrefix("http://")
                || trimmed.lowercased().hasPrefix("https://") {
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
            let detail = InboxDetailRef(kind: .item, id: created.id)
            draft = ""
            errorMessage = nil
            // Scope-aware copy: in a folder the item lands in that folder,
            // so the toast must not claim it went to Inbox.
            statusMessage = OnboardingL10n.text(
                folderId == nil
                    ? (isURL ? "Link added to Inbox." : "Text added to Inbox.")
                    : (isURL ? "Link added to this folder." : "Text added to this folder."),
                folderId == nil
                    ? (isURL ? "Ссылка добавлена в Инбокс." : "Текст добавлен в Инбокс.")
                    : (isURL ? "Ссылка добавлена в эту папку." : "Текст добавлен в эту папку."),
                language: LanguageManager.shared.current
            )
            await load()
            return rows.first { $0.id == "item:\(created.id)" }?.detail ?? detail
        } catch {
            errorMessage = error.localizedDescription
            return nil
        }
    }

    func selectUploadFile(_ url: URL) {
        releaseSelectedUploadAccess()
        selectedUploadFile = nil

        let scoped = url.startAccessingSecurityScopedResource()

        do {
            let values = try url.resourceValues(forKeys: [
                .fileSizeKey,
                .localizedTypeDescriptionKey,
                .contentTypeKey
            ])
            selectedUploadFile = PendingInboxUploadFile(
                url: url,
                filename: url.lastPathComponent,
                byteCount: values.fileSize.map(Int64.init),
                typeDescription: values.localizedTypeDescription
                    ?? values.contentType?.localizedDescription
            )
            selectedUploadFileHasScopedAccess = scoped
            uploadPhase = .selected
            errorMessage = nil
            statusMessage = nil
        } catch {
            if scoped {
                url.stopAccessingSecurityScopedResource()
            }
            selectedUploadFileHasScopedAccess = false
            selectedUploadFile = nil
            uploadPhase = .failed(error.localizedDescription)
            errorMessage = error.localizedDescription
        }
    }

    func clearSelectedUploadFile() {
        guard !uploadPhase.isWorking else { return }
        releaseSelectedUploadAccess()
        selectedUploadFile = nil
        uploadPhase = .idle
    }

    func submitSelectedUploadFile() async -> InboxDetailRef? {
        guard let selectedUploadFile else { return nil }
        return await uploadFile(selectedUploadFile)
    }

    private func uploadFile(_ file: PendingInboxUploadFile) async -> InboxDetailRef? {
        guard !isAdding else { return nil }
        isAdding = true
        defer { isAdding = false }
        uploadPhase = .preparing(OnboardingL10n.text(
            "Preparing \(file.filename)...",
            "Готовим \(file.filename)...",
            language: LanguageManager.shared.current
        ))

        let hasHeldAccess = selectedUploadFile?.url == file.url && selectedUploadFileHasScopedAccess
        let scoped = hasHeldAccess ? false : file.url.startAccessingSecurityScopedResource()
        defer { if scoped { file.url.stopAccessingSecurityScopedResource() } }

        do {
            uploadPhase = .uploading(OnboardingL10n.text(
                "Uploading \(file.filename)...",
                "Загружаем \(file.filename)...",
                language: LanguageManager.shared.current
            ))
            let outcome = try await apiClient.uploadItem(fileURL: file.url, folderId: folderId)
            switch outcome {
            case .item(let item):
                let detail = InboxDetailRef(kind: .item, id: item.id)
                let message = OnboardingL10n.text(
                    folderId == nil
                        ? "Added \(file.filename) to Inbox."
                        : "Added \(file.filename) to this folder.",
                    folderId == nil
                        ? "\(file.filename) добавлен в Инбокс."
                        : "\(file.filename) добавлен в эту папку.",
                    language: LanguageManager.shared.current
                )
                errorMessage = nil
                statusMessage = message
                uploadPhase = .added(message)
                releaseSelectedUploadAccess()
                selectedUploadFile = nil
                await load()
                return rows.first { $0.id == "item:\(item.id)" }?.detail ?? detail
            case .recording(status: _, recordingId: let recordingId):
                let detail = InboxDetailRef(kind: .recording, id: recordingId)
                let message = OnboardingL10n.text(
                    folderId == nil
                        ? "Added \(file.filename) to Inbox. Transcription has started."
                        : "Added \(file.filename) to this folder. Transcription has started.",
                    folderId == nil
                        ? "\(file.filename) добавлен в Инбокс. Расшифровка началась."
                        : "\(file.filename) добавлен в эту папку. Расшифровка началась.",
                    language: LanguageManager.shared.current
                )
                errorMessage = nil
                statusMessage = message
                uploadPhase = .processing(message)
                releaseSelectedUploadAccess()
                selectedUploadFile = nil
                await load()
                return rows.first { $0.id == "recording:\(recordingId)" }?.detail ?? detail
            }
        } catch {
            uploadPhase = .failed(error.localizedDescription)
            errorMessage = error.localizedDescription
            return nil
        }
    }

    private func releaseSelectedUploadAccess() {
        guard selectedUploadFileHasScopedAccess else { return }
        selectedUploadFile?.url.stopAccessingSecurityScopedResource()
        selectedUploadFileHasScopedAccess = false
    }

    func newChat() async -> InboxDetailRef? {
        guard !isAdding else { return nil }
        isAdding = true
        defer { isAdding = false }
        do {
            let chat = try await apiClient.createCompanionChat()
            let detail = InboxDetailRef(kind: .chat, id: chat.id)
            await load()
            return rows.first { $0.id == "chat:\(chat.id)" }?.detail ?? detail
        } catch {
            errorMessage = error.localizedDescription
            return nil
        }
    }
}
