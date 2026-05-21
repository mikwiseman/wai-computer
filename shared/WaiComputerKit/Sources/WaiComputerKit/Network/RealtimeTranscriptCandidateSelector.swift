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
            if candidateNormalized.contains(bestNormalized) {
                best = candidate
                continue
            }
            if bestNormalized.contains(candidateNormalized) {
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
}
