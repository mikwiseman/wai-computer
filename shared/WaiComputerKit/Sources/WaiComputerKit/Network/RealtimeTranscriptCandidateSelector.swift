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
            if candidateNormalized.contains(bestNormalized) {
                best = candidate
                continue
            }
            if bestNormalized.contains(candidateNormalized) {
                continue
            }
            let bestTokenPhrase = bestTokens.joined(separator: " ")
            let candidateTokenPhrase = candidateTokens.joined(separator: " ")
            if !bestTokenPhrase.isEmpty,
               candidateTokenPhrase.contains(bestTokenPhrase) {
                best = candidate
                continue
            }
            if !candidateTokenPhrase.isEmpty,
               bestTokenPhrase.contains(candidateTokenPhrase) {
                continue
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
