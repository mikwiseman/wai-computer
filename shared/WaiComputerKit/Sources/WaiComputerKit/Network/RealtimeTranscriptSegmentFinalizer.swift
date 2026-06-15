import Foundation

public enum RealtimeTranscriptSegmentFinalizer {
    public static func finalizedSegments(
        providerSegments: [LiveTranscriptSegment],
        liveTranscript: String?,
        liveSpeaker: String?,
        durationSeconds: TimeInterval,
        didFinalize: Bool
    ) -> [LiveTranscriptSegment] {
        let providerTranscript = transcriptText(from: providerSegments)
        let selected = RealtimeTranscriptCandidateSelector.select([
            providerTranscript.isEmpty ? nil : providerTranscript,
            liveTranscript,
        ])
        guard !selected.isEmpty else { return providerSegments }

        if selected == providerTranscript || normalized(selected) == normalized(providerTranscript) {
            return providerSegments
        }

        if !didFinalize, providerSegments.isEmpty == false {
            let providerTokens = tokenList(providerTranscript)
            let selectedTokens = tokenList(selected)
            if selectedTokens.count > providerTokens.count,
               Array(selectedTokens.prefix(providerTokens.count)) == providerTokens {
                return providerSegments
            }
        }

        return [
            syntheticSegment(
                text: selected,
                providerSegments: providerSegments,
                liveSpeaker: liveSpeaker,
                durationSeconds: durationSeconds
            )
        ]
    }

    private static func transcriptText(from segments: [LiveTranscriptSegment]) -> String {
        segments
            .map { $0.text.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
            .joined(separator: " ")
    }

    private static func syntheticSegment(
        text: String,
        providerSegments: [LiveTranscriptSegment],
        liveSpeaker: String?,
        durationSeconds: TimeInterval
    ) -> LiveTranscriptSegment {
        let durationMs = Int(max(durationSeconds, 0) * 1_000)
        let startMs = providerSegments.isEmpty ? max(durationMs - 1_000, 0) : 0
        let endMs = max(providerSegments.map(\.endMs).max() ?? durationMs, durationMs, startMs)
        let providerSpeakers = Set(providerSegments.compactMap(\.speaker).filter { !$0.isEmpty })
        let speaker = providerSpeakers.count == 1 ? providerSpeakers.first : liveSpeaker

        return LiveTranscriptSegment(
            text: text,
            speaker: speaker,
            isFinal: true,
            startMs: startMs,
            endMs: endMs,
            confidence: 0
        )
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
}
