import Foundation

// Phonetic similarity for the learn-from-edits engine: decide whether a
// substitution is a genuine mis-hearing (learnable) or an unrelated rewrite
// (ignore). FROZEN PUBLIC API — implement bodies, keep signatures.
//
// Script-aware: Latin uses a Metaphone-style consonant skeleton; Cyrillic uses
// Russian reduction rules (collapse unstressed vowels О/Ы/Я→А, Ю→У, Е/Ё/Э→И;
// devoice final/pre-consonant Б→П, З→С, Д→Т, В→Ф, Г→К, Ж→Ш; drop ь/ъ and
// doubled letters). Mixed/other scripts fall back to edit-distance similarity.
// Do NOT use Soundex/Metaphone on Cyrillic — they encode English phonetics.

public enum PhoneticMatcher {

    /// True if `a` and `b` plausibly sound alike (a mis-recognition), false if
    /// they read as an unrelated rewrite. Combines phonetic-code equality with
    /// an edit-distance floor; case/whitespace-insensitive.
    public static func areSoundAlike(_ a: String, _ b: String) -> Bool {
        _unimplemented()
    }

    /// Normalized similarity in 0...1 (1 = identical), Levenshtein-based on the
    /// case-folded tokens. Exposed for thresholds and tests.
    public static func similarity(_ a: String, _ b: String) -> Double {
        _unimplemented()
    }

    /// Phonetic code for a single token (script auto-detected). Visible for
    /// tests; two tokens with equal non-empty codes are treated as sound-alike.
    public static func code(for token: String) -> String {
        _unimplemented()
    }

    private static func _unimplemented(_ function: StaticString = #function) -> Never {
        fatalError("PhoneticMatcher.\(function) not yet implemented")
    }
}
