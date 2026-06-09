import Foundation

// Shared contract for the dictation "learn from edits" engine.
//
// The recognizer produces text; the user keeps or fixes it. When the same
// mis-hearing is corrected repeatedly we propose adding the word to the
// dictionary. Everything here is pure Foundation so iOS can reuse it later;
// platform pieces (NSSpellChecker, Accessibility) live in the app target.
//
// Privacy: these types carry single token pairs only — never sentences or
// surrounding context. See DICTIONARY_LEARNING.md.

/// One token-level substitution: the recognizer wrote `original`, the user
/// changed it to `corrected`. Surface forms are preserved (the corrected form
/// is what we would add to the dictionary). `language` is the best-effort hint
/// captured at dictation time ("en", "ru", "multi", or nil).
public struct CorrectionPair: Equatable, Hashable, Sendable, Codable {
    public let original: String
    public let corrected: String
    public let language: String?

    public init(original: String, corrected: String, language: String?) {
        self.original = original
        self.corrected = corrected
        self.language = language
    }
}

/// Outcome of running the extractor on one (produced, edited) text pair.
/// `pairs` are the gated, learnable substitutions; `skipped` explains an empty
/// result for diagnostics (content-free — safe to log).
public struct CorrectionExtractionResult: Equatable, Sendable {
    public enum SkipReason: String, Sendable {
        case emptyInput
        case identical
        case tooDivergent      // edited text differs too much to attribute reliably
        case noSubstitutions   // diff had only inserts/deletes/format changes
        case allGated          // substitutions existed but every one failed a gate
    }

    public let pairs: [CorrectionPair]
    public let skipped: SkipReason?

    public init(pairs: [CorrectionPair], skipped: SkipReason?) {
        self.pairs = pairs
        self.skipped = skipped
    }

    public static let empty = CorrectionExtractionResult(pairs: [], skipped: .emptyInput)
}

/// Decides whether a token is an ordinary, known word in a language — used by
/// the class gate so we only auto-learn out-of-vocabulary / proper-noun terms,
/// never common words. Implemented per platform (NSSpellChecker on macOS,
/// UITextChecker on iOS); the kit stays AppKit-free.
public protocol LexiconChecking: Sendable {
    /// True if `token` is a recognized common word in `language` (so it is NOT
    /// a learnable vocabulary term on its own). `language` nil ⇒ best-effort.
    func isKnownWord(_ token: String, language: String?) -> Bool
}

/// A recurrence-promoted suggestion surfaced to the user for one-tap accept.
/// Persisted in the on-device ledger; never synced, never logged with content.
public struct DictionarySuggestion: Identifiable, Equatable, Sendable, Codable {
    public let id: UUID
    /// The mis-heard form (left side of an optional replacement rule).
    public let original: String
    /// The word to add to the dictionary (right side / bias term).
    public let corrected: String
    public let language: String?
    public let hitCount: Int
    public let firstSeen: Date
    public let lastSeen: Date

    public init(
        id: UUID = UUID(),
        original: String,
        corrected: String,
        language: String?,
        hitCount: Int,
        firstSeen: Date,
        lastSeen: Date
    ) {
        self.id = id
        self.original = original
        self.corrected = corrected
        self.language = language
        self.hitCount = hitCount
        self.firstSeen = firstSeen
        self.lastSeen = lastSeen
    }
}
