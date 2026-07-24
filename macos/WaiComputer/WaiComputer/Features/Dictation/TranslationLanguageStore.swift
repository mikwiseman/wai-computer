import Foundation
import WaiComputerKit

/// Target languages for Translation mode. The user pre-sets an ordered list of
/// targets (Typeless-style "Translation targets") and switches the active one
/// from Settings, the dictation overlay, or by cycling mid-dictation.
@MainActor
final class TranslationLanguageStore: ObservableObject {
    static let userDefaultsKey = "dictationTranslationTargetLanguage"
    static let enabledTargetsKey = "dictationTranslationTargetLanguages"

    @Published private(set) var selectedLanguageCode: String
    /// Ordered preset targets. Never empty; always contains the selection.
    @Published private(set) var enabledLanguageCodes: [String]

    init(defaults: UserDefaults = .standard) {
        let storedSelection = defaults.string(forKey: Self.userDefaultsKey)
        let selection = storedSelection.flatMap { TranslationLanguageCatalog.entry(for: $0)?.code }
            ?? Self.defaultLanguageCode()

        var enabled = (defaults.stringArray(forKey: Self.enabledTargetsKey) ?? [])
            .compactMap { TranslationLanguageCatalog.entry(for: $0)?.code }
        enabled = enabled.reduce(into: []) { unique, code in
            if !unique.contains(code) { unique.append(code) }
        }
        // Legacy single-target installs (or a wiped list) fold into the
        // enabled list so nothing the user picked before is lost.
        if enabled.isEmpty {
            enabled = [selection]
        } else if !enabled.contains(selection) {
            enabled.append(selection)
        }

        self.selectedLanguageCode = selection
        self.enabledLanguageCodes = enabled
        defaults.set(selection, forKey: Self.userDefaultsKey)
        defaults.set(enabled, forKey: Self.enabledTargetsKey)
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

    var enabledEntries: [TranslationLanguageCatalog.Entry] {
        enabledLanguageCodes.compactMap { TranslationLanguageCatalog.entry(for: $0) }
    }

    func selectLanguage(_ code: String, defaults: UserDefaults = .standard) {
        guard let entry = TranslationLanguageCatalog.entry(for: code) else { return }
        if !enabledLanguageCodes.contains(entry.code) {
            enabledLanguageCodes.append(entry.code)
            defaults.set(enabledLanguageCodes, forKey: Self.enabledTargetsKey)
        }
        selectedLanguageCode = entry.code
        defaults.set(entry.code, forKey: Self.userDefaultsKey)
    }

    func enableLanguage(_ code: String, defaults: UserDefaults = .standard) {
        guard let entry = TranslationLanguageCatalog.entry(for: code),
              !enabledLanguageCodes.contains(entry.code)
        else { return }
        enabledLanguageCodes.append(entry.code)
        defaults.set(enabledLanguageCodes, forKey: Self.enabledTargetsKey)
    }

    func disableLanguage(_ code: String, defaults: UserDefaults = .standard) {
        guard enabledLanguageCodes.count > 1,
              let index = enabledLanguageCodes.firstIndex(of: code)
        else { return }
        enabledLanguageCodes.remove(at: index)
        defaults.set(enabledLanguageCodes, forKey: Self.enabledTargetsKey)
        if selectedLanguageCode == code, let fallback = enabledLanguageCodes.first {
            selectedLanguageCode = fallback
            defaults.set(fallback, forKey: Self.userDefaultsKey)
        }
    }

    func moveEnabledLanguages(
        fromOffsets source: IndexSet,
        toOffset destination: Int,
        defaults: UserDefaults = .standard
    ) {
        enabledLanguageCodes.move(fromOffsets: source, toOffset: destination)
        defaults.set(enabledLanguageCodes, forKey: Self.enabledTargetsKey)
    }

    /// Cycle to the next preset target, wrapping in list order.
    func selectNextTarget(defaults: UserDefaults = .standard) {
        guard enabledLanguageCodes.count > 1,
              let index = enabledLanguageCodes.firstIndex(of: selectedLanguageCode)
        else { return }
        let next = enabledLanguageCodes[(index + 1) % enabledLanguageCodes.count]
        selectedLanguageCode = next
        defaults.set(next, forKey: Self.userDefaultsKey)
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
