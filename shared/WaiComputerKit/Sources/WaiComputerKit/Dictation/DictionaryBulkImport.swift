import Foundation

/// Parses a bulk-import file for the personal dictation dictionary.
///
/// One entry per line: a bare word, or `word<sep>replacement` where the
/// separator is the first tab, semicolon, or comma on the line. Blank lines,
/// `#` comments, and a `word,replacement` header are ignored. Entries are
/// deduplicated case-insensitively (first occurrence wins) and bounded to the
/// server's column limits so a bad file cannot flood the store.
public enum DictionaryBulkImport {
    public struct ParsedWord: Equatable, Sendable {
        public let word: String
        public let replacement: String?

        public init(word: String, replacement: String?) {
            self.word = word
            self.replacement = replacement
        }
    }

    public struct Result: Equatable, Sendable {
        /// Entries ready to add to the dictionary store, in file order.
        public let words: [ParsedWord]
        /// Non-empty lines that were dropped: duplicates, over the length or
        /// count limits. Comments and the header don't count.
        public let skippedLineCount: Int

        public init(words: [ParsedWord], skippedLineCount: Int) {
            self.words = words
            self.skippedLineCount = skippedLineCount
        }
    }

    /// Matches the backend `dictation_dictionary_words` column limits.
    public static let maxEntryLength = 200
    /// One import stays a curated vocabulary, not a data dump.
    public static let maxWords = 500

    private static let separators: [Character] = ["\t", ";", ","]

    public static func parse(_ contents: String) -> Result {
        var words: [ParsedWord] = []
        var seen: Set<String> = []
        var skipped = 0

        for rawLine in contents.split(omittingEmptySubsequences: false, whereSeparator: \.isNewline) {
            let line = rawLine.trimmingCharacters(in: .whitespaces)
            if line.isEmpty || line.hasPrefix("#") {
                continue
            }
            if isHeader(line) {
                continue
            }

            let (word, replacement) = splitEntry(line)
            guard !word.isEmpty,
                  word.count <= maxEntryLength,
                  (replacement?.count ?? 0) <= maxEntryLength
            else {
                skipped += 1
                continue
            }

            let key = word.lowercased()
            guard !seen.contains(key) else {
                skipped += 1
                continue
            }
            guard words.count < maxWords else {
                skipped += 1
                continue
            }
            seen.insert(key)
            words.append(ParsedWord(word: word, replacement: replacement))
        }

        return Result(words: words, skippedLineCount: skipped)
    }

    private static func isHeader(_ line: String) -> Bool {
        let normalized = line.lowercased().replacingOccurrences(of: " ", with: "")
        return normalized == "word,replacement"
            || normalized == "word;replacement"
            || normalized == "word\treplacement"
    }

    private static func splitEntry(_ line: String) -> (word: String, replacement: String?) {
        guard let separatorIndex = line.firstIndex(where: { separators.contains($0) }) else {
            return (line, nil)
        }
        let word = String(line[line.startIndex..<separatorIndex])
            .trimmingCharacters(in: .whitespaces)
        let replacement = String(line[line.index(after: separatorIndex)...])
            .trimmingCharacters(in: .whitespaces)
        return (word, replacement.isEmpty ? nil : replacement)
    }
}
