import Foundation

/// Localized, human-readable labels for item/material `kind` values.
/// The API stores free strings ("article", "mcp_resource", …) — never show
/// them raw: "MCP_RESOURCE" in a badge reads as a bug.
public enum ItemKindLabel {
    public static func text(
        _ kind: String?,
        language: LanguageManager.SupportedLanguage
    ) -> String? {
        guard let raw = kind?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased(),
              !raw.isEmpty else { return nil }
        switch raw {
        case "article": return OnboardingL10n.text("Article", "Статья", language: language)
        case "video": return OnboardingL10n.text("Video", "Видео", language: language)
        case "post": return OnboardingL10n.text("Post", "Пост", language: language)
        case "pdf": return "PDF"
        case "email": return OnboardingL10n.text("Email", "Письмо", language: language)
        case "note": return OnboardingL10n.text("Note", "Заметка", language: language)
        case "event": return OnboardingL10n.text("Event", "Событие", language: language)
        case "message": return OnboardingL10n.text("Message", "Сообщение", language: language)
        case "transaction": return OnboardingL10n.text("Transaction", "Транзакция", language: language)
        case "chat": return OnboardingL10n.text("Chat", "Чат", language: language)
        case "file": return OnboardingL10n.text("File", "Файл", language: language)
        case "mcp_resource": return OnboardingL10n.text("Connected", "Подключение", language: language)
        default:
            let spaced = raw.replacingOccurrences(of: "_", with: " ")
            return spaced.prefix(1).uppercased() + spaced.dropFirst()
        }
    }
}
