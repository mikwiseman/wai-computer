import Foundation
import os
import WaiComputerKit

private let log = Logger(subsystem: "is.waiwai.computer.app", category: "dictation-dictionary")

struct DictionaryWord: Identifiable, Codable, Hashable {
    let id: UUID
    var word: String
    var replacement: String?
    let createdAt: Date

    init(word: String, replacement: String? = nil) {
        self.id = UUID()
        self.word = word
        self.replacement = replacement
        self.createdAt = Date()
    }

    init(id: UUID, word: String, replacement: String?, createdAt: Date) {
        self.id = id
        self.word = word
        self.replacement = replacement
        self.createdAt = createdAt
    }

    /// Words without replacement are vocabulary boosters (improve recognition).
    /// Words with replacement are auto-corrections applied after transcription.
    var isReplacement: Bool {
        replacement != nil && replacement != word
    }
}

/// Server-synced custom dictation dictionary. Ported verbatim from macOS (pure
/// Foundation/os/WaiComputerKit). Mirrors the server via the shared
/// `listDictationDictionary` / `createDictionaryWord` / `deleteDictionaryWord`
/// endpoints. The view layer is iOS-native; this store is identical.
@MainActor
final class DictationDictionaryStore: ObservableObject {
    @Published private(set) var words: [DictionaryWord] = []

    private let fileURL: URL
    private let tombstonesURL: URL
    private var tombstones: Set<UUID> = []
    private var apiClient: APIClient?

