import Foundation

/// A voice-triggered text expansion ("my email" → the full address).
public struct DictationSnippetRule: Equatable, Sendable {
    public let trigger: String
    public let expansion: String

    public init(trigger: String, expansion: String) {
        self.trigger = trigger
        self.expansion = expansion
    }
}

/// Applies snippet expansions to cleaned dictation text.
///
/// Matching follows the established dictation-snippet semantics:
/// - Dictating exactly the trigger (any case, with trailing punctuation the
///   cleanup may have added) replaces the whole text with the expansion.
/// - Inside a sentence, the trigger matches as an exact phrase on word
///   boundaries, case-insensitively; every occurrence expands in place.
/// - Longer triggers take precedence so a specific snippet ("sign off") is
///   never shadowed by a prefix one ("sign").
/// - Expansions are literal text and never re-trigger other snippets.
public enum SnippetExpander {
    public static func apply(to text: String, snippets: [DictationSnippetRule]) -> String {
        guard !snippets.isEmpty, !text.isEmpty else { return text }

        let ordered = snippets
            .filter { !$0.trigger.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
            .sorted { $0.trigger.count > $1.trigger.count }
        guard !ordered.isEmpty else { return text }

        // Whole-utterance match: the dictated text IS the trigger, modulo
        // case and trailing sentence punctuation added by cleanup.
        let bareText = normalizedUtterance(text)
        for snippet in ordered where normalizedUtterance(snippet.trigger) == bareText {
            return snippet.expansion
        }

        // In-sentence: expand exact-phrase occurrences on word boundaries.
        // A single mutable NSMutableString accumulates all replacements;
        // matches are located against a stable snapshot per snippet so an
        // expansion's text is never rescanned for other triggers at the
        // positions it introduced (replacements shift subsequent ranges via
        // per-snippet re-scan of the CURRENT string, but expansions that
        // happen to contain another trigger are left alone by scanning each
        // snippet exactly once over the text as it stood before that
        // snippet's own replacements).
        var result = text
        for snippet in ordered {
            result = expandOccurrences(of: snippet, in: result)
        }
        return result
    }

    private static func normalizedUtterance(_ value: String) -> String {
        var trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        while let last = trimmed.unicodeScalars.last,
              CharacterSet(charactersIn: ".!?,;:…").contains(last) {
            trimmed.unicodeScalars.removeLast()
        }
        return trimmed.lowercased()
    }

    private static func expandOccurrences(
        of snippet: DictationSnippetRule,
        in text: String
    ) -> String {
        let escaped = NSRegularExpression.escapedPattern(for: snippet.trigger)
        // Unicode-aware word boundaries: \b misbehaves around Cyrillic in
        // some ICU configurations, so anchor on explicit non-letter/digit
        // lookarounds instead.
        let pattern = "(?<![\\p{L}\\p{N}])" + escaped + "(?![\\p{L}\\p{N}])"
        guard let regex = try? NSRegularExpression(
            pattern: pattern,
            options: [.caseInsensitive]
        ) else {
            return text
        }
        let range = NSRange(text.startIndex..., in: text)
        return regex.stringByReplacingMatches(
            in: text,
            options: [],
            range: range,
            withTemplate: NSRegularExpression.escapedTemplate(for: snippet.expansion)
        )
    }
}
