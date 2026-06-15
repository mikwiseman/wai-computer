import Foundation

/// Picks the most complete transcript from provider close output, provider
/// deltas, and the UI accumulator. Short dictation sessions can finalize while
/// the last live/interim text is still fuller than the provider's drained
/// segment list, so prefer completeness over source order.
public enum RealtimeTranscriptCandidateSelector {
    public static func select(_ candidates: [String?]) -> String {
        let cleaned = candidates.compactMap { candidate -> String? in
            let value = candidate?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            return value.isEmpty ? nil : value
        }
        guard var best = cleaned.first else { return "" }

        for candidate in cleaned.dropFirst() {
            let bestNormalized = normalized(best)
            let candidateNormalized = normalized(candidate)
            guard !candidateNormalized.isEmpty else { continue }

            if bestNormalized == candidateNormalized {
                continue
            }
            if repeatsPrefixAfterCompleteCandidate(
                complete: best,
                candidate: candidate
            ) {
                continue
            }
            let bestTokens = tokenList(best)
            let candidateTokens = tokenList(candidate)
            if appendsTailAfterCompleteCandidate(
                completeTokens: bestTokens,
                candidateTokens: candidateTokens
            ) {
                continue
            }
            if containsTokenSequence(candidateTokens, bestTokens) {
                best = candidate
                continue
            }
            if containsTokenSequence(bestTokens, candidateTokens) {
                continue
            }
            if bestTokens.isEmpty || candidateTokens.isEmpty {
                if candidateNormalized.contains(bestNormalized) {
                    best = candidate
                    continue
                }
                if bestNormalized.contains(candidateNormalized) {
                    continue
                }
            }
        }

        return best
    }

    private static func normalized(_ text: String) -> String {
        text
            .split(whereSeparator: \.isWhitespace)
            .joined(separator: " ")
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
    }

    private static func tokenList(_ text: String) -> [String] {
        text
            .lowercased()
            .components(separatedBy: CharacterSet.alphanumerics.inverted)
            .filter { !$0.isEmpty }
    }

    private static func repeatsPrefixAfterCompleteCandidate(
        complete: String,
        candidate: String
    ) -> Bool {
        let completeTokens = tokenList(complete)
        let candidateTokens = tokenList(candidate)
        guard !completeTokens.isEmpty,
              candidateTokens.count > completeTokens.count,
              Array(candidateTokens.prefix(completeTokens.count)) == completeTokens else {
            return false
        }
        let suffix = Array(candidateTokens.dropFirst(completeTokens.count))
        guard !suffix.isEmpty,
              suffix.count < completeTokens.count else {
            return false
        }
        return Array(completeTokens.prefix(suffix.count)) == suffix
    }

    private static func containsTokenSequence(_ tokens: [String], _ phrase: [String]) -> Bool {
        guard !phrase.isEmpty,
              tokens.count >= phrase.count else {
            return false
        }
        if tokens == phrase {
            return true
        }
        for start in 0...(tokens.count - phrase.count) {
            if Array(tokens[start..<start + phrase.count]) == phrase {
                return true
            }
        }
        return false
    }

    private static func appendsTailAfterCompleteCandidate(
        completeTokens: [String],
        candidateTokens: [String]
    ) -> Bool {
        guard !completeTokens.isEmpty,
              candidateTokens.count > completeTokens.count else {
            return false
        }
        return Array(candidateTokens.prefix(completeTokens.count)) == completeTokens
    }
}
