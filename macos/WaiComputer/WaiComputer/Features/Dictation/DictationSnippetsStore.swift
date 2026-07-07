import Foundation
import os
import WaiComputerKit

private let log = Logger(subsystem: "is.waiwai.computer.app", category: "dictation-snippets")

struct DictationSnippet: Identifiable, Codable, Hashable {
    let id: UUID
    var trigger: String
    var expansion: String
    let createdAt: Date

    init(trigger: String, expansion: String) {
        self.id = UUID()
        self.trigger = trigger
        self.expansion = expansion
        self.createdAt = Date()
    }

    init(id: UUID, trigger: String, expansion: String, createdAt: Date) {
        self.id = id
        self.trigger = trigger
        self.expansion = expansion
        self.createdAt = createdAt
    }
}

/// Local-first snippet store, synced with `/api/dictation/snippets` the same
/// way the dictionary store syncs: local JSON as the source of truth for the
/// session, tombstones so offline deletes replay, hydrate-merge on sign-in.
@MainActor
final class DictationSnippetsStore: ObservableObject {
    @Published private(set) var snippets: [DictationSnippet] = []

    private let fileURL: URL
    private let tombstonesURL: URL
    private var tombstones: Set<UUID> = []
    private var apiClient: APIClient?

    convenience init() {
        let appSupport = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
        let dir = appSupport.appendingPathComponent("WaiComputer", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        self.init(
            fileURL: dir.appendingPathComponent("dictation_snippets.json"),
            tombstonesURL: dir.appendingPathComponent("dictation_snippets_tombstones.json")
        )
    }

    init(fileURL: URL, tombstonesURL: URL) {
        self.fileURL = fileURL
        self.tombstonesURL = tombstonesURL
        load()
        loadTombstones()
    }

    func attach(apiClient: APIClient) {
        self.apiClient = apiClient
    }

    /// The expansion rules fed into `SnippetExpander` on every insertion.
    var expansionRules: [DictationSnippetRule] {
        snippets.map { DictationSnippetRule(trigger: $0.trigger, expansion: $0.expansion) }
    }

    @discardableResult
    func add(trigger: String, expansion: String) -> Bool {
        let trimmedTrigger = trigger.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedExpansion = expansion.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedTrigger.isEmpty, !trimmedExpansion.isEmpty else { return false }
        guard !snippets.contains(where: { $0.trigger.lowercased() == trimmedTrigger.lowercased() }) else {
            return false
        }

        let entry = DictationSnippet(trigger: trimmedTrigger, expansion: trimmedExpansion)
        snippets.append(entry)
        sortSnippets()
        save()
        log.info("Added snippet trigger_len=\(trimmedTrigger.count) expansion_len=\(trimmedExpansion.count)")

        if apiClient != nil {
            Task { await self.push(entry) }
        }
        return true
    }

    /// Edit via delete-then-add so server sync reuses the tested paths.
    @discardableResult
    func update(_ snippet: DictationSnippet, newTrigger: String, newExpansion: String) -> Bool {
        let trimmedTrigger = newTrigger.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedTrigger.isEmpty else { return false }
        if snippets.contains(where: {
            $0.id != snippet.id && $0.trigger.lowercased() == trimmedTrigger.lowercased()
        }) {
            return false
        }
        delete(snippet)
        return add(trigger: trimmedTrigger, expansion: newExpansion)
    }

    func delete(_ snippet: DictationSnippet) {
        snippets.removeAll { $0.id == snippet.id }
        save()

        guard apiClient != nil else { return }
        tombstones.insert(snippet.id)
        saveTombstones()
        Task { await self.deleteOnServer(snippet.id) }
    }

    func clearLocalCache() {
        snippets.removeAll()
        tombstones.removeAll()
        save()
        saveTombstones()
    }

    /// Pull server state, replay tombstoned deletes, merge, push local-only.
    func hydrate() async {
        guard let apiClient else { return }

        let serverSnippets: [APIClient.DictationSnippetPayload]
        do {
            serverSnippets = try await apiClient.listDictationSnippets()
        } catch {
            log.error("Hydrate snippets fetch failed: \(error.localizedDescription)")
            return
        }

        for server in serverSnippets where tombstones.contains(server.clientSnippetId) {
            do {
                try await apiClient.deleteDictationSnippet(clientSnippetId: server.clientSnippetId)
                tombstones.remove(server.clientSnippetId)
            } catch {
                log.error("Hydrate snippet tombstone replay failed: \(error.localizedDescription)")
            }
        }
        saveTombstones()

        let localIDs = Set(snippets.map(\.id))
        let serverByID = Dictionary(
            uniqueKeysWithValues: serverSnippets.map { ($0.clientSnippetId, $0) }
        )
        var additions: [DictationSnippet] = []
        for (id, dto) in serverByID where !localIDs.contains(id) && !tombstones.contains(id) {
            additions.append(
                DictationSnippet(
                    id: dto.clientSnippetId,
                    trigger: dto.trigger,
                    expansion: dto.expansion,
                    createdAt: dto.occurredAt
                )
            )
        }
        if !additions.isEmpty {
            snippets.append(contentsOf: additions)
            sortSnippets()
            save()
        }

        let serverIDs = Set(serverByID.keys)
        for entry in snippets where !serverIDs.contains(entry.id) {
            await push(entry)
        }
    }

    // MARK: - Private

    private func sortSnippets() {
        snippets.sort { $0.trigger.localizedCaseInsensitiveCompare($1.trigger) == .orderedAscending }
    }

    private func push(_ snippet: DictationSnippet) async {
        guard let apiClient else { return }
        do {
            _ = try await apiClient.createDictationSnippet(
                APIClient.DictationSnippetPayload(
                    clientSnippetId: snippet.id,
                    trigger: snippet.trigger,
                    expansion: snippet.expansion,
                    occurredAt: snippet.createdAt
                )
            )
        } catch {
            log.error("Snippet push failed: \(error.localizedDescription)")
        }
    }

    private func deleteOnServer(_ id: UUID) async {
        guard let apiClient else { return }
        do {
            try await apiClient.deleteDictationSnippet(clientSnippetId: id)
            tombstones.remove(id)
            saveTombstones()
        } catch {
            log.error("Snippet delete failed (kept tombstone): \(error.localizedDescription)")
        }
    }

    private func load() {
        guard let data = try? Data(contentsOf: fileURL) else { return }
        do {
            snippets = try JSONDecoder().decode([DictationSnippet].self, from: data)
        } catch {
            log.error("Snippet store load failed: \(error.localizedDescription)")
        }
    }

    private func save() {
        do {
            let data = try JSONEncoder().encode(snippets)
            try data.write(to: fileURL, options: .atomic)
        } catch {
            log.error("Snippet store save failed: \(error.localizedDescription)")
        }
    }

    private func loadTombstones() {
        guard let data = try? Data(contentsOf: tombstonesURL) else { return }
        tombstones = (try? JSONDecoder().decode(Set<UUID>.self, from: data)) ?? []
    }

    private func saveTombstones() {
        do {
            let data = try JSONEncoder().encode(tombstones)
            try data.write(to: tombstonesURL, options: .atomic)
        } catch {
            log.error("Snippet tombstones save failed: \(error.localizedDescription)")
        }
    }
}
