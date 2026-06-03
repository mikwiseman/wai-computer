import Foundation
import WaiComputerKit

@MainActor
final class TranslationLanguageStore: ObservableObject {
    static let userDefaultsKey = "dictationTranslationTargetLanguage"

    @Published private(set) var selectedLanguageCode: String

    init(defaults: UserDefaults = .standard) {
        let stored = defaults.string(forKey: Self.userDefaultsKey)
        let initial = stored.flatMap { TranslationLanguageCatalog.entry(for: $0)?.code }
            ?? Self.defaultLanguageCode()
        self.selectedLanguageCode = initial
        defaults.set(initial, forKey: Self.userDefaultsKey)
    }

    var selectedEntry: TranslationLanguageCatalog.Entry {
        TranslationLanguageCatalog.entry(for: selectedLanguageCode)
            ?? TranslationLanguageCatalog.entry(for: "en")!
    }

    var targetLanguageCode: String {
        selectedEntry.code
    }

    var targetLanguageName: String {
        selectedEntry.englishName
    }

    func selectLanguage(_ code: String, defaults: UserDefaults = .standard) {
        guard let entry = TranslationLanguageCatalog.entry(for: code) else { return }
        selectedLanguageCode = entry.code
        defaults.set(entry.code, forKey: Self.userDefaultsKey)
    }

    private static func defaultLanguageCode() -> String {
        switch LanguageManager.shared.current {
        case .russian:
            return "ru"
        default:
            return "en"
        }
    }
}

struct TranslationLanguageCatalog {
    struct Entry: Hashable, Identifiable {
        let code: String
        let englishName: String
        let nativeName: String
        var id: String { code }

        var displayName: String {
            englishName == nativeName ? englishName : "\(englishName) (\(nativeName))"
        }
    }

    static let all: [Entry] = [
        .init(code: "en", englishName: "English", nativeName: "English"),
        .init(code: "ru", englishName: "Russian", nativeName: "Русский"),
        .init(code: "sq", englishName: "Albanian", nativeName: "Shqip"),
        .init(code: "es", englishName: "Spanish", nativeName: "Español"),
        .init(code: "de", englishName: "German", nativeName: "Deutsch"),
        .init(code: "fr", englishName: "French", nativeName: "Français"),
        .init(code: "it", englishName: "Italian", nativeName: "Italiano"),
        .init(code: "pt", englishName: "Portuguese", nativeName: "Português"),
        .init(code: "ja", englishName: "Japanese", nativeName: "日本語"),
        .init(code: "ko", englishName: "Korean", nativeName: "한국어"),
        .init(code: "zh", englishName: "Chinese", nativeName: "中文"),
        .init(code: "hi", englishName: "Hindi", nativeName: "हिन्दी"),
        .init(code: "ar", englishName: "Arabic", nativeName: "العربية"),
        .init(code: "uk", englishName: "Ukrainian", nativeName: "Українська"),
        .init(code: "pl", englishName: "Polish", nativeName: "Polski"),
        .init(code: "nl", englishName: "Dutch", nativeName: "Nederlands"),
        .init(code: "tr", englishName: "Turkish", nativeName: "Türkçe"),
    ]

    static func entry(for code: String) -> Entry? {
        let normalized = code.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return all.first { $0.code == normalized }
    }
}
