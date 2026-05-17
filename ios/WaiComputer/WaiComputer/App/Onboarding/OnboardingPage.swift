import Foundation

enum OnboardingPage: Int, CaseIterable, Identifiable {
    case welcome
    case record
    case transcribe
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
                eyebrow: "WaiComputer",
                title: "Your AI second brain for voice.",
                body: "Capture meetings, notes, and reflections — instantly searchable.",
                symbol: nil,
                useAppIcon: true
            )
        case .record:
            return Content(
                eyebrow: "Record",
                title: "One tap. Anywhere.",
                body: "Meetings, voice notes, late-night ideas. WaiComputer keeps recording even when offline.",
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
        case .permission:
            return Content(
                eyebrow: "Permission",
                title: "We need your microphone.",
                body: "WaiComputer only records when you press record. We never listen in the background.",
                symbol: "lock.shield",
                useAppIcon: false
            )
        }
    }
}
