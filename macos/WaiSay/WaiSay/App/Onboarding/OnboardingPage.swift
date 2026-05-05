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
        let useTriangleIcon: Bool
    }

    var content: Content {
        switch self {
        case .welcome:
            return Content(
                eyebrow: "WaiSay",
                title: "Your AI second brain for voice.",
                body: "Capture meetings, notes, and reflections — instantly searchable.",
                symbol: nil,
                useTriangleIcon: true
            )
        case .record:
            return Content(
                eyebrow: "Record",
                title: "One tap. Anywhere.",
                body: "Meetings, voice notes, late-night ideas. WaiSay keeps recording even when offline.",
                symbol: "mic.circle",
                useTriangleIcon: false
            )
        case .transcribe:
            return Content(
                eyebrow: "Understand",
                title: "Transcripts that think.",
                body: "Real-time transcription, AI summaries, action items, and key decisions — without the busywork.",
                symbol: "sparkles",
                useTriangleIcon: false
            )
        case .dictate:
            return Content(
                eyebrow: "Dictate",
                title: "Speak into anything.",
                body: "A global hotkey turns your voice into text in any app. We'll set up the hotkey in Settings.",
                symbol: "keyboard.badge.eye",
                useTriangleIcon: false
            )
        case .permission:
            return Content(
                eyebrow: "Permission",
                title: "We need your microphone.",
                body: "WaiSay only records when you press record. We never listen in the background.",
                symbol: "lock.shield",
                useTriangleIcon: false
            )
        }
    }
}
