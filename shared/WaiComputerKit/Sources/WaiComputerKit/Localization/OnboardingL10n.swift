import Foundation

/// Code-based bilingual text helper for in-app-language content, shared by
/// every WaiComputer client.
///
/// Use this (or a per-view `t(_:_:)` wrapper around it) instead of
/// `Text("key")` / `String(localized:)` for any string that must follow the
/// user's in-app ``LanguageManager`` selection. `String(localized:)` resolves
/// against the *system* locale and produces mixed-language UI when the app
/// language differs from the system language.
public enum OnboardingL10n {
    public enum Language {
        case english
        case russian
    }

    public static func language(for selection: LanguageManager.SupportedLanguage) -> Language {
        switch selection {
        case .russian:
            return .russian
        case .english:
            return .english
        case .followSystem:
            let preferred = Locale.preferredLanguages.first?.lowercased() ?? ""
            return preferred.hasPrefix("ru") ? .russian : .english
        }
    }

    public static func text(_ english: String, _ russian: String, language selection: LanguageManager.SupportedLanguage) -> String {
        switch language(for: selection) {
        case .english:
            return english
        case .russian:
            return russian
        }
    }
}
