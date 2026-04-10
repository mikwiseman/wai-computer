import Foundation
import os

private let log = Logger(subsystem: "com.waisay.app", category: "dictation-dictionary")

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

    /// Words without replacement are vocabulary boosters (improve recognition).
    /// Words with replacement are auto-corrections applied after transcription.
    var isReplacement: Bool {
        replacement != nil && replacement != word
    }
}

@MainActor
final class DictationDictionaryStore: ObservableObject {
    @Published private(set) var words: [DictionaryWord] = []

    private let fileURL: URL

    init() {
        let appSupport = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
        let dir = appSupport.appendingPathComponent("WaiSay", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        self.fileURL = dir.appendingPathComponent("dictation_dictionary.json")
        load()
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
    }

    func delete(_ word: DictionaryWord) {
        words.removeAll { $0.id == word.id }
        save()
    }

    /// Vocabulary list for prompt conditioning — sent to transcription provider
    var vocabularyList: [String] {
        words.map(\.word)
    }

    /// Apply replacement rules to transcribed text
    func applyReplacements(to text: String) -> String {
        var result = text
        for word in words where word.isReplacement {
            guard let replacement = word.replacement else { continue }
            result = result.replacingOccurrences(
                of: word.word,
                with: replacement,
                options: [.caseInsensitive]
            )
        }
        return result
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
            let data = try JSONEncoder().encode(words)
            try data.write(to: fileURL, options: .atomic)
        } catch {
            log.error("Failed to save dictionary: \(error.localizedDescription)")
        }
    }
}
