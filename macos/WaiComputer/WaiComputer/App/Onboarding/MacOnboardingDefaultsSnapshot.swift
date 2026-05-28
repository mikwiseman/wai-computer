import Foundation

struct MacOnboardingDefaultsSnapshot {
    static let onboardingCompletedKey = "nativeOnboardingV4Completed"
    static let onboardingCurrentPageKey = "nativeOnboardingV4CurrentPage"
    static let preAuthOnboardingCompletedKey = "nativeOnboardingV5PreAuthCompleted"
    static let preAuthOnboardingCurrentPageKey = "nativeOnboardingV5PreAuthCurrentPage"
    static let postAuthOnboardingCurrentPageKey = "nativeOnboardingV5PostAuthCurrentPage"
    static let legacyOnboardingCompletedKeys = ["nativeOnboardingV2Completed", "nativeOnboardingV3Completed"]
    static let onboardingMicAcknowledgedKey = "onboardingMicAcknowledged"
    static let onboardingSystemAudioSetupKey = "onboardingSystemAudioSetupCompleted"

    private static let postAuthOnboardingCompletedKeyPrefix = "nativeOnboardingV5PostAuthCompleted."

    private let boolValues: [String: Bool]

    static func postAuthOnboardingCompletedKey(userId: String) -> String {
        "\(postAuthOnboardingCompletedKeyPrefix)\(userId)"
    }

    static func capture(
        defaults: UserDefaults = .standard,
        userId: String?
    ) -> MacOnboardingDefaultsSnapshot {
        var keys = [
            onboardingCompletedKey,
            preAuthOnboardingCompletedKey,
            onboardingMicAcknowledgedKey,
            onboardingSystemAudioSetupKey,
        ]
        keys.append(contentsOf: legacyOnboardingCompletedKeys)
        if let userId {
            keys.append(postAuthOnboardingCompletedKey(userId: userId))
        }

        let values = keys.reduce(into: [String: Bool]()) { result, key in
            guard defaults.object(forKey: key) != nil else { return }
            result[key] = defaults.bool(forKey: key)
        }
        return MacOnboardingDefaultsSnapshot(boolValues: values)
    }

    func restore(to defaults: UserDefaults = .standard) {
        for (key, value) in boolValues {
            defaults.set(value, forKey: key)
        }
        defaults.synchronize()
    }
}
