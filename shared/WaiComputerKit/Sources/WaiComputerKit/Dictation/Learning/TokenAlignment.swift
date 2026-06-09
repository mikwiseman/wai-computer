import Foundation

// Token-level alignment primitives for the learn-from-edits engine.
//
// FROZEN PUBLIC API — implement the bodies, do not change the signatures or the
// `Op` cases (CorrectionExtractor and DictionaryLearningEngine compile against
// them). Private helpers are welcome.

public enum TokenAlignment {

    /// A single alignment operation between the produced token stream and the
    /// edited one. `match` carries the (edited) surface; `substitute` carries
    /// both surfaces.
    public enum Op: Equatable, Sendable {
        case match(String)
        case substitute(from: String, to: String)
        case insert(String)   // present only in edited
        case delete(String)   // present only in produced
    }

    /// Split text into comparable word tokens. Unicode-aware: a token is a
    /// maximal run of letters/numbers (intra-word apostrophes and hyphens kept,
    /// e.g. "don't", "IT-директор"); whitespace and surrounding punctuation are
    /// separators and dropped. Empty input ⇒ [].
    public static func tokenize(_ text: String) -> [String] {
        _unimplemented()
    }

    /// Normalize a token for equality comparison: Unicode case-fold
    /// (`lowercased()` — correct for Cyrillic on Apple platforms) and strip
    /// leading/trailing punctuation, NFC. Used to decide whether two tokens are
    /// "the same" (case/punctuation-only differences are NOT edits).
    public static func normalize(_ token: String) -> String {
        _unimplemented()
    }

    /// Damerau-Levenshtein alignment of two token arrays. Tokens whose
    /// `normalize` forms are equal align as `.match`; differing ones become
    /// `.substitute` / `.insert` / `.delete`. Order is preserved.
    public static func align(_ produced: [String], _ edited: [String]) -> [Op] {
        _unimplemented()
    }

    /// Find the best contiguous run in `haystack` that aligns with `needle`
    /// (used to locate the text we inserted inside a larger edited field).
    /// Returns the haystack index range, or nil if `needle` is not
    /// substantially present (so we don't attribute unrelated edits).
    public static func locate(_ needle: [String], in haystack: [String]) -> Range<Int>? {
        _unimplemented()
    }

    private static func _unimplemented(_ function: StaticString = #function) -> Never {
        fatalError("TokenAlignment.\(function) not yet implemented")
    }
}
