import Foundation
import WaiComputerKit

enum OnboardingPage: Int, CaseIterable, Identifiable {
    case welcome
    case language
    case record
    case transcribe
    case permission
    case voiceSetup

    var id: Int { rawValue }

    struct Content {
        let eyebrow: String
        let title: String
        let body: String
        let symbol: String?
        let useAppIcon: Bool
    }

    /// Short breadcrumb shown in the page indicator, localized to the in-app
    /// language. Mirrors macOS `OnboardingPage.breadcrumbLabel`.
    func breadcrumbLabel(language: LanguageManager.SupportedLanguage) -> String {
        switch self {
        case .welcome:
            return OnboardingL10n.text("Welcome", "Старт", language: language)
        case .language:
            return OnboardingL10n.text("Language", "Язык", language: language)
        case .record:
            return OnboardingL10n.text("Record", "Запись", language: language)
        case .transcribe:
            return OnboardingL10n.text("Understand", "Понимание", language: language)
        case .permission:
            return OnboardingL10n.text("Allow", "Доступ", language: language)
        case .voiceSetup:
            return OnboardingL10n.text("Voice", "Голос", language: language)
        }
    }

    func content(language: LanguageManager.SupportedLanguage) -> Content {
        func t(_ english: String, _ russian: String) -> String {
            OnboardingL10n.text(english, russian, language: language)
        }

        switch self {
        case .welcome:
            return Content(
                eyebrow: "WaiComputer",
                title: t("Your AI second brain for voice.", "Твой ИИ второй мозг для голоса."),
                body: t(
                    "Capture meetings, notes, and reflections — instantly searchable.",
                    "Записывай встречи, заметки и мысли — с мгновенным поиском."
                ),
                symbol: nil,
                useAppIcon: true
            )
        case .language:
            return Content(
                eyebrow: t("Language", "Язык"),
                title: t("Choose your language.", "Выбери язык."),
                body: t(
                    "Pick the language for the app. You can change it anytime in Settings.",
                    "Выбери язык приложения. Его можно изменить в любой момент в настройках."
                ),
                symbol: "globe",
                useAppIcon: false
            )
        case .record:
            return Content(
                eyebrow: t("Record", "Запись"),
                title: t("One tap. Anywhere.", "Одно касание. Где угодно."),
                body: t(
                    "Meetings, voice notes, late-night ideas. WaiComputer keeps recording even when offline.",
                    "Встречи, голосовые заметки, ночные идеи. WaiComputer продолжает запись даже офлайн."
                ),
                symbol: "mic.circle",
                useAppIcon: false
            )
        case .transcribe:
            return Content(
                eyebrow: t("Understand", "Понимание"),
                title: t("Transcripts that think.", "Расшифровки, которые думают."),
                body: t(
                    "Real-time transcription, AI summaries, action items, and key decisions — without the busywork.",
                    "Расшифровка в реальном времени, ИИ-сводки, задачи и ключевые решения — без рутины."
                ),
                symbol: "sparkles",
                useAppIcon: false
            )
        case .permission:
            return Content(
                eyebrow: t("Permission", "Разрешение"),
                title: t("We need your microphone.", "Нам нужен доступ к микрофону."),
                body: t(
                    "WaiComputer only records when you press record. We never listen in the background.",
                    "WaiComputer записывает, только когда ты нажимаешь запись. Мы никогда не слушаем в фоне."
                ),
                symbol: "lock.shield",
                useAppIcon: false
            )
        case .voiceSetup:
            return Content(
                eyebrow: t("Voice", "Голос"),
                title: t("Teach Wai your voice.", "Научи Wai узнавать твой голос."),
                body: t(
                    "Read the prompt for ~20 seconds. Wai will recognise you automatically in future meetings.",
                    "Прочитай текст около 20 секунд. Wai будет узнавать тебя на будущих встречах автоматически."
                ),
                symbol: "waveform.circle",
                useAppIcon: false
            )
        }
    }
}
