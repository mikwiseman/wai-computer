import Foundation

/// Trailing spoken commands: saying "press enter" at the END of a dictation
/// strips the phrase from the inserted text and fires the keystroke after the
/// paste — the chat-app "dictate and send" flow. Mid-sentence mentions are
/// content, not commands.
public enum DictationTrailingCommand: Equatable, Sendable {
    case pressEnter

    public struct Parsed: Equatable, Sendable {
        public let text: String
        public let command: DictationTrailingCommand?
    }

    /// English + Russian trigger phrases, matched only at the end of the
    /// utterance (with optional trailing punctuation the cleanup added).
    private static let pressEnterPhrases = [
        "press enter",
        "нажми энтер",
        "нажми enter",
    ]

    public static func parse(_ text: String) -> Parsed {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return Parsed(text: text, command: nil) }

        for phrase in pressEnterPhrases {
            let pattern =
                "(?:^|[\\s.,;:!?…])" +
                NSRegularExpression.escapedPattern(for: phrase) +
                "[\\s.,;:!?…]*$"
            guard let regex = try? NSRegularExpression(
                pattern: pattern,
                options: [.caseInsensitive]
            ) else { continue }
            let range = NSRange(trimmed.startIndex..., in: trimmed)
            guard let match = regex.firstMatch(in: trimmed, options: [], range: range),
                  let swiftRange = Range(match.range, in: trimmed) else { continue }

            var remainder = String(trimmed[..<swiftRange.lowerBound])
            remainder = remainder.trimmingCharacters(in: .whitespacesAndNewlines)
            // The match consumes the separator before the phrase; keep the
            // sentence punctuation that belongs to the remaining text.
            if let separator = trimmed[swiftRange].unicodeScalars.first,
               CharacterSet(charactersIn: ".,;:!?…").contains(separator) {
                remainder += String(separator)
            }
            return Parsed(text: remainder, command: .pressEnter)
        }

        return Parsed(text: text, command: nil)
    }
}
