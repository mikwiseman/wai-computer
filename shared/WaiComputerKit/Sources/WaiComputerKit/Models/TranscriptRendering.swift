import Foundation

/// Transcript rendering styles. The recogniser emits short, pause-split utterances;
/// rendering one per line with a repeated `[Speaker, time]` prefix is unreadable.
/// Merging consecutive same-speaker utterances into turns is the shared primitive
/// (mirrors the backend `merge_segment_turns` and the web `mergeTurns`), and these
/// styles render the result:
///
/// - `plain`: flowing paragraphs, no timestamps; labels dropped for a single-speaker
///   recording (the "just give me the text" case).
/// - `speakers`: like `plain` but always shows the speaker label.
/// - `timestamped`: `[Speaker, M:SS] text` per turn (today's look, merged).
public enum TranscriptStyle: Sendable, Equatable {
    case plain
    case speakers
    case timestamped
}

/// Consecutive same-speaker utterances merged into a single speaker turn.
public struct TranscriptTurn: Identifiable, Sendable {
    /// Stable grouping identity (`person:<id>` / `speaker:<n>` / raw label / "").
    public let key: String
    /// Resolved human display label for the turn (e.g. "Speaker 1", "Anna").
    public let speaker: String
    public let startMs: Int?
    public let text: String
    /// Source utterances; `segments.first` drives the interactive speaker chip in the view.
    public let segments: [Segment]

    public var id: String { segments.first?.id ?? key }
}

public enum TranscriptRendering {
    private static let closingPunctuation: Set<Character> = [
        ",", ".", ";", ":", "!", "?", ")", "»", "”",
    ]

    /// Merge consecutive segments with the same resolved speaker into readable turns.
    /// Segments are ordered by `startMs` (missing timestamps sort last, stably) and
    /// empty-content segments are dropped.
    public static func mergeTurns(_ segments: [Segment], languageCode: String?) -> [TranscriptTurn] {
        let ordered = segments.enumerated().sorted { lhs, rhs in
            switch (lhs.element.startMs, rhs.element.startMs) {
            case let (l?, r?): return l == r ? lhs.offset < rhs.offset : l < r
            case (nil, .some): return false
            case (.some, nil): return true
            case (nil, nil): return lhs.offset < rhs.offset
            }
        }.map(\.element)

        var turns: [TranscriptTurn] = []
        var key: String?
        var speaker = ""
        var start: Int?
        var text = ""
        var members: [Segment] = []

        func flush() {
            guard let key else { return }
            turns.append(TranscriptTurn(key: key, speaker: speaker, startMs: start, text: text, segments: members))
        }

        for seg in ordered {
            let fragment = seg.content.trimmingCharacters(in: .whitespacesAndNewlines)
            if fragment.isEmpty { continue }
            let segKey = speakerKey(seg)
            if key == segKey {
                text = joinFragments(text, fragment)
                members.append(seg)
            } else {
                flush()
                key = segKey
                speaker = seg.userFacingSpeakerLabel(languageCode: languageCode)
                    ?? SpeakerLabelCopy.userFacingLabel("Speaker", languageCode: languageCode)
                    ?? "Speaker"
                start = seg.startMs
                text = fragment
                members = [seg]
            }
        }
        flush()
        return turns
    }

    /// Render merged turns as a transcript string in the requested style.
    public static func renderTranscript(_ turns: [TranscriptTurn], style: TranscriptStyle) -> String {
        guard !turns.isEmpty else { return "" }

        switch style {
        case .timestamped:
            return turns.map { turn in
                let ts = timestampLabel(turn.startMs)
                return ts.isEmpty
                    ? "[\(turn.speaker)] \(turn.text)"
                    : "[\(turn.speaker), \(ts)] \(turn.text)"
            }.joined(separator: "\n")
        case .plain, .speakers:
            let showLabels = style == .speakers || Set(turns.map(\.key)).count > 1
            return turns
                .map { showLabels ? "\($0.speaker): \($0.text)" : $0.text }
                .joined(separator: "\n\n")
        }
    }

    /// Convenience: merge + render in one call (used by copy buttons / export).
    public static func transcriptText(
        _ segments: [Segment],
        style: TranscriptStyle,
        languageCode: String?
    ) -> String {
        renderTranscript(mergeTurns(segments, languageCode: languageCode), style: style)
    }

    // MARK: - Internals

    /// Mirrors the backend `_segment_speaker_key`: identity for turn grouping.
    static func speakerKey(_ seg: Segment) -> String {
        if let personId = seg.personId, !personId.isEmpty { return "person:\(personId)" }
        let raw = (seg.speaker ?? seg.rawLabel ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        if let number = speakerNumber(from: raw) { return "speaker:\(number)" }
        return raw.lowercased()
    }

    private static func speakerNumber(from raw: String) -> Int? {
        let lower = raw.lowercased()
        for prefix in ["speaker", "спикер"] where lower.hasPrefix(prefix) {
            let rest = String(lower.dropFirst(prefix.count))
                .trimmingCharacters(in: CharacterSet(charactersIn: " _-"))
            guard !rest.isEmpty, rest.allSatisfy(\.isNumber) else { return nil }
            return Int(rest)
        }
        return nil
    }

    /// Join two utterance fragments with a single space, except before closing punctuation.
    static func joinFragments(_ existing: String, _ addition: String) -> String {
        if existing.isEmpty { return addition }
        if addition.isEmpty { return existing }
        if let first = addition.first, closingPunctuation.contains(first) {
            return existing + addition
        }
        return existing + " " + addition
    }

    /// `M:SS` (no leading zero on minutes), or "" when absent — parity with the backend
    /// `_format_timestamp_short`, so the timestamped copy matches web/export byte-for-byte.
    /// (Distinct from `Segment.formattedTimestamp`, which the UI renders as `MM:SS`.)
    static func timestampLabel(_ ms: Int?) -> String {
        guard let ms else { return "" }
        let seconds = ms / 1000
        return "\(seconds / 60):" + String(format: "%02d", seconds % 60)
    }
}
