import Foundation

/// Hours-aware clock strings for UI display. A 3.5-hour meeting must read
/// "3:28:40", never "208:40" — minutes only roll up, they never exceed 59.
///
/// Not for transcript export/copy: `TranscriptRendering.timestampLabel` keeps
/// byte-parity with the backend's `_format_timestamp_short` and stays `M:SS`.
public enum ClockDuration {
    /// Compact form for lists and metadata: "0:53", "28:40", "3:28:40".
    public static func string(seconds: Int) -> String {
        let clamped = max(0, seconds)
        let hours = clamped / 3600
        let minutes = (clamped % 3600) / 60
        let secs = clamped % 60
        if hours > 0 {
            return String(format: "%d:%02d:%02d", hours, minutes, secs)
        }
        return String(format: "%d:%02d", minutes, secs)
    }

    /// Zero-padded form for ticking timers and timestamp columns where
    /// vertical alignment matters: "00:53", "28:40", "1:00:53".
    public static func padded(seconds: Int) -> String {
        let clamped = max(0, seconds)
        let hours = clamped / 3600
        let minutes = (clamped % 3600) / 60
        let secs = clamped % 60
        if hours > 0 {
            return String(format: "%d:%02d:%02d", hours, minutes, secs)
        }
        return String(format: "%02d:%02d", minutes, secs)
    }
}
