import Foundation
import SwiftUI
import os

private let log = Logger(subsystem: "is.waiwai.computer.localization", category: "language-manager")

/// Drives the app's in-session language.
///
/// Three layers:
///
/// 1. **First-launch seeding** — reads ``WAIDownloadRegion`` from
///    ``Info.plist`` (stamped at archive time by the build script:
///    `global` or `ru`). If the user has never picked a language yet,
///    we seed ``AppleLanguages`` so the next process launch boots in
///    Russian for `ru` DMG installs and follows ``Locale.preferredLanguages``
///    otherwise.
///
/// 2. **In-session switching** — ``LanguageManager.shared.preferredLocale``
///    feeds ``.environment(\.locale, …)`` on the root SwiftUI view, so
///    every ``Text("key")`` re-resolves the moment the user picks a new
///    language in Settings. No restart needed for SwiftUI views.
///
/// 3. **Persistence** — the user's pick is stored in ``UserDefaults``
///    under ``waiUserLanguage`` and survives Sparkle updates (Info.plist
///    ``WAIDownloadRegion`` is only consulted on a fresh install).
@MainActor
public final class LanguageManager: ObservableObject {
    public static let shared = LanguageManager()

    /// Languages WaiComputer ships UI translations for. Expand when adding
    /// new locales — the manager will surface them in the Settings picker.
    public enum SupportedLanguage: String, CaseIterable, Identifiable {
        case followSystem = "system"
        case english = "en"
        case russian = "ru"

        public var id: String { rawValue }

        public var displayName: String {
            switch self {
            case .followSystem: return "Follow system"
            case .english: return "English"
            case .russian: return "Русский"
            }
        }

        /// Native locale name shown when the picker is in another language.
        public var nativeDisplayName: String {
            switch self {
            case .followSystem: return NSLocalizedString("language.followSystem", value: "Follow system", comment: "Language picker option")
            case .english: return "English"
            case .russian: return "Русский"
            }
        }
    }

    private static let userDefaultsKey = "waiUserLanguage"
    private static let downloadRegionInfoPlistKey = "WAIDownloadRegion"

    @Published public private(set) var current: SupportedLanguage

    public init(defaults: UserDefaults = .standard, bundle: Bundle = .main) {
        let stored = defaults.string(forKey: Self.userDefaultsKey)
        if let stored, let lang = SupportedLanguage(rawValue: stored) {
            self.current = lang
        } else {
            // First launch: pick a default based on the build-time
            // WAIDownloadRegion stamp. We do NOT write to UserDefaults yet —
            // the user hasn't made a choice. We do, however, push the
            // expected `AppleLanguages` array so the next time the process
            // boots it comes up in the right language.
            let region = bundle.object(forInfoDictionaryKey: Self.downloadRegionInfoPlistKey) as? String
            let resolved = Self.resolveFirstLaunchDefault(downloadRegion: region)
            self.current = resolved
            Self.seedAppleLanguagesIfNeeded(for: resolved, defaults: defaults)
        }
    }

    public var preferredLocale: Locale {
        switch current {
        case .followSystem:
            return Locale.current
        case .english:
            return Locale(identifier: "en")
        case .russian:
            return Locale(identifier: "ru")
        }
    }

    public func setLanguage(_ language: SupportedLanguage, defaults: UserDefaults = .standard) {
        guard current != language else { return }
        current = language
        defaults.set(language.rawValue, forKey: Self.userDefaultsKey)
        Self.seedAppleLanguagesIfNeeded(for: language, defaults: defaults)
        log.notice("Language switched to \(language.rawValue, privacy: .public)")
    }

    /// First-launch decision: if the DMG was tagged ``ru``, default to
    /// Russian; otherwise default to English. The user can still choose
    /// "Follow system" later in Settings, but onboarding starts in the
    /// language matching the downloaded build.
    private static func resolveFirstLaunchDefault(downloadRegion: String?) -> SupportedLanguage {
        switch downloadRegion?.lowercased() {
        case "ru":
            return .russian
        default:
            return .english
        }
    }

    private static func seedAppleLanguagesIfNeeded(
        for language: SupportedLanguage, defaults: UserDefaults
    ) {
        switch language {
        case .followSystem:
            defaults.removeObject(forKey: "AppleLanguages")
        case .english:
            defaults.set(["en"], forKey: "AppleLanguages")
        case .russian:
            defaults.set(["ru"], forKey: "AppleLanguages")
        }
    }
}

/// Convenience root-view modifier that wires `LanguageManager` into the
/// SwiftUI environment. Updates flow downward through `\.locale`, so any
/// `Text("key")` lookup re-resolves through the user's preferred bundle.
public struct LanguageManagedRoot<Content: View>: View {
    @ObservedObject private var manager = LanguageManager.shared
    private let content: () -> Content

    public init(@ViewBuilder content: @escaping () -> Content) {
        self.content = content
    }

    public var body: some View {
        content()
            .environment(\.locale, manager.preferredLocale)
    }
}
