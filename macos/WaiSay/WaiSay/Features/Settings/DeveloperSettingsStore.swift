import Foundation
import SwiftUI
import WaiSayKit

/// Speech-to-text provider for the dictation pipeline. Persisted as the raw
/// `String` value so Swift renames don't silently flip a power user's choice.
public enum DictationProvider: String, CaseIterable, Identifiable {
    /// Default since the build 67 rollback. Routed through
    /// `WebSocketManager` → ElevenLabs Scribe v2 RT WebSocket directly.
    case elevenLabs = "elevenlabs"
    /// Phase 4 path — Inworld unified STT API with the
    /// `soniox/stt-rt-v4` model under the hood. Benefits from
    /// `soniox_config.context.terms` biasing wired in build 76.
    case inworld = "inworld"

    public var id: String { rawValue }

    public var displayName: String {
        switch self {
        case .elevenLabs: return "ElevenLabs Scribe v2 RT"
        case .inworld:    return "Inworld + Soniox v4 RT (experimental)"
        }
    }

    public var subtitle: String {
        switch self {
        case .elevenLabs:
            return "Default. The proven path since build 67."
        case .inworld:
            return "Soniox v4 RT under the hood. Sometimes better on casual speech, sometimes silent in production. Watch the dictation overlay for failures and switch back if needed."
        }
    }
}

/// Single source of truth for Developer Mode settings — opt-in toggles
/// surfaced under Settings → About → Enable developer mode that expose
/// experimental knobs. Mirrors `BetaChannelStore`'s minimal pattern, with
/// a `UserDefaults` parameter so tests can use isolated suites instead of
/// polluting `.standard`.
@MainActor
public final class DeveloperSettingsStore: ObservableObject {
    /// Process-wide singleton bound to `UserDefaults.standard`. Used by
    /// `DictationManager` (which is also `@MainActor`) for direct synchronous
    /// reads at the start of each dictation session — no `await` hop needed.
    public static let shared = DeveloperSettingsStore(defaults: .standard)

    public static let developerModeEnabledKey = "developerModeEnabled"
    public static let dictationProviderKey = "dictationProvider"

    private let defaults: UserDefaults

    @Published public var developerModeEnabled: Bool {
        didSet {
            guard developerModeEnabled != oldValue else { return }
            defaults.set(developerModeEnabled, forKey: Self.developerModeEnabledKey)
            SentryHelper.addBreadcrumb(
                category: "settings.developer",
                message: "developer mode toggled",
                data: ["enabled": developerModeEnabled]
            )
        }
    }

    @Published public var dictationProvider: DictationProvider {
        didSet {
            guard dictationProvider != oldValue else { return }
            defaults.set(dictationProvider.rawValue, forKey: Self.dictationProviderKey)
            SentryHelper.addBreadcrumb(
                category: "settings.developer",
                message: "dictation provider changed",
                data: ["provider": dictationProvider.rawValue]
            )
        }
    }

    public init(defaults: UserDefaults) {
        self.defaults = defaults
        // bool(forKey:) returns false when the key is absent — that's the
        // intended fresh-install default, so no special-casing needed.
        self.developerModeEnabled = defaults.bool(forKey: Self.developerModeEnabledKey)
        // Garbage / legacy values fall back to .elevenLabs so a stray rename
        // can't soft-brick someone's dictation.
        let raw = defaults.string(forKey: Self.dictationProviderKey)
        self.dictationProvider = raw.flatMap(DictationProvider.init(rawValue:)) ?? .elevenLabs
    }

    /// Clears developer-only experimental knobs back to defaults. Does NOT
    /// flip `developerModeEnabled` — the toggle is the user's intent, not a
    /// dev setting, so a "reset" would otherwise surprise them by hiding the
    /// section they're staring at.
    public func reset() {
        dictationProvider = .elevenLabs
    }
}