    init() {
        let appSupport = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
        let dir = appSupport.appendingPathComponent("WaiComputer", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        self.fileURL = dir.appendingPathComponent("dictation_dictionary.json")
        self.tombstonesURL = dir.appendingPathComponent("dictation_dictionary_tombstones.json")
        load()
        loadTombstones()
    }

    // MARK: - Sync wiring

    func attach(apiClient: APIClient) {
        self.apiClient = apiClient
    }

    func add(word: String, replacement: String? = nil) {
        let trimmed = word.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        guard !words.contains(where: { $0.word.lowercased() == trimmed.lowercased() }) else { return }

        let entry = DictionaryWord(word: trimmed, replacement: replacement)
        words.append(entry)
        words.sort { $0.word.localizedCaseInsensitiveCompare($1.word) == .orderedAscending }
        save()
        log.info("Added dictionary word: \(trimmed)")

        if apiClient != nil {
            Task { await self.pushWord(entry) }
        }
    }

    func delete(_ word: DictionaryWord) {
        words.removeAll { $0.id == word.id }
        save()

        guard apiClient != nil else { return }
        tombstones.insert(word.id)
        saveTombstones()
        Task { await self.deleteWordOnServer(word.id) }
    }

    func clearLocalCache() {
        words.removeAll()
        tombstones.removeAll()
        save()
        saveTombstones()
    }

    /// Pull server state, merge, push local-only words, retry tombstoned deletes.
    func hydrate() async {
        guard let apiClient else { return }

        let serverWords: [DictionaryWordDTO]
        do {
            serverWords = try await apiClient.listDictationDictionary()
        } catch {
            log.error("Hydrate dictionary fetch failed: \(error.localizedDescription)")
            return
        }

        for serverWord in serverWords where tombstones.contains(serverWord.clientWordID) {
            do {
                try await apiClient.deleteDictionaryWord(clientWordID: serverWord.clientWordID)
                tombstones.remove(serverWord.clientWordID)
            } catch {
                log.error("Hydrate dictionary tombstone replay failed: \(error.localizedDescription)")
            }
        }
        saveTombstones()

        let localIDs = Set(words.map(\.id))
        let serverByID = Dictionary(uniqueKeysWithValues: serverWords.map { ($0.clientWordID, $0) })
        var additions: [DictionaryWord] = []
        for (id, dto) in serverByID where !localIDs.contains(id) && !tombstones.contains(id) {
            additions.append(
                DictionaryWord(
                    id: dto.clientWordID,
                    word: dto.word,
                    replacement: dto.replacement,
                    createdAt: dto.occurredAt
                )
            )
        }
        if !additions.isEmpty {
            words.append(contentsOf: additions)
            words.sort { $0.word.localizedCaseInsensitiveCompare($1.word) == .orderedAscending }
            save()
        }

        let serverIDs = Set(serverByID.keys)
        for entry in words where !serverIDs.contains(entry.id) {
            await pushWord(entry)
        }
    }

    /// Vocabulary list for prompt conditioning — sent to transcription provider
    var vocabularyList: [String] {
        words.map(\.word)
    }

    /// Apply replacement rules to transcribed text.
    ///
    /// Matches whole words only. A literal substring replace would rewrite
    /// inside words ("cat" → "dog" turning "category" into "dogegory"), so we
    /// anchor on Unicode word boundaries — `.useUnicodeWordBoundaries` is
    /// essential or `\b` is ASCII-only and never fires between Cyrillic letters.
    func applyReplacements(to text: String) -> String {
        var result = text
        for word in words where word.isReplacement {
            guard let replacement = word.replacement,
                  !word.word.isEmpty else { continue }
            let pattern = "\\b" + NSRegularExpression.escapedPattern(for: word.word) + "\\b"
            guard let regex = try? NSRegularExpression(
                pattern: pattern,
                options: [.caseInsensitive, .useUnicodeWordBoundaries]
            ) else { continue }
            let range = NSRange(result.startIndex..., in: result)
            result = regex.stringByReplacingMatches(
                in: result,
                range: range,
                withTemplate: NSRegularExpression.escapedTemplate(for: replacement)
            )
        }
        return result
    }

    // MARK: - Sync helpers

    private static let iso8601: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()

    private func pushWord(_ word: DictionaryWord) async {
        guard let apiClient else { return }
        let request = CreateDictionaryWordRequest(
            clientWordID: word.id,
            word: word.word,
            replacement: word.replacement,
            occurredAt: Self.iso8601.string(from: word.createdAt)
        )
        do {
            _ = try await apiClient.createDictionaryWord(request)
        } catch {
            log.error("Push word failed (will retry on next hydrate): \(error.localizedDescription)")
        }
    }

    private func deleteWordOnServer(_ id: UUID) async {
        guard let apiClient else { return }
        do {
            try await apiClient.deleteDictionaryWord(clientWordID: id)
            tombstones.remove(id)
            saveTombstones()
        } catch {
            log.error("Delete word on server failed (tombstone remains): \(error.localizedDescription)")
        }
    }

    // MARK: - Persistence

    private func load() {
        guard FileManager.default.fileExists(atPath: fileURL.path) else { return }
        do {
            let data = try Data(contentsOf: fileURL)
            words = try JSONDecoder().decode([DictionaryWord].self, from: data)
            log.info("Loaded \(self.words.count) dictionary words")
        } catch {
            log.error("Failed to load dictionary: \(error.localizedDescription)")
        }
    }

    private func save() {
        do {
            try FileManager.default.createDirectory(
                at: fileURL.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            let data = try JSONEncoder().encode(words)
            try data.write(to: fileURL, options: .atomic)
        } catch {
            log.error("Failed to save dictionary: \(error.localizedDescription)")
        }
    }

    private func loadTombstones() {
        guard FileManager.default.fileExists(atPath: tombstonesURL.path) else { return }
        do {
            let data = try Data(contentsOf: tombstonesURL)
            tombstones = Set(try JSONDecoder().decode([UUID].self, from: data))
        } catch {
            log.error("Failed to load dictionary tombstones: \(error.localizedDescription)")
        }
    }

    private func saveTombstones() {
        do {
            try FileManager.default.createDirectory(
                at: tombstonesURL.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            let data = try JSONEncoder().encode(Array(tombstones))
            try data.write(to: tombstonesURL, options: .atomic)
        } catch {
            log.error("Failed to save dictionary tombstones: \(error.localizedDescription)")
        }
    }
}
