import Foundation

enum OnboardingPage: Int, CaseIterable, Identifiable {
    case welcome
    case record
    case transcribe
    case dictate
    case permission

    var id: Int { rawValue }

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
        case .permission:
            return Content(
                eyebrow: "Setup",
                title: "Set up voice access.",
                body: "Grant Microphone for recording, Input Monitoring for the global hotkey, and Automatic Paste for text insertion.",
                symbol: "lock.shield",
                useAppIcon: false
            )
        }
    }
}
