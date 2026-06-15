import Foundation
import os
import WaiComputerKit

private let log = Logger(subsystem: "is.waiwai.computer.app", category: "dictation-dictionary")

struct DictionaryWord: Identifiable, Codable, Hashable {
    let id: UUID
    var word: String
    var replacement: String?
    /// "manual" or "learned" (accepted from an auto-suggestion).
    var origin: String
    let createdAt: Date

    init(word: String, replacement: String? = nil, origin: String = "manual") {
        self.id = UUID()
        self.word = word
        self.replacement = replacement
        self.origin = origin
        self.createdAt = Date()
    }

    init(id: UUID, word: String, replacement: String?, origin: String = "manual", createdAt: Date) {
        self.id = id
        self.word = word
        self.replacement = replacement
        self.origin = origin
        self.createdAt = createdAt
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(UUID.self, forKey: .id)
        word = try c.decode(String.self, forKey: .word)
        replacement = try c.decodeIfPresent(String.self, forKey: .replacement)
        // Older local caches predate `origin`; default them to manual.
        origin = try c.decodeIfPresent(String.self, forKey: .origin) ?? "manual"
        createdAt = try c.decode(Date.self, forKey: .createdAt)
    }

    /// Words without replacement are vocabulary boosters (improve recognition).
    /// Words with replacement are auto-corrections applied after transcription.
    var isReplacement: Bool {
        replacement != nil && replacement != word
    }

    /// True for entries auto-learned from the user's repeated edits.
    var isLearned: Bool { origin == "learned" }
}

struct DictationRealtimeHints: Equatable {
    static let empty = DictationRealtimeHints(keyterms: [], replacements: [])

    let keyterms: [String]
    let replacements: [RealtimeTranscriptionReplacement]
}

@MainActor
final class DictationDictionaryStore: ObservableObject {
    @Published private(set) var words: [DictionaryWord] = [] {
        didSet { wordsRevision += 1 }
    }
    private(set) var wordsRevision = 0

    private let fileURL: URL
    private let tombstonesURL: URL
    private var tombstones: Set<UUID> = []
    private var apiClient: APIClient?
    var onRealtimeHintsChanged: ((String) -> Void)?

    convenience init() {
        let appSupport = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
        let dir = appSupport.appendingPathComponent("WaiComputer", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        self.init(
            fileURL: dir.appendingPathComponent("dictation_dictionary.json"),
            tombstonesURL: dir.appendingPathComponent("dictation_dictionary_tombstones.json")
        )
    }

    init(fileURL: URL, tombstonesURL: URL) {
        self.fileURL = fileURL
        self.tombstonesURL = tombstonesURL
        load()
        loadTombstones()
    }

    // MARK: - Sync wiring

    func attach(apiClient: APIClient) {
        self.apiClient = apiClient
    }

    @discardableResult
    func add(word: String, replacement: String? = nil, origin: String = "manual") -> Bool {
        add(word: word, replacement: replacement, origin: origin, notificationReason: "dictionary_add")
    }

    @discardableResult
    private func add(
        word: String,
        replacement: String? = nil,
        origin: String = "manual",
        notificationReason: String?
    ) -> Bool {
        let trimmed = word.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return false }
        guard !words.contains(where: { $0.word.lowercased() == trimmed.lowercased() }) else { return false }

        let entry = DictionaryWord(word: trimmed, replacement: replacement, origin: origin)
        words.append(entry)
        words.sort { $0.word.localizedCaseInsensitiveCompare($1.word) == .orderedAscending }
        save()
        log.info("Added dictionary word: \(trimmed)")

        if apiClient != nil {
            Task { await self.pushWord(entry) }
        }
        notifyRealtimeHintsChanged(reason: notificationReason)
        return true
    }

    /// Add a learned replacement rule, upgrading an existing same-word entry
    /// (e.g. a bias booster) to carry the replacement instead of silently
    /// dropping the user's request on a name collision. Always yields a rule.
    func learnReplacement(word: String, replacement: String) {
        let trimmed = word.trimmingCharacters(in: .whitespacesAndNewlines)
        let replacementTrimmed = replacement.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, !replacementTrimmed.isEmpty else { return }
        if let existing = words.first(where: { $0.word.lowercased() == trimmed.lowercased() }) {
            delete(existing, notificationReason: nil)
        }
        add(
            word: trimmed,
            replacement: replacementTrimmed,
            origin: "learned",
            notificationReason: "dictionary_learn_replacement"
        )
    }

