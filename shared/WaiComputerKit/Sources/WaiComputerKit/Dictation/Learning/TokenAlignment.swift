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
        var tokens: [String] = []
        var current: [Character] = []
        // Connector characters (apostrophes / hyphens) are only kept when they
        // sit *between* two word characters. We buffer them while inside a token
        // and commit them only once a following word character arrives.
        var pendingConnectors: [Character] = []

        func flush() {
            if !current.isEmpty {
                tokens.append(String(current))
            }
            current.removeAll(keepingCapacity: true)
            pendingConnectors.removeAll(keepingCapacity: true)
        }

        for ch in text {
            if ch.isLetter || ch.isNumber {
                if !current.isEmpty && !pendingConnectors.isEmpty {
                    // We had buffered connectors between two word chars — keep them.
                    current.append(contentsOf: pendingConnectors)
                    pendingConnectors.removeAll(keepingCapacity: true)
                }
                current.append(ch)
            } else if isConnector(ch) {
                if current.isEmpty {
                    // Leading connector (e.g. "-foo" or "'quoted") — it is a
                    // separator, not part of a token. Drop it.
                    continue
                }
                // Buffer it; only kept if another word char follows.
                pendingConnectors.append(ch)
            } else {
                // Whitespace or other punctuation — hard separator.
                flush()
            }
        }
        flush()
        return tokens
    }

    /// Normalize a token for equality comparison: Unicode case-fold
    /// (`lowercased()` — correct for Cyrillic on Apple platforms) and strip
    /// leading/trailing punctuation, NFC. Used to decide whether two tokens are
    /// "the same" (case/punctuation-only differences are NOT edits).
    public static func normalize(_ token: String) -> String {
        // Case-fold first (ICU-correct on Apple, folds Cyrillic), then canonical
        // compose (NFC) so combining marks compare equal to precomposed forms.
        let folded = token.lowercased().precomposedStringWithCanonicalMapping
        let scalars = Array(folded)
        // Strip leading / trailing characters that are not letters or numbers.
        var start = scalars.startIndex
        var end = scalars.endIndex
        while start < end, !scalars[start].isLetter, !scalars[start].isNumber {
            start += 1
        }
        while end > start {
            let last = scalars[end - 1]
            if last.isLetter || last.isNumber { break }
            end -= 1
        }
        return String(scalars[start..<end])
    }

    /// Damerau-Levenshtein alignment of two token arrays. Tokens whose
    /// `normalize` forms are equal align as `.match`; differing ones become
    /// `.substitute` / `.insert` / `.delete`. Order is preserved.
    public static func align(_ produced: [String], _ edited: [String]) -> [Op] {
        let n = produced.count
        let m = edited.count

        // Fast paths for empty inputs.
        if n == 0 && m == 0 { return [] }
        if n == 0 { return edited.map { Op.insert($0) } }
        if m == 0 { return produced.map { Op.delete($0) } }

        // Precompute normalized forms once.
        let pNorm = produced.map(normalize)
        let eNorm = edited.map(normalize)

        // Damerau-Levenshtein DP table. cost[i][j] = edit distance between the
        // first i produced tokens and first j edited tokens.
        var cost = Array(repeating: Array(repeating: 0, count: m + 1), count: n + 1)
        for i in 0...n { cost[i][0] = i }
        for j in 0...m { cost[0][j] = j }

        for i in 1...n {
            for j in 1...m {
                let subCost = (pNorm[i - 1] == eNorm[j - 1]) ? 0 : 1
                var best = min(
                    cost[i - 1][j] + 1,        // delete produced[i-1]
                    cost[i][j - 1] + 1,        // insert edited[j-1]
                    cost[i - 1][j - 1] + subCost // substitute / match
                )
                // Adjacent transposition (Damerau): produced[i-2,i-1] swapped to
                // edited[j-2,j-1]. Compared on normalized forms.
                if i >= 2, j >= 2,
                   pNorm[i - 1] == eNorm[j - 2],
                   pNorm[i - 2] == eNorm[j - 1] {
                    best = min(best, cost[i - 2][j - 2] + 1)
                }
                cost[i][j] = best
            }
        }

        // Backtrace from (n, m) to (0, 0), emitting ops in reverse then flipping.
        var ops: [Op] = []
        var i = n
        var j = m
        while i > 0 || j > 0 {
            // Transposition step.
            if i >= 2, j >= 2,
               pNorm[i - 1] == eNorm[j - 2],
               pNorm[i - 2] == eNorm[j - 1],
               cost[i][j] == cost[i - 2][j - 2] + 1 {
                // Emit the two swapped tokens (reverse order, flipped later).
                // Both surfaces differ in position only; surface them as the
                // edited tokens so the corrected text is reconstructable.
                ops.append(.substitute(from: produced[i - 1], to: edited[j - 1]))
                ops.append(.substitute(from: produced[i - 2], to: edited[j - 2]))
                i -= 2
                j -= 2
                continue
            }

            if i > 0, j > 0 {
                let subCost = (pNorm[i - 1] == eNorm[j - 1]) ? 0 : 1
                if cost[i][j] == cost[i - 1][j - 1] + subCost {
                    if subCost == 0 {
                        // Same normalized form ⇒ match. Carry the edited surface.
                        ops.append(.match(edited[j - 1]))
                    } else {
                        ops.append(.substitute(from: produced[i - 1], to: edited[j - 1]))
                    }
                    i -= 1
                    j -= 1
                    continue
                }
            }
            if i > 0, cost[i][j] == cost[i - 1][j] + 1 {
                ops.append(.delete(produced[i - 1]))
                i -= 1
                continue
            }
            // Remaining case: insertion.
            ops.append(.insert(edited[j - 1]))
            j -= 1
        }

        return ops.reversed()
    }

    /// Find the best contiguous run in `haystack` that aligns with `needle`
    /// (used to locate the text we inserted inside a larger edited field).
    /// Returns the haystack index range, or nil if `needle` is not
    /// substantially present (so we don't attribute unrelated edits).
    public static func locate(_ needle: [String], in haystack: [String]) -> Range<Int>? {
        let needleCount = needle.count
        if needleCount == 0 { return nil }
        if haystack.isEmpty { return nil }

        let needleNorm = needle.map(normalize)
        let haystackNorm = haystack.map(normalize)

        // Minimum fraction of needle tokens that must match in the best window.
        let minMatches = Int((Double(needleCount) * 0.6).rounded(.up))

        var bestRange: Range<Int>? = nil
        var bestScore = -1          // matched normalized tokens in the window
        var bestPenalty = Int.max   // length difference (tie-breaker)

        // Allow the window length to vary slightly around the needle length so a
        // few inserts/deletes inside the inserted run don't break the location.
        let slack = max(1, needleCount / 4)
        let minLen = max(1, needleCount - slack)
        let maxLen = min(haystack.count, needleCount + slack)
        guard minLen <= maxLen else { return nil }

        for windowLen in minLen...maxLen {
            if windowLen > haystack.count { break }
            let lastStart = haystack.count - windowLen
            for start in 0...lastStart {
                let window = Array(haystackNorm[start..<(start + windowLen)])
                let matches = normalizedMatchCount(needleNorm, window)
                let penalty = abs(windowLen - needleCount)
                if matches > bestScore || (matches == bestScore && penalty < bestPenalty) {
                    bestScore = matches
                    bestPenalty = penalty
                    bestRange = start..<(start + windowLen)
                }
            }
        }

        guard let range = bestRange, bestScore >= minMatches else { return nil }
        return range
    }

    // MARK: - Private helpers

    /// True for intra-word connector characters: straight/curly apostrophes and
    /// the hyphen-minus. (Em/en dashes are treated as separators by intent.)
    private static func isConnector(_ ch: Character) -> Bool {
        switch ch {
        case "'", "\u{2019}", "-":  // apostrophe, right single quote, hyphen-minus
            return true
        default:
            return false
        }
    }

    /// Count how many already-normalized needle tokens align as matches against
    /// an already-normalized window, via the same edit-distance backtrace logic.
    /// Operates on normalized forms directly (no re-normalization).
    private static func normalizedMatchCount(_ needle: [String], _ window: [String]) -> Int {
        let n = needle.count
        let m = window.count
        if n == 0 || m == 0 { return 0 }

        var cost = Array(repeating: Array(repeating: 0, count: m + 1), count: n + 1)
        for i in 0...n { cost[i][0] = i }
        for j in 0...m { cost[0][j] = j }
        for i in 1...n {
            for j in 1...m {
                let subCost = (needle[i - 1] == window[j - 1]) ? 0 : 1
                cost[i][j] = min(
                    cost[i - 1][j] + 1,
                    cost[i][j - 1] + 1,
                    cost[i - 1][j - 1] + subCost
                )
            }
        }

        // Backtrace counting only zero-cost diagonal steps (true matches).
        var matches = 0
        var i = n
        var j = m
        while i > 0 || j > 0 {
            if i > 0, j > 0 {
                let subCost = (needle[i - 1] == window[j - 1]) ? 0 : 1
                if cost[i][j] == cost[i - 1][j - 1] + subCost {
                    if subCost == 0 { matches += 1 }
                    i -= 1
                    j -= 1
                    continue
                }
            }
            if i > 0, cost[i][j] == cost[i - 1][j] + 1 {
                i -= 1
                continue
            }
            j -= 1
        }
        return matches
    }
}
