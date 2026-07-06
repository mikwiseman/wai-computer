import Foundation
import WaiComputerKit

/// User preferences for ending a recording automatically once the
/// conversation is over. Persisted in UserDefaults (same store the Settings
/// toggles use via @AppStorage).
enum RecordingAutoStopSettings {
    static let enabledKey = "recordingAutoStopEnabled"
    static let silenceMinutesKey = "recordingAutoStopSilenceMinutes"
    static let actionKey = "recordingAutoStopAction"

    /// What to do when the countdown expires without a human response.
    enum Action: String {
        /// Finalize the recording: upload, transcribe, summarize.
        case stop
        /// Keep the session open but stop capturing audio.
        case pause
    }

    static let defaultSilenceMinutes = 4
    static let silenceMinuteChoices = [2, 4, 8, 15]

    static func isEnabled(defaults: UserDefaults = .standard) -> Bool {
        if defaults.object(forKey: enabledKey) == nil { return true }
        return defaults.bool(forKey: enabledKey)
    }

    static func silenceMinutes(defaults: UserDefaults = .standard) -> Int {
        let stored = defaults.integer(forKey: silenceMinutesKey)
        return silenceMinuteChoices.contains(stored) ? stored : defaultSilenceMinutes
    }

    static func action(defaults: UserDefaults = .standard) -> Action {
        guard let raw = defaults.string(forKey: actionKey),
              let action = Action(rawValue: raw) else { return .stop }
        return action
    }

    static func config(defaults: UserDefaults = .standard) -> ConversationAutoStopConfig {
        ConversationAutoStopConfig(
            silenceTimeout: TimeInterval(silenceMinutes(defaults: defaults) * 60),
            callEndedTimeout: 30,
            countdown: 60
        )
    }
}
