import AppKit
import WaiComputerKit

/// `LexiconChecking` backed by macOS `NSSpellChecker`: a token is "known" when
/// the system spell checker finds no misspelling for it. The learn-from-edits
/// gate uses this so only out-of-vocabulary terms (names, brands, jargon) are
/// ever auto-learned — common words are left to STT biasing + cleanup.
///
/// Always invoked on the main actor (the learning engine is `@MainActor`);
/// `NSSpellChecker.shared` requires the main thread.
struct MacLexiconChecker: LexiconChecking {
    func isKnownWord(_ token: String, language: String?) -> Bool {
        let trimmed = token.trimmingCharacters(in: .whitespacesAndNewlines)
        // No letters (digits / symbols) ⇒ not a learnable vocabulary word; treat
        // as "known" so the OOV gate rejects it. (Numerals are handled upstream.)
        guard trimmed.contains(where: { $0.isLetter }) else { return true }

        // Called on the main actor (the learning engine is @MainActor), which is
        // where NSSpellChecker must run.
        let checker = NSSpellChecker.shared
        let spellLanguage = Self.spellLanguage(for: language) ?? checker.language()
        let misspelledRange = checker.checkSpelling(
            of: trimmed,
            startingAt: 0,
            language: spellLanguage,
            wrap: false,
            inSpellDocumentWithTag: 0,
            wordCount: nil
        )
        // NSNotFound ⇒ no misspelling ⇒ the word is in the dictionary.
        return misspelledRange.location == NSNotFound
    }

    /// Map our dictation language hint to an NSSpellChecker language id, or nil
    /// to fall back to the checker's current language (covers "multi"/auto).
    private static func spellLanguage(for language: String?) -> String? {
        guard let raw = language?.lowercased(), !raw.isEmpty else { return nil }
        if raw == "multi" || raw == "auto" || raw == "und" { return nil }
        if raw.hasPrefix("ru") { return "ru" }
        if raw.hasPrefix("en") { return "en" }
        // Pass through a concrete base code (e.g. "de", "fr"); NSSpellChecker
        // ignores languages whose dictionary isn't installed and uses the default.
        return String(raw.prefix(2))
    }
}
