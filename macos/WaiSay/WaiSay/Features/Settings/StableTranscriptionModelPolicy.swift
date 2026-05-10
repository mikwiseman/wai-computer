import Foundation
import WaiSayKit

enum StableTranscriptionModelPolicy {
    static let dictationLiveProvider = "elevenlabs"
    static let dictationLiveModel = "scribe_v2_realtime"
    static let recordingLiveProvider = "elevenlabs"
    static let recordingLiveModel = "scribe_v2_realtime"
    static let fileProvider = "elevenlabs"
    static let fileModel = "scribe_v2"
    static let postFilterProvider = "anthropic"
    static let postFilterModel = "claude-haiku-4-5"

    static let dictationLiveSelection = "\(dictationLiveProvider):\(dictationLiveModel)"
    static let recordingLiveSelection = "\(recordingLiveProvider):\(recordingLiveModel)"
    static let fileSelection = "\(fileProvider):\(fileModel)"
    static let postFilterSelection = "\(postFilterProvider):\(postFilterModel)"

    static let dictationLiveLabel = "ElevenLabs Scribe v2 Realtime"
    static let recordingLiveLabel = "ElevenLabs Scribe v2 Realtime"
    static let fileLabel = "ElevenLabs Scribe v2"
    static let postFilterLabel = "Claude Haiku 4.5"

    static let dictationLiveDescription = "Default stable dictation path."
    static let recordingLiveDescription = "Default live recording transcription path."
    static let fileDescription = "Default full-session and uploaded-file transcription path."
    static let postFilterDescription = "Default low-latency cleanup for dictated text."

    static func isStable(_ settings: UserSettings) -> Bool {
        settings.dictationLiveSTTProvider == dictationLiveProvider &&
            settings.dictationLiveSTTModel == dictationLiveModel &&
            settings.recordingLiveSTTProvider == recordingLiveProvider &&
            settings.recordingLiveSTTModel == recordingLiveModel &&
            settings.fileSTTProvider == fileProvider &&
            settings.fileSTTModel == fileModel &&
            settings.dictationPostFilterEnabled &&
            settings.dictationPostFilterProvider == postFilterProvider &&
            settings.dictationPostFilterModel == postFilterModel
    }

    static var updateRequest: UpdateSettingsRequest {
        UpdateSettingsRequest(
            dictationLiveSTTProvider: dictationLiveProvider,
            dictationLiveSTTModel: dictationLiveModel,
            recordingLiveSTTProvider: recordingLiveProvider,
            recordingLiveSTTModel: recordingLiveModel,
            fileSTTProvider: fileProvider,
            fileSTTModel: fileModel,
            dictationPostFilterEnabled: true,
            dictationPostFilterProvider: postFilterProvider,
            dictationPostFilterModel: postFilterModel
        )
    }

    @MainActor
    static func enforceIfNeeded(apiClient: APIClient, settings: UserSettings) async throws -> UserSettings {
        guard !DeveloperSettingsStore.shared.developerModeEnabled else { return settings }
        guard !isStable(settings) else { return settings }
        return try await apiClient.updateSettings(updateRequest)
    }
}
