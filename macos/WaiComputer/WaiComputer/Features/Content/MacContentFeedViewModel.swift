import Foundation
import WaiComputerKit

/// Drives the macOS Content feed: add-anything capture, kind filtering, list +
/// selected-item detail. Polls briefly after a create so the background summary
/// surfaces without a manual refresh.
@MainActor
final class MacContentFeedViewModel: ObservableObject {
    @Published var entries: [ItemListEntry] = []
    @Published var selectedId: String?
    @Published var selectedItem: Item?
    @Published var draft: String = ""
    @Published var kind: String?
    @Published var isLoading = false
    @Published var isAdding = false
    @Published var errorMessage: String?

    // Multi-select -> compare
    @Published var compareSelection: Set<String> = []
    @Published var activeComparisonId: String?
    @Published var isComparing = false

    let apiClient: APIClient

    init(apiClient: APIClient) {
        self.apiClient = apiClient
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
            activeComparisonId = set.id
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func clearComparison() {
        activeComparisonId = nil
        compareSelection.removeAll()
    }

    func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            let response = try await apiClient.listItems(kind: kind)
            entries = response.items
            if let selectedId, !entries.contains(where: { $0.id == selectedId }) {
                self.selectedId = nil
                selectedItem = nil
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func setKind(_ newKind: String?) async {
        kind = newKind
        selectedId = nil
        selectedItem = nil
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
            selectedId = created.id
            await selectItem(created.id)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func selectItem(_ id: String) async {
        do {
            selectedItem = try await apiClient.getItem(id: id)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func deleteSelected() async {
        guard let id = selectedId else { return }
        do {
            try await apiClient.deleteItem(id: id)
            selectedId = nil
            selectedItem = nil
            await load()
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
