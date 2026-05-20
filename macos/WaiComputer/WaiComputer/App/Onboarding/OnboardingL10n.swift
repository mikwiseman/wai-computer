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
