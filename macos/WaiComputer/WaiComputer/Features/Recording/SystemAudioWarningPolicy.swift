import Foundation
import WaiComputerKit

enum SystemAudioWarningPolicy {
    static func visibleBannerText(
        recordingType: RecordingType,
        requestedSystemAudio: Bool,
        warning: String?
    ) -> String? {
        guard requestedSystemAudio else { return nil }
        guard let trimmed = warning?.trimmingCharacters(in: .whitespacesAndNewlines), !trimmed.isEmpty else {
            return nil
        }

        return recordingType == .meeting ? trimmed : nil
    }
}
