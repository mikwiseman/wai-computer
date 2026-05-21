import Foundation
import WaiComputerKit

enum DictationSettingsCopy {
    static func hotkeyLabel(rawValue: String, language: LanguageManager.SupportedLanguage) -> String {
        switch rawValue {
        case "right_option":
            return text("Right Option (\u{2325})", "Правый Option (\u{2325})", language: language)
        case "left_option":
            return text("Left Option (\u{2325})", "Левый Option (\u{2325})", language: language)
        case "right_command":
            return text("Right Command (\u{2318})", "Правый Command (\u{2318})", language: language)
        case "fn":
            return text("Fn (Globe)", "Fn (Глобус)", language: language)
        case "control_option":
            return text("Control + Option (\u{2303}\u{2325})", "Control + Option (\u{2303}\u{2325})", language: language)
        default:
            return rawValue
        }
    }

    static func hotkeyShortLabel(rawValue: String, language: LanguageManager.SupportedLanguage) -> String {
        switch rawValue {
        case "right_option":
            return text("\u{2325} (Right)", "\u{2325} справа", language: language)
        case "left_option":
            return text("\u{2325} (Left)", "\u{2325} слева", language: language)
        case "right_command":
            return text("\u{2318} (Right)", "\u{2318} справа", language: language)
        case "fn":
            return "Fn"
        case "control_option":
            return "\u{2303}\u{2325}"
        default:
            return rawValue
        }
    }

    static func stalePermissionHint(language: LanguageManager.SupportedLanguage) -> String {
        "\(permissionRestartHint(language: language)) \(duplicatePermissionHint(language: language))"
    }

    static func permissionRestartHint(language: LanguageManager.SupportedLanguage) -> String {
        text(
            "WaiComputer is enabled in System Settings - restart so macOS applies the permission to this running app.",
            "WaiComputer включен в Системных настройках - перезапусти приложение, чтобы macOS применила разрешение к текущему процессу.",
            language: language
        )
    }

    static func duplicatePermissionHint(language: LanguageManager.SupportedLanguage) -> String {
        text(
            "If WaiComputer appears more than once in the list, keep only the installed copy enabled and remove old rows with the minus button.",
            "Если WaiComputer показан в списке несколько раз, оставь включенной только установленную копию и удали старые строки кнопкой минус.",
            language: language
        )
    }

    private static func text(
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
}
