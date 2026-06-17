import Foundation
import WaiComputerKit

@MainActor
final class MacSchemesViewModel: ObservableObject {
    @Published var schemes: [Scheme] = []
    @Published var selectedScheme: Scheme?
    @Published var prompt = ""
    @Published var layout = SchemeCanvasLayout()
    @Published var isLoading = false
    @Published var isCreating = false
    @Published var isRefreshing = false
    @Published var errorMessage: String?

    private let apiClient: APIClient

    init(apiClient: APIClient) {
        self.apiClient = apiClient
    }

    func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            let response = try await apiClient.listSchemes()
            schemes = response.schemes
            if let selectedScheme,
               let updated = response.schemes.first(where: { $0.id == selectedScheme.id }) {
                self.selectedScheme = updated
                layout = updated.layout
            } else {
                selectedScheme = response.schemes.first
                layout = response.schemes.first?.layout ?? SchemeCanvasLayout()
            }
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func select(_ scheme: Scheme) async {
        selectedScheme = scheme
        layout = scheme.layout
        do {
            let detail = try await apiClient.getScheme(id: scheme.id)
            guard selectedScheme?.id == scheme.id else { return }
            replace(detail)
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func create() async {
        let trimmed = prompt.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, !isCreating else { return }
        isCreating = true
        defer { isCreating = false }
        do {
            let created = try await apiClient.createScheme(prompt: trimmed)
            prompt = ""
            schemes.removeAll { $0.id == created.id }
            schemes.insert(created, at: 0)
            selectedScheme = created
            layout = created.layout
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func refreshSelected() async {
        guard let selectedScheme, !isRefreshing else { return }
        isRefreshing = true
        defer { isRefreshing = false }
        do {
            let revision = try await apiClient.refreshScheme(id: selectedScheme.id)
            let updated = Scheme(
                id: selectedScheme.id,
                spaceId: selectedScheme.spaceId,
                title: selectedScheme.title,
                prompt: selectedScheme.prompt,
                schemeType: selectedScheme.schemeType,
                origin: selectedScheme.origin,
                status: selectedScheme.status,
                sourceScope: selectedScheme.sourceScope,
                layout: layout,
                currentRevisionId: revision.id,
                currentRevision: revision,
                createdAt: selectedScheme.createdAt,
                updatedAt: selectedScheme.updatedAt
            )
            replace(updated)
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func updateNodePosition(nodeId: String, position: SchemePosition) async {
        guard let selectedScheme else { return }
        var nextLayout = layout
        nextLayout.nodePositions[nodeId] = position
        await updateLayout(nextLayout, selectedScheme: selectedScheme)
    }

    func updateLayout(_ nextLayout: SchemeCanvasLayout) async {
        guard let selectedScheme else { return }
        await updateLayout(nextLayout, selectedScheme: selectedScheme)
    }

    private func updateLayout(_ nextLayout: SchemeCanvasLayout, selectedScheme: Scheme) async {
        layout = nextLayout
        do {
            let updated = try await apiClient.updateSchemeLayout(id: selectedScheme.id, layout: nextLayout)
            replace(updated)
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func replace(_ scheme: Scheme) {
        selectedScheme = scheme
        layout = scheme.layout
        if let index = schemes.firstIndex(where: { $0.id == scheme.id }) {
            schemes[index] = scheme
        } else {
            schemes.insert(scheme, at: 0)
        }
    }
}
