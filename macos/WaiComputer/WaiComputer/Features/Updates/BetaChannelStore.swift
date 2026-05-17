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
