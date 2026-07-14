import Foundation
import WaiComputerKit

enum OnboardingPage: Int, CaseIterable, Identifiable {
    case welcome
    case permission
    case languages
    case hotkey
    case sandbox
    case voiceSetup

    var id: Int { rawValue }

    func breadcrumbLabel(language: LanguageManager.SupportedLanguage) -> String {
        switch self {
        case .welcome:
            return OnboardingL10n.text("Welcome", "Старт", language: language)
        case .permission:
            return OnboardingL10n.text("Allow", "Доступ", language: language)
        case .languages:
            return OnboardingL10n.text("Languages", "Языки", language: language)
        case .hotkey:
            return OnboardingL10n.text("Hotkey", "Клавиша", language: language)
        case .sandbox:
            return OnboardingL10n.text("Try", "Проба", language: language)
        case .voiceSetup:
            return OnboardingL10n.text("Voice", "Голос", language: language)
        }
    }
}

enum OnboardingPhase {
    case preAuth
    case postAuth

    var pages: [OnboardingPage] {
        switch self {
        case .preAuth:
            return [.welcome, .permission, .languages, .hotkey]
        case .postAuth:
            return [.sandbox, .voiceSetup]
        }
    }

    var currentPageKey: String {
        switch self {
        case .preAuth:
            return MacAppState.preAuthOnboardingCurrentPageKey
        case .postAuth:
            return MacAppState.postAuthOnboardingCurrentPageKey
        }
    }
}
