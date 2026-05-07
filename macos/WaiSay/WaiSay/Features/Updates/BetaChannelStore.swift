import Foundation
import Sparkle

enum BetaChannelStore {
    static let userDefaultsKey = "receiveBetaUpdates"
    static let channelName = "beta"

    static var isOptedIn: Bool {
        UserDefaults.standard.bool(forKey: userDefaultsKey)
    }
}

final class BetaChannelUpdaterDelegate: NSObject, SPUUpdaterDelegate {
    func allowedChannels(for updater: SPUUpdater) -> Set<String> {
        BetaChannelStore.isOptedIn ? Set([BetaChannelStore.channelName]) : Set()
    }
}
