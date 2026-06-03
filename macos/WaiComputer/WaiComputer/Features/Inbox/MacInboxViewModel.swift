import Foundation
import UniformTypeIdentifiers
import WaiComputerKit

@MainActor
final class MacInboxViewModel: ObservableObject {
    @Published var rows: [InboxRow] = []
    @Published var sourceKind: InboxSourceKind?
    @Published var statusFilter: InboxStatusFilter?
    @Published var nextCursor: String?
    @Published var isLoading = false
    @Published var isLoadingMore = false
    @Published var isAdding = false
    @Published var draft = ""
    @Published var errorMessage: String?
    @Published var statusMessage: String?

    let apiClient: APIClient

    init(apiClient: APIClient) {
        self.apiClient = apiClient
    }

    func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            let response = try await apiClient.listInbox(
                sourceKind: sourceKind,
                status: statusFilter,
                limit: 50
            )
            rows = response.rows
            nextCursor = response.nextCursor
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func loadMore() async {
        guard let nextCursor, !isLoadingMore else { return }
        isLoadingMore = true
        defer { isLoadingMore = false }
        do {
            let response = try await apiClient.listInbox(
                sourceKind: sourceKind,
                status: statusFilter,
                limit: 50,
                cursor: nextCursor
            )
            rows.append(contentsOf: response.rows)
            self.nextCursor = response.nextCursor
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func setSourceKind(_ next: InboxSourceKind?) async {
        sourceKind = next
        nextCursor = nil
        await load()
    }

    func setStatusFilter(_ next: InboxStatusFilter?) async {
        statusFilter = next
        nextCursor = nil
        await load()
    }

    func addDraft() async -> InboxRow? {
        let trimmed = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, !isAdding else { return nil }
        isAdding = true
        defer { isAdding = false }
        do {
            let created: Item
            if trimmed.lowercased().hasPrefix("http://")
                || trimmed.lowercased().hasPrefix("https://") {
                created = try await apiClient.createItem(
                    source: "url",
                    kind: "article",
                    url: trimmed
                )
            } else {
                created = try await apiClient.createItem(
                    source: "paste",
                    kind: "note",
                    body: trimmed
                )
            }
            draft = ""
            await load()
            return rows.first { $0.id == "item:\(created.id)" }
        } catch {
            errorMessage = error.localizedDescription
            return nil
        }
    }

    func uploadFile(_ url: URL) async -> InboxRow? {
        guard !isAdding else { return nil }
        isAdding = true
        defer { isAdding = false }

        let scoped = url.startAccessingSecurityScopedResource()
        defer { if scoped { url.stopAccessingSecurityScopedResource() } }

        do {
            let outcome = try await apiClient.uploadItem(fileURL: url)
            switch outcome {
            case .item(let item):
                statusMessage = nil
                await load()
                return rows.first { $0.id == "item:\(item.id)" }
            case .recording(status: _, recordingId: let recordingId):
                errorMessage = nil
                statusMessage = OnboardingL10n.text(
                    "Transcribing — the recording is now in Inbox.",
                    "Расшифровываем — запись уже в Инбоксе.",
                    language: LanguageManager.shared.current
                )
                await load()
                return rows.first { $0.id == "recording:\(recordingId)" } ?? InboxRow(
                    id: "recording:\(recordingId)",
                    sourceKind: .recording,
                    sourceId: recordingId,
                    detail: InboxDetailRef(kind: .recording, id: recordingId),
                    title: url.deletingPathExtension().lastPathComponent,
                    sourceLabel: "Recording",
                    sublabel: "note",
                    activityAt: Date(),
                    createdAt: Date(),
                    updatedAt: nil,
                    occurredAt: Date(),
                    status: .processing,
                    sourceStatus: "processing",
                    error: nil,
                    folderId: nil,
                    durationSeconds: nil,
                    language: nil,
                    hasSummary: false,
                    isStarred: false,
                    isPinned: false,
                    isArchived: false,
                    isTrashed: false
                )
            }
        } catch {
            errorMessage = error.localizedDescription
            return nil
        }
    }

    func newChat() async -> InboxRow? {
        guard !isAdding else { return nil }
        isAdding = true
        defer { isAdding = false }
        do {
            let chat = try await apiClient.createCompanionChat()
            await load()
            return rows.first { $0.id == "chat:\(chat.id)" } ?? InboxRow(
                id: "chat:\(chat.id)",
                sourceKind: .chat,
                sourceId: chat.id,
                detail: InboxDetailRef(kind: .chat, id: chat.id),
                title: chat.title,
                sourceLabel: "Wai chat",
                sublabel: "Chat",
                activityAt: chat.lastMessageAt ?? chat.createdAt,
                createdAt: chat.createdAt,
                updatedAt: chat.updatedAt,
                occurredAt: chat.lastMessageAt,
                status: .ready,
                sourceStatus: nil,
                error: nil,
                folderId: nil,
                durationSeconds: nil,
                language: nil,
                hasSummary: nil,
                isStarred: false,
                isPinned: chat.pinnedAt != nil,
                isArchived: false,
                isTrashed: false
            )
        } catch {
            errorMessage = error.localizedDescription
            return nil
        }
    }
}
