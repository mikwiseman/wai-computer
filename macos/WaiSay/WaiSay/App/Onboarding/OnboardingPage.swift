import Foundation

enum OnboardingPage: Int, CaseIterable, Identifiable {
    case welcome
    case valueProps
    case permission
    case hotkey
    case sandbox

    var id: Int { rawValue }

    var breadcrumbLabel: String {
        switch self {
        case .welcome: return "Welcome"
        case .valueProps: return "What"
        case .permission: return "Allow"
        case .hotkey: return "Hotkey"
        case .sandbox: return "Try"
        }
    }
}
