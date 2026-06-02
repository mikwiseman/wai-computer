import Foundation
import WaiComputerKit

/// Drives the macOS Content feed: add-anything capture, kind filtering, list +
/// active-item detail. Polls briefly after a create so the background summary
/// surfaces without a manual refresh.
@MainActor
final class MacContentFeedViewModel: ObservableObject {
    @Published var entries: [ItemListEntry] = []
    @Published var activeItemId: String?
    @Published var activeItem: Item?
    @Published var draft: String = ""
    @Published var kind: String?
    @Published var isLoading = false
    @Published var isAdding = false
    @Published var errorMessage: String?
    // Non-error notice (e.g. an audio/video upload now transcribing in the background).
    @Published var statusMessage: String?

    let apiClient: APIClient

    init(apiClient: APIClient) {
        self.apiClient = apiClient
    }

    func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            let response = try await apiClient.listItems(kind: kind)
            entries = response.items
            if let activeItemId, !entries.contains(where: { $0.id == activeItemId }) {
                self.activeItemId = nil
                activeItem = nil
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func setKind(_ newKind: String?) async {
        kind = newKind
        activeItemId = nil
        activeItem = nil
        await load()
    }

    private static let urlPredicate: (String) -> Bool = { text in
        let lowered = text.lowercased()
        return lowered.hasPrefix("http://") || lowered.hasPrefix("https://")
    }

    func addDraft() async {
        let trimmed = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, !isAdding else { return }
        isAdding = true
        defer { isAdding = false }
        do {
            let created: Item
            if Self.urlPredicate(trimmed) {
                created = try await apiClient.createItem(source: "url", kind: "article", url: trimmed)
            } else {
                created = try await apiClient.createItem(source: "paste", kind: "note", body: trimmed)
            }
            draft = ""
            await load()
            activeItemId = created.id
            await openItem(created.id)
            // Poll in the background so the Add button frees up immediately
            // while the summary + key-moments land (honors the doc comment).
            let createdId = created.id
            Task { [weak self] in await self?.pollUntilProcessed(createdId) }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    /// After a create, poll the new item until its summary lands (or it needs
    /// input / failed) so the "add → instant summary" payoff surfaces without a
    /// manual refresh. Capped at ~60s; bails if the user opens another item.
    private func pollUntilProcessed(_ id: String) async {
        for _ in 0..<30 {
            try? await Task.sleep(nanoseconds: 2_000_000_000)
            guard activeItemId == id else { return }
            guard let item = try? await apiClient.getItem(id: id) else { continue }
            activeItem = item
            if item.summary?.summary != nil
                || item.state == "needs_input"
                || item.state == "failed" {
                await load()
                return
            }
        }
        await load()
    }

    func uploadFile(_ url: URL) async {
        guard !isAdding else { return }
        isAdding = true
        defer { isAdding = false }
        // App Sandbox is off on macOS, but honor the security scope if present
        // (e.g. a file dropped/imported with a scoped URL).
        let scoped = url.startAccessingSecurityScopedResource()
        defer { if scoped { url.stopAccessingSecurityScopedResource() } }
        do {
            let outcome = try await apiClient.uploadItem(fileURL: url)
            switch outcome {
            case .recording:
                // Audio/video → background transcription; it surfaces under Recordings.
                errorMessage = nil
                statusMessage = OnboardingL10n.text(
                    "Transcribing — it'll appear in your recordings shortly.",
                    "Расшифровываем — скоро появится в ваших записях.",
                    language: LanguageManager.shared.current
                )
            case .item(let created):
                statusMessage = nil
                await load()
                activeItemId = created.id
                await openItem(created.id)
                let createdId = created.id
                Task { [weak self] in await self?.pollUntilProcessed(createdId) }
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func openItem(_ id: String) async {
        activeItemId = id
        do {
            activeItem = try await apiClient.getItem(id: id)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func deleteActiveItem() async {
        guard let id = activeItemId else { return }
        do {
            try await apiClient.deleteItem(id: id)
            activeItemId = nil
            activeItem = nil
            await load()
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
