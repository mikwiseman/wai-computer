import Foundation

public enum DictationFinalTranscriptSelector {
    public static func captureLiveCandidate(
        liveTranscript: String,
        previousCandidate: String?
    ) -> String {
        let live = liveTranscript.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !live.isEmpty else {
            return previousCandidate?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        }
        return RealtimeTranscriptCandidateSelector.select([
            live,
            blankToNil(previousCandidate),
        ])
    }

    public static func select(
        providerTranscript: String?,
        liveTranscript: String?,
        liveTranscriptCandidate: String?,
        hasActiveInterim: Bool
    ) -> String {
        if hasActiveInterim {
            return RealtimeTranscriptCandidateSelector.select([
                blankToNil(liveTranscript),
                blankToNil(providerTranscript),
                blankToNil(liveTranscriptCandidate),
            ])
        }

        return RealtimeTranscriptCandidateSelector.select([
            blankToNil(providerTranscript),
            blankToNil(liveTranscript),
            blankToNil(liveTranscriptCandidate),
        ])
    }

    private static func blankToNil(_ text: String?) -> String? {
        let trimmed = text?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return trimmed.isEmpty ? nil : trimmed
    }
}