    /// Edit an existing entry. Implemented as delete-then-add so it reuses the
    /// tested server sync paths (the `add` dedupe is keyed on `word`, so editing
    /// only the replacement would otherwise be silently rejected). Returns false
    /// if the new word collides with a *different* existing entry.
    @discardableResult
    func update(_ word: DictionaryWord, newWord: String, newReplacement: String?) -> Bool {
        let trimmed = newWord.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return false }
        if words.contains(where: { $0.id != word.id && $0.word.lowercased() == trimmed.lowercased() }) {
            return false
        }
        delete(word, notificationReason: nil)
        let replacement = newReplacement?.trimmingCharacters(in: .whitespacesAndNewlines)
        return add(
            word: trimmed,
            replacement: (replacement?.isEmpty == false) ? replacement : nil,
            notificationReason: "dictionary_update"
        )
    }

    func delete(_ word: DictionaryWord) {
        delete(word, notificationReason: "dictionary_delete")
    }

    private func delete(_ word: DictionaryWord, notificationReason: String?) {
        words.removeAll { $0.id == word.id }
        save()
        notifyRealtimeHintsChanged(reason: notificationReason)

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
        notifyRealtimeHintsChanged(reason: "dictionary_clear")
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
                    origin: dto.origin,
                    createdAt: dto.occurredAt
                )
            )
        }
        if !additions.isEmpty {
            words.append(contentsOf: additions)
            words.sort { $0.word.localizedCaseInsensitiveCompare($1.word) == .orderedAscending }
            save()
            notifyRealtimeHintsChanged(reason: "dictionary_hydrate")
        }

        let serverIDs = Set(serverByID.keys)
        for entry in words where !serverIDs.contains(entry.id) {
            await pushWord(entry)
        }
    }

    /// Vocabulary list for prompt conditioning — sent to transcription provider
    var vocabularyList: [String] {
        var terms: [String] = []
        var seen: Set<String> = []
        for word in words {
            appendVocabularyTerm(word.word, to: &terms, seen: &seen)
            if let replacement = word.replacement {
                appendVocabularyTerm(replacement, to: &terms, seen: &seen)
            }
        }
        return terms
    }

    var realtimeHints: DictationRealtimeHints {
        let keyterms = Array(vocabularyList.prefix(100))
        var replacements: [RealtimeTranscriptionReplacement] = []
        var seenReplacementFinds: Set<String> = []
        for word in words where word.isReplacement {
            guard let replacement = word.replacement else { continue }
            let find = word.word.trimmingCharacters(in: .whitespacesAndNewlines)
            let replace = replacement.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !find.isEmpty, !replace.isEmpty else { continue }
            let normalizedFind = find.lowercased()
            guard !seenReplacementFinds.contains(normalizedFind) else { continue }
            seenReplacementFinds.insert(normalizedFind)
            replacements.append(RealtimeTranscriptionReplacement(find: find, replace: replace))
            if replacements.count >= 200 {
                break
            }
        }
        return DictationRealtimeHints(keyterms: keyterms, replacements: replacements)
    }

    /// Apply replacement rules to transcribed text.
    ///
    /// Matches whole words only. Multi-token learned phrases tolerate
    /// punctuation between words ("why, computer" → "WaiComputer") because STT
    /// may insert commas before replacements run. A literal substring replace
    /// would rewrite inside words ("cat" → "dog" turning "category" into
    /// "dogegory"), so we anchor on Unicode word boundaries —
    /// `.useUnicodeWordBoundaries` is essential or `\b` is ASCII-only and never
    /// fires between Cyrillic letters.
    func applyReplacements(to text: String) -> String {
        var result = text
        for word in words where word.isReplacement {
            guard let replacement = word.replacement,
                  !word.word.isEmpty else { continue }
            let pattern = replacementPattern(for: word.word)
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

    private func replacementPattern(for word: String) -> String {
        let tokens = word
            .split(whereSeparator: \.isWhitespace)
            .map(String.init)
        guard tokens.count > 1 else {
            return "\\b" + NSRegularExpression.escapedPattern(for: word) + "\\b"
        }
        return "\\b"
            + tokens
                .map { NSRegularExpression.escapedPattern(for: $0) }
                .joined(separator: "[^\\p{L}\\p{N}]+")
            + "\\b"
    }

    private func appendVocabularyTerm(_ term: String, to terms: inout [String], seen: inout Set<String>) {
        let trimmed = term.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        let normalized = trimmed.lowercased()
        guard !seen.contains(normalized) else { return }
        seen.insert(normalized)
        terms.append(trimmed)
    }

    private func notifyRealtimeHintsChanged(reason: String?) {
        guard let reason else { return }
        onRealtimeHintsChanged?(reason)
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
            origin: word.origin,
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
