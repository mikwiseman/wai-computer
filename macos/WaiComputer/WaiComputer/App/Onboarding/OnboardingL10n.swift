import Foundation
import WaiComputerKit

enum OnboardingL10n {
    enum Language {
        case english
        case russian
    }

    static func language(for selection: LanguageManager.SupportedLanguage) -> Language {
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

    static func text(_ english: String, _ russian: String, language selection: LanguageManager.SupportedLanguage) -> String {
        switch language(for: selection) {
        case .english:
            return english
        case .russian:
            return russian
        }
    }
}

extension DictationHotkey {
    func onboardingLabel(language selection: LanguageManager.SupportedLanguage) -> String {
        switch self {
        case .rightOption:
            return OnboardingL10n.text("Right Option (\u{2325})", "Правая клавиша Option (\u{2325})", language: selection)
        case .leftOption:
            return OnboardingL10n.text("Left Option (\u{2325})", "Левая клавиша Option (\u{2325})", language: selection)
        case .rightCommand:
            return OnboardingL10n.text("Right Command (\u{2318})", "Правая клавиша Command (\u{2318})", language: selection)
        case .fn:
            return OnboardingL10n.text("Fn (Globe)", "Fn (Глобус)", language: selection)
        case .controlOption:
            return OnboardingL10n.text("Control + Option (\u{2303}\u{2325})", "Control + Option (\u{2303}\u{2325})", language: selection)
        }
    }

    func onboardingShortLabel(language selection: LanguageManager.SupportedLanguage) -> String {
        switch self {
        case .rightOption:
            return OnboardingL10n.text("\u{2325} (Right)", "\u{2325} справа", language: selection)
        case .leftOption:
            return OnboardingL10n.text("\u{2325} (Left)", "\u{2325} слева", language: selection)
        case .rightCommand:
            return OnboardingL10n.text("\u{2318} (Right)", "\u{2318} справа", language: selection)
        case .fn:
            return "Fn"
        case .controlOption:
            return "\u{2303}\u{2325}"
        }
    }
}
