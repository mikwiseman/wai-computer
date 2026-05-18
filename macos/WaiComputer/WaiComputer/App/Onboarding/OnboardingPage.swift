import Foundation

enum OnboardingPage: Int, CaseIterable, Identifiable {
    case welcome
    case valueProps
    case permission
    case voiceSetup
    case languages
    case hotkey
    case sandbox

    var id: Int { rawValue }

    var breadcrumbLabel: String {
        switch self {
        case .welcome: return "Welcome"
        case .valueProps: return "What"
        case .permission: return "Allow"
        case .voiceSetup: return "Voice"
        case .languages: return "Languages"
        case .hotkey: return "Hotkey"
        case .sandbox: return "Try"
        }
    }
}
