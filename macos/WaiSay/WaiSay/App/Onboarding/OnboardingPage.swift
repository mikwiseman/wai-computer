import Foundation

enum OnboardingPage: Int, CaseIterable, Identifiable {
    case welcome
    case record
    case transcribe
    case dictate
    case languages
    case permission
    case verify

    var id: Int { rawValue }

    /// Short label shown in the top breadcrumb navigation.
    var breadcrumbLabel: String {
        switch self {
        case .welcome: return "Welcome"
        case .record: return "Record"
        case .transcribe: return "Understand"
        case .dictate: return "Dictate"
        case .languages: return "Languages"
        case .permission: return "Permissions"
        case .verify: return "Test"
        }
    }

    struct Content {
        let eyebrow: String
        let title: String
        let body: String
        let symbol: String?
        let useAppIcon: Bool
    }

    var content: Content {
        switch self {
        case .welcome:
            return Content(
                eyebrow: "WaiSay",
                title: "Your AI second brain for voice.",
                body: "Capture meetings, notes, and reflections — instantly searchable.",
                symbol: nil,
                useAppIcon: true
            )
        case .record:
            return Content(
                eyebrow: "Record",
                title: "One tap. Anywhere.",
                body: "Meetings, voice notes, late-night ideas. WaiSay keeps recording even when offline.",
                symbol: "mic.circle",
                useAppIcon: false
            )
        case .transcribe:
            return Content(
                eyebrow: "Understand",
                title: "Transcripts that think.",
                body: "Real-time transcription, AI summaries, action items, and key decisions — without the busywork.",
                symbol: "sparkles",
                useAppIcon: false
            )
        case .dictate:
            return Content(
                eyebrow: "Dictate",
                title: "Speak into anything.",
                body: "A global hotkey turns your voice into text in any app. You can set it up before signing in.",
                symbol: "keyboard.badge.eye",
                useAppIcon: false
            )
        case .languages:
            return Content(
                eyebrow: "Languages",
                title: "Pick your languages.",
                body: "Choose one for the lowest latency, several to switch fluidly, or auto-detect any language.",
                symbol: "globe",
                useAppIcon: false
            )
        case .permission:
            return Content(
                eyebrow: "Setup",
                title: "Set up voice access.",
                body: "Grant Microphone for recording, and Accessibility for the global hotkey and text insertion.",
                symbol: "lock.shield",
                useAppIcon: false
            )
        case .verify:
            return Content(
                eyebrow: "Test",
                title: "Test the keyboard shortcut.",
                body: "Press the dictation hotkey. The key on screen should turn orange while you hold it.",
                symbol: "keyboard",
                useAppIcon: false
            )
        }
    }
}
