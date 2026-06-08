import Foundation
import WaiComputerKit

/// Filter for the living Pages list (entities). Mirrors the macOS `BrainPageFilter`.
enum BrainPageFilter: String, CaseIterable {
    case all
    case person
    case project
    case topic
}

/// The iOS Brain view model — a faithful port of `MacBrainViewModel`.
///
/// Drives the unified Brain surface: a live source mirror, generated maps,
/// an askable Brain (`askBrain`), the browsable living Pages (entities) and
/// their rich dossiers (`getEntityPage`), plus the curated Brain spaces.
/// The data/API layer is identical to macOS — only the SwiftUI views differ.
@MainActor
final class BrainViewModel: ObservableObject {
    struct SelectedEntity: Equatable {
        let id: String
        let name: String
    }

    @Published var loading = true
    @Published var errorMessage: String?

    // Live mirror + generated maps
    @Published var mirror: BrainMapProjection?
    @Published var brainOverview: BrainOverview?
    @Published var brainSyncResult: BrainSyncResult?
    @Published var maps: [BrainMap] = []
    @Published var selectedMapId = "mirror"
    @Published var lensPrompt = ""
    @Published var creatingLens = false
    @Published var refreshingMapId: String?
    @Published var linkingBrainSources = false
    @Published var brainQuestion = ""
    @Published var brainAnswer: BrainAnswer?
    @Published var askingBrain = false
    @Published var brainAskError: String?

    // Pages (entities)
    @Published var entities: [Entity] = []
    @Published var pageFilter: BrainPageFilter = .all
    @Published var searchText = ""
    @Published var selectedEntity: SelectedEntity?
    @Published var entityPage: EntityPage?
    @Published var pageLoading = false
    @Published var pageError: String?

    // Curated knowledge (Brain spaces)
    @Published var spaces: [BrainSpace] = []
    @Published var selectedSpaceId = ""
    @Published var spaceHome: BrainSpaceHome?
    @Published var spaceReviewPacks: [BrainReviewPack] = []
    @Published var spaceError: String?
    @Published var sharing = false
    @Published var shareMessage: String?
    @Published var exportMessage: String?
    @Published var actingSpaceReviewPackIds: Set<String> = []

    let apiClient: APIClient
    private var autoRefreshedMapIds: Set<String> = []

    init(apiClient: APIClient, initialMapId: String? = nil) {
        self.apiClient = apiClient
        selectInitialMap(initialMapId)
    }

    func selectInitialMap(_ mapId: String?) {
        guard let mapId, !mapId.isEmpty else { return }
        selectedMapId = mapId
    }

    func load() async {
        loading = true
        errorMessage = nil
        defer { loading = false }
        do {
            // No-fallback: a transient failure must NOT look like "empty brain".
            let loadedSync = try await apiClient.syncBrain(limit: 500)
            async let mirrorRequest = apiClient.getBrainMirror(limit: 60)
            async let graphRequest = apiClient.getBrainGraph(limit: 200)
            async let mapsRequest = apiClient.listBrainMaps(limit: 50)
            async let entitiesRequest = apiClient.listEntities(limit: 200)
            let (loadedMirror, loadedGraph, loadedMaps, loadedEntities) = try await (
                mirrorRequest,
                graphRequest,
                mapsRequest,
                entitiesRequest
            )
            brainSyncResult = loadedSync
            mirror = loadedMirror
            brainOverview = loadedGraph.overview
            maps = loadedMaps.maps
            entities = loadedEntities
            if selectedMapId != "mirror", !maps.contains(where: { $0.id == selectedMapId }) {
                selectedMapId = "mirror"
            }
        } catch {
            errorMessage = error.localizedDescription
            return
        }
        await loadSpaces()
        await loadSelectedSpace()
    }

