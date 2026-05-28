import Foundation

/// Pick the dominant speaker across the word array from a Deepgram diarised
/// result. Returns `"speaker_<n>"` (matching the backend's raw_label
/// convention) or `nil` if diarisation is off, no word carries a speaker tag,
/// or the integers are negative (Deepgram has used `-1` historically for
/// "uncertain"; we treat those as no signal).
///
/// Duration-weighted: a single 2-second word from speaker 1 outweighs three
/// short words from speaker 0. This is what users perceive as "who is
/// speaking right now".
public enum DeepgramSpeakerLabel {
    public static func dominant(in alternative: [String: Any]) -> String? {
        guard let words = alternative["words"] as? [[String: Any]] else { return nil }
        var totals: [Int: Double] = [:]
        for word in words {
            guard let speaker = word["speaker"] as? Int, speaker >= 0 else { continue }
            let start = word["start"] as? Double ?? 0
            let end = word["end"] as? Double ?? start
            let weight = max(0.001, end - start)
            totals[speaker, default: 0] += weight
        }
        guard let dominant = totals.max(by: { $0.value < $1.value })?.key else { return nil }
        return "speaker_\(dominant)"
    }
}
