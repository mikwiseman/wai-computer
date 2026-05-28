import Foundation
import Sparkle

enum BetaChannelStore {
    static let userDefaultsKey = "receiveBetaUpdates"
    static let channelName = "beta"

    static var isOptedIn: Bool {
        UserDefaults.standard.bool(forKey: userDefaultsKey)
    }

    static func allowedChannels(isOptedIn: Bool) -> Set<String> {
        isOptedIn ? Set([channelName]) : Set()
    }
}

final class BetaChannelUpdaterDelegate: NSObject, SPUUpdaterDelegate {
    func allowedChannels(for updater: SPUUpdater) -> Set<String> {
        BetaChannelStore.allowedChannels(isOptedIn: BetaChannelStore.isOptedIn)
    }
}

enum RecordingAwareUpdatePolicy {
    static func shouldLetSparklePresentScheduledUpdate(isRecordingActive: Bool) -> Bool {
        !isRecordingActive
    }
}

@MainActor
final class RecordingAwareUpdateUserDriverDelegate: NSObject, @preconcurrency SPUStandardUserDriverDelegate {
    private let isRecordingActive: () -> Bool
    private var hasDeferredUpdateCheck = false

    init(isRecordingActive: @escaping () -> Bool) {
        self.isRecordingActive = isRecordingActive
    }

    var supportsGentleScheduledUpdateReminders: Bool {
        true
    }

    func deferUpdateCheckUntilIdle() {
        hasDeferredUpdateCheck = true
    }

    func presentDeferredUpdateIfIdle(using updaterController: SPUStandardUpdaterController?) {
        guard hasDeferredUpdateCheck, !isRecordingActive() else { return }
        hasDeferredUpdateCheck = false
        updaterController?.checkForUpdates(nil)
    }

    func standardUserDriverShouldHandleShowingScheduledUpdate(
        _ update: SUAppcastItem,
        andInImmediateFocus immediateFocus: Bool
    ) -> Bool {
        RecordingAwareUpdatePolicy.shouldLetSparklePresentScheduledUpdate(
            isRecordingActive: isRecordingActive()
        )
    }

    func standardUserDriverWillHandleShowingUpdate(
        _ handleShowingUpdate: Bool,
        forUpdate update: SUAppcastItem,
        state: SPUUserUpdateState
    ) {
        if !handleShowingUpdate {
            hasDeferredUpdateCheck = true
        }
    }

    func standardUserDriverDidReceiveUserAttention(forUpdate update: SUAppcastItem) {
        hasDeferredUpdateCheck = false
    }

    func standardUserDriverWillFinishUpdateSession() {
        if !isRecordingActive() {
            hasDeferredUpdateCheck = false
        }
    }
}
