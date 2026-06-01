import Foundation
import WaiComputerKit

/// Drives the iOS Content feed (the "Brain" tab home): add-anything capture,
/// kind filtering, the item list, and multi-select → compare. Mirrors the
/// macOS MacContentFeedViewModel; the per-item detail loads itself on push.
@MainActor
final class ContentFeedViewModel: ObservableObject {
    @Published var entries: [ItemListEntry] = []
    @Published var kind: String?
    @Published var isLoading = false
    @Published var isAdding = false
    @Published var errorMessage: String?
    @Published var pendingReviewCount = 0

    // Multi-select → compare
    @Published var isSelecting = false
    @Published var compareSelection: Set<String> = []
    @Published var isComparing = false
    @Published var createdComparisonId: String?

    let apiClient: APIClient

    init(apiClient: APIClient) {
        self.apiClient = apiClient
    }

    func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            entries = try await apiClient.listItems(kind: kind).items
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
        // Best-effort review badge; never blocks the feed.
        if let count = try? await apiClient.listMemoryProposals(status: "pending").pendingCount {
            pendingReviewCount = count
        }
    }

    func setKind(_ newKind: String?) async {
        kind = newKind
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
                created = try await apiClient.createItem(source: "url", kind: "article", url: trimmed)
            } else {
                created = try await apiClient.createItem(source: "paste", kind: "note", body: trimmed)
            }
            await load()
            return created.id
        } catch {
            errorMessage = error.localizedDescription
            return nil
        }
    }

    func delete(_ id: String) async {
        do {
            try await apiClient.deleteItem(id: id)
            entries.removeAll { $0.id == id }
        } catch {
            errorMessage = error.localizedDescription
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
            errorMessage = error.localizedDescription
        }
    }
}
