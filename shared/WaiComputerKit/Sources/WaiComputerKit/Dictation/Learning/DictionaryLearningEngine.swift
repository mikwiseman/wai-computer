import Foundation
import os

// Owns the learn-from-edits loop's state: it receives (produced → edited)
// observations, runs the extractor, tallies how often each mis-hearing recurs
// in a rolling window, and publishes one-tap suggestions once a pair crosses the
// recurrence threshold.
//
// Privacy: the on-device ledger stores ONLY token / short token-phrase pairs +
// counts, never sentences or surrounding context, is never synced, and is never
// logged with content. See DICTIONARY_LEARNING.md.

@MainActor
public final class DictionaryLearningEngine: ObservableObject {

    public struct Config: Sendable {
        /// Recurrences of the same correction before it becomes a suggestion.
        public var promoteAfter: Int
        /// How long a correction stays "remembered" without recurring.
        public var window: TimeInterval
        /// Max suggestions surfaced at once.
        public var maxSuggestions: Int

        public init(
            promoteAfter: Int = 2,
            window: TimeInterval = 30 * 24 * 60 * 60,
            maxSuggestions: Int = 20
        ) {
            self.promoteAfter = promoteAfter
            self.window = window
            self.maxSuggestions = maxSuggestions
        }

        public static let `default` = Config()
    }

    /// Pending suggestions, newest-corrected first. Drives the UI.
    @Published public private(set) var suggestions: [DictionarySuggestion] = []

    private let extractor: CorrectionExtractor
    private let config: Config
    private let storeURL: URL
    private let dateProvider: @Sendable () -> Date
    private let log = Logger(subsystem: "is.waiwai.computer.kit", category: "dictation-learning")

    private var entries: [Entry] = []
    private var suppressed: Set<String> = []

    public init(
        lexicon: LexiconChecking,
        config: Config = .default,
        extractorConfig: CorrectionExtractor.Config = .default,
        storeURL: URL? = nil,
        dateProvider: @escaping @Sendable () -> Date = { Date() }
    ) {
        self.extractor = CorrectionExtractor(lexicon: lexicon, config: extractorConfig)
        self.config = config
        self.dateProvider = dateProvider
        self.storeURL = storeURL ?? Self.defaultStoreURL()
        load()
        recompute()
    }

    // MARK: - Public API

    /// Observe what we produced vs what the user kept. Extracts learnable
    /// corrections, tallies recurrence, and refreshes `suggestions`.
    public func observeEdit(produced: String, edited: String, language: String?) {
        let result = extractor.extract(produced: produced, edited: edited, language: language)
        guard !result.pairs.isEmpty else { return }

        let now = dateProvider()
        // Drop entries that fell out of the window BEFORE counting, so a
        // recurrence after the window starts fresh rather than resurrecting a
        // stale hit.
        pruneExpired(now: now)
        for pair in result.pairs {
            let key = Self.key(original: pair.original, corrected: pair.corrected)
            if suppressed.contains(key) { continue }
            if let index = entries.firstIndex(where: { $0.key == key }) {
                entries[index].count += 1
                entries[index].lastSeen = now
                // Keep the freshest surface forms (casing the user actually used).
                entries[index].original = pair.original
                entries[index].corrected = pair.corrected
            } else {
                entries.append(
                    Entry(
                        id: UUID(),
                        key: key,
                        original: pair.original,
                        corrected: pair.corrected,
                        language: pair.language,
                        count: 1,
                        firstSeen: now,
                        lastSeen: now
                    )
                )
            }
        }
        save()
        recompute()
    }

    /// User accepted a suggestion (the caller adds it to the dictionary). The
    /// pair is suppressed so it is not re-suggested for an already-known word.
    public func accept(_ suggestion: DictionarySuggestion) {
        suppressAndRemove(suggestion)
    }

    /// User dismissed a suggestion: suppress so it does not nag again.
    public func dismiss(_ suggestion: DictionarySuggestion) {
        suppressAndRemove(suggestion)
    }

    /// Forget all learned data and pending suggestions (Settings → clear).
    public func clearAll() {
        entries.removeAll()
        suppressed.removeAll()
        save()
        recompute()
    }

    // MARK: - Internals

    private func suppressAndRemove(_ suggestion: DictionarySuggestion) {
        let key = Self.key(original: suggestion.original, corrected: suggestion.corrected)
        suppressed.insert(key)
        entries.removeAll { $0.key == key }
        save()
        recompute()
    }

    private func pruneExpired(now: Date) {
        let cutoff = now.addingTimeInterval(-config.window)
        entries.removeAll { $0.lastSeen < cutoff }
    }

    private func recompute() {
        let cutoff = dateProvider().addingTimeInterval(-config.window)
        suggestions = entries
            .filter { $0.count >= config.promoteAfter && $0.lastSeen >= cutoff && !suppressed.contains($0.key) }
            .sorted { $0.lastSeen > $1.lastSeen }
            .prefix(config.maxSuggestions)
            .map {
                DictionarySuggestion(
                    id: $0.id,
                    original: $0.original,
                    corrected: $0.corrected,
                    language: $0.language,
                    hitCount: $0.count,
                    firstSeen: $0.firstSeen,
                    lastSeen: $0.lastSeen
                )
            }
    }

    private static func key(original: String, corrected: String) -> String {
        // Language-insensitive on purpose: the AX monitor tags a best-effort
        // language while history-row edits can't, so both surfaces must converge
        // on one recurrence counter. Language is kept only as entry metadata.
        TokenAlignment.normalize(original) + "→" + TokenAlignment.normalize(corrected)
    }

    // MARK: - Persistence (on-device only, never synced)

    private struct Entry: Codable, Sendable {
        let id: UUID
        let key: String
        var original: String
        var corrected: String
        let language: String?
        var count: Int
        let firstSeen: Date
        var lastSeen: Date
    }

    private struct PersistedState: Codable {
        var entries: [Entry]
        var suppressed: [String]
    }

    private static func defaultStoreURL() -> URL {
        let appSupport = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
        let dir = appSupport.appendingPathComponent("WaiComputer", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir.appendingPathComponent("dictation_learning_ledger.json")
    }

    private func load() {
        guard FileManager.default.fileExists(atPath: storeURL.path) else { return }
        do {
            let data = try Data(contentsOf: storeURL)
            let state = try JSONDecoder().decode(PersistedState.self, from: data)
            entries = state.entries
            suppressed = Set(state.suppressed)
        } catch {
            // A corrupt local cache is recoverable by starting empty; surface it
            // in the log but never crash dictation over learning state.
            log.error("Failed to load learning ledger: \(error.localizedDescription, privacy: .public)")
        }
    }

    private func save() {
        do {
            try FileManager.default.createDirectory(
                at: storeURL.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            let state = PersistedState(entries: entries, suppressed: Array(suppressed))
            let data = try JSONEncoder().encode(state)
            try data.write(to: storeURL, options: .atomic)
        } catch {
            log.error("Failed to save learning ledger: \(error.localizedDescription, privacy: .public)")
        }
    }
}
