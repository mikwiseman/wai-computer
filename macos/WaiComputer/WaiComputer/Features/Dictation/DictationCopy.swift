import Foundation
import WaiComputerKit

enum DictationCopy {
    enum OverlayStatus {
        case idle
        case connecting
        case listening
        case processing
        case inserting
    }

    static func text(
        _ english: String,
        _ russian: String,
        language: LanguageManager.SupportedLanguage
    ) -> String {
        switch language {
        case .russian:
            return russian
        case .english:
            return english
        case .followSystem:
            let preferred = Locale.preferredLanguages.first?.lowercased() ?? ""
            return preferred.hasPrefix("ru") ? russian : english
        }
    }

    static func overlayStatus(
        _ status: OverlayStatus,
        language: LanguageManager.SupportedLanguage
    ) -> String {
        switch status {
        case .idle:
            return text("Ready", "Готово", language: language)
        case .connecting:
            return text("Connecting…", "Подключаемся…", language: language)
        case .listening:
            return text("Listening…", "Слушаем…", language: language)
        case .processing:
            return text("Processing…", "Обрабатываем…", language: language)
        case .inserting:
            return text("Inserting…", "Вставляем…", language: language)
        }
    }

    static func microphonePermissionDenied(language: LanguageManager.SupportedLanguage) -> String {
        text(
            "Microphone permission denied. Open System Settings -> Privacy & Security -> Microphone and enable WaiComputer.",
            "Нет доступа к микрофону. Открой Системные настройки -> Конфиденциальность и безопасность -> Микрофон и включи WaiComputer.",
            language: language
        )
    }

    static func recoveryCopyKept(
        insertionError: String,
        language: LanguageManager.SupportedLanguage
    ) -> String {
        let suffix = text(
            "A recovery copy was kept on this Mac.",
            "Резервная копия сохранена на этом Mac.",
            language: language
        )
        return "\(insertionError) \(suffix)"
    }

    static func genericInsertionRecovery(language: LanguageManager.SupportedLanguage) -> String {
        text(
            "We couldn't insert the dictated text into the current app. A recovery copy was kept on this Mac.",
            "Не удалось вставить продиктованный текст в текущее приложение. Резервная копия сохранена на этом Mac.",
            language: language
        )
    }

    static func providerError(
        _ error: ProviderError,
        language: LanguageManager.SupportedLanguage
    ) -> String {
        switch error {
        case .authError:
            return text(
                "Authentication with the transcription service failed. Please try again.",
                "Не удалось авторизоваться в сервисе распознавания речи. Попробуй ещё раз.",
                language: language
            )
        case .quotaExceeded:
            return text(
                "Dictation quota exceeded. Please try again later.",
                "Лимит диктовки исчерпан. Попробуй позже.",
                language: language
            )
        case .rateLimited:
            return text(
                "Dictation service is busy. Please wait a moment and try again.",
                "Сервис диктовки перегружен. Подожди немного и попробуй ещё раз.",
                language: language
            )
        case .insufficientAudioActivity:
            return text(
                "Hold the hotkey and speak clearly to dictate.",
                "Удерживай клавишу диктовки и говори чётко.",
                language: language
            )
        case .sessionTimeLimitExceeded:
            return text(
                "Dictation session time limit reached. Please start a new session.",
                "Время сессии диктовки закончилось. Начни новую сессию.",
                language: language
            )
        case .chunkSizeExceeded, .commitThrottled, .malformedFrame:
            return text(
                "Live transcription was interrupted. Try again.",
                "Потоковое распознавание прервалось. Попробуй ещё раз.",
                language: language
            )
        case .unsupportedModel(let model):
            return text(
                "Dictation model \(model) is not supported.",
                "Модель диктовки \(model) не поддерживается.",
                language: language
            )
        case .transcriberInternal(let message):
            if message.isEmpty {
                return text(
                    "The transcription service returned an error. Please try again.",
                    "Сервис распознавания речи вернул ошибку. Попробуй ещё раз.",
                    language: language
                )
            }
            return text(
                "Transcription error: \(message)",
                "Ошибка распознавания речи: \(message)",
                language: language
            )
        }
    }
}
