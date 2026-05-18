import Foundation
import WaiComputerKit

enum SystemAudioWarningPolicy {
    /// Returns the banner text to show, or nil to hide.
    ///
    /// We surface the warning whenever the user explicitly requested system audio
    /// capture (mic + system, or system-only) and the capture pipeline reports a
    /// failure. Recording type does NOT gate this — if someone chose "Mic + System
    /// Audio" they need to know the system audio half is silent, regardless of
    /// whether they tagged the recording as a note, meeting, or reflection.
    static func visibleBannerText(
        recordingType: RecordingType,
        requestedSystemAudio: Bool,
        warning: String?
    ) -> String? {
        _ = recordingType  // intentionally unused; preserved for ABI/callsite stability
        guard requestedSystemAudio else { return nil }
        guard let trimmed = warning?.trimmingCharacters(in: .whitespacesAndNewlines), !trimmed.isEmpty else {
            return nil
        }
        return trimmed
    }
}