    func repairBrainLinks() async {
        guard !linkingBrainSources else { return }
        linkingBrainSources = true
        defer { linkingBrainSources = false }
        do {
            // The explicit button also links never-linked chats (the auto-sync
            // on open stays zero-LLM); new chats already auto-link on each turn.
            let loadedSync = try await apiClient.syncBrain(limit: 500, includeChats: true)
            async let mirrorRequest = apiClient.getBrainMirror(limit: 60)
            async let graphRequest = apiClient.getBrainGraph(limit: 200)
            async let mapsRequest = apiClient.listBrainMaps(limit: 50)
            async let entitiesRequest = apiClient.listEntities(limit: 200)
            let (loadedMirror, loadedGraph, loadedMaps, loadedEntities) = try await (
                mirrorRequest,
                graphRequest,
                mapsRequest,
                entitiesRequest
            )
            brainSyncResult = loadedSync
            mirror = loadedMirror
            brainOverview = loadedGraph.overview
            maps = loadedMaps.maps
            entities = loadedEntities
            if selectedMapId != "mirror", !maps.contains(where: { $0.id == selectedMapId }) {
                selectedMapId = "mirror"
            }
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    var activeMap: BrainMap? {
        maps.first { $0.id == selectedMapId }
    }

    var activeProjection: BrainMapProjection? {
        if selectedMapId == "mirror" {
            return mirror
        }
        return activeMap?.currentRevision?.projection
    }

    func createLens(promptOverride: String? = nil) async {
        let prompt = (promptOverride ?? lensPrompt).trimmingCharacters(in: .whitespacesAndNewlines)
        guard !prompt.isEmpty, !creatingLens else { return }
        creatingLens = true
        defer { creatingLens = false }
        do {
            let created = try await apiClient.createBrainMap(
                BrainMapCreateRequest(prompt: prompt, origin: "brain")
            )
            maps.removeAll { $0.id == created.id }
            maps.insert(created, at: 0)
            selectedMapId = created.id
            lensPrompt = ""
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func askBrain(questionOverride: String? = nil) async {
        let question = (questionOverride ?? brainQuestion).trimmingCharacters(in: .whitespacesAndNewlines)
        guard !question.isEmpty, !askingBrain else { return }
        brainQuestion = question
        askingBrain = true
        defer { askingBrain = false }
        do {
            brainAnswer = try await apiClient.askBrain(question: question)
            brainAskError = nil
        } catch {
            brainAskError = error.localizedDescription
        }
    }

    func refreshActiveMap() async {
        guard let map = activeMap, refreshingMapId == nil else { return }
        refreshingMapId = map.id
        defer { refreshingMapId = nil }
        do {
            _ = try await apiClient.refreshBrainMap(mapId: map.id)
            let refreshed = try await apiClient.getBrainMap(mapId: map.id)
            replaceMap(refreshed)
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func refreshSelectedMapOnceIfNeeded() async {
        guard let map = activeMap, refreshingMapId == nil else { return }
        guard !autoRefreshedMapIds.contains(map.id) else { return }
        autoRefreshedMapIds.insert(map.id)
        await refreshActiveMap()
    }

    func keepActiveMap() async {
        guard let map = activeMap else { return }
        do {
            let updated = try await apiClient.updateBrainMap(
                mapId: map.id,
                BrainMapUpdateRequest(status: "saved")
            )
            replaceMap(updated)
            errorMessage = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    var hasAnything: Bool {
        !(mirror?.nodes.isEmpty ?? true)
            || ((brainOverview?.recordings.total ?? 0)
                + (brainOverview?.materials.total ?? 0)
                + (brainOverview?.chats.total ?? 0)) > 0
            || !maps.isEmpty
            || !entities.isEmpty
            || (spaceHome?.claimCounts.values.reduce(0, +) ?? 0) > 0
            || !spaceReviewPacks.isEmpty
            || !(spaceHome?.sources.isEmpty ?? true)
    }

    var visiblePages: [Entity] {
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return entities.filter { entity in
            (pageFilter == .all || entity.type.rawValue == pageFilter.rawValue)
                && (query.isEmpty || entity.name.lowercased().contains(query))
        }
    }

    func loadSpaces() async {
        do {
            let response = try await apiClient.listBrainSpaces()
            spaces = response.spaces
            if selectedSpaceId.isEmpty || !response.spaces.contains(where: { $0.id == selectedSpaceId }) {
                selectedSpaceId = response.spaces.first?.id ?? ""
            }
            spaceError = nil
        } catch {
            spaceError = error.localizedDescription
        }
    }

    func loadSelectedSpace() async {
        guard !selectedSpaceId.isEmpty else {
            spaceHome = nil
            spaceReviewPacks = []
            return
        }
        do {
            async let homeRequest = apiClient.getBrainSpaceHome(spaceId: selectedSpaceId)
            async let packsRequest = apiClient.listBrainReviewPacks(spaceId: selectedSpaceId)
            let loadedHome = try await homeRequest
            let loadedPacks = try await packsRequest
            spaceHome = loadedHome
            spaceReviewPacks = loadedPacks.reviewPacks
            spaceError = nil
        } catch {
            spaceError = error.localizedDescription
        }
    }

    func shareSelectedSpace(email: String, role: String) async {
        let trimmedEmail = email.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !selectedSpaceId.isEmpty, !trimmedEmail.isEmpty, !sharing else { return }
        sharing = true
        shareMessage = nil
        defer { sharing = false }
        do {
            _ = try await apiClient.addBrainSpaceMember(
                spaceId: selectedSpaceId,
                email: trimmedEmail,
                role: role
            )
            shareMessage = "Shared with \(trimmedEmail) as \(role)."
            spaceError = nil
        } catch {
            spaceError = error.localizedDescription
        }
    }

    func exportSelectedSpace(profile: String) async {
        guard !selectedSpaceId.isEmpty else { return }
        exportMessage = nil
        do {
            let export = try await apiClient.exportBrainSpace(spaceId: selectedSpaceId, profile: profile)
            switch export.files.count {
            case 0:
                exportMessage = "Nothing to export yet. Approved knowledge notes will appear here."
            case 1:
                exportMessage = "1 Markdown file is ready."
            default:
                exportMessage = "\(export.files.count) Markdown files are ready."
            }
            spaceError = nil
        } catch {
            spaceError = error.localizedDescription
        }
    }

    var selectedSpace: BrainSpace? {
        spaces.first { $0.id == selectedSpaceId }
    }

    private func replaceMap(_ updated: BrainMap) {
        if let index = maps.firstIndex(where: { $0.id == updated.id }) {
            maps[index] = updated
        } else {
            maps.insert(updated, at: 0)
        }
    }

    func openEntity(id: String, name: String) {
        selectedEntity = SelectedEntity(id: id, name: name)
        entityPage = nil
        Task { await loadEntityPage(id) }
    }

    func closeEntity() {
        selectedEntity = nil
        entityPage = nil
        pageError = nil
    }

    func loadEntityPage(_ id: String) async {
        pageLoading = true
        pageError = nil
        defer { pageLoading = false }
        do {
            entityPage = try await apiClient.getEntityPage(id: id)
        } catch {
            pageError = error.localizedDescription
        }
    }

    func acceptSpaceReviewPack(_ id: String) async {
        await decideSpaceReviewPack(id) {
            try await self.apiClient.acceptBrainReviewPack(spaceId: self.selectedSpaceId, packId: id)
        }
    }

    func rejectSpaceReviewPack(_ id: String) async {
        await decideSpaceReviewPack(id) {
            try await self.apiClient.rejectBrainReviewPack(spaceId: self.selectedSpaceId, packId: id)
        }
    }

    private func decideSpaceReviewPack(
        _ id: String,
        action: @escaping () async throws -> BrainReviewPack
    ) async {
        guard !selectedSpaceId.isEmpty, !actingSpaceReviewPackIds.contains(id) else { return }
        actingSpaceReviewPackIds.insert(id)
        defer { actingSpaceReviewPackIds.remove(id) }
        do {
            _ = try await action()
            spaceReviewPacks.removeAll { $0.id == id }
            await loadSelectedSpace()
        } catch {
            spaceError = error.localizedDescription
        }
    }
}
