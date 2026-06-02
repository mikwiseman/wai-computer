import SwiftUI
import WaiComputerKit

/// Settings row that switches the UI language at runtime.
///
/// Backed by `LanguageManager.shared` in `WaiComputerKit`. Selecting a language
/// updates `\.environment(\.locale)` on the root view so every bilingual `t()`
/// string re-resolves instantly — no relaunch required. The choice persists in
/// `UserDefaults` under `waiUserLanguage`. Mirrors macOS `AppLanguagePicker`.
struct AppLanguagePicker: View {
    @EnvironmentObject var languageManager: LanguageManager

    private let selectableLanguages: [LanguageManager.SupportedLanguage] = [.english, .russian]

    private var selectedLanguage: LanguageManager.SupportedLanguage {
        switch languageManager.current {
        case .russian:
            return .russian
        case .followSystem:
            return Locale.current.language.languageCode?.identifier == "ru" ? .russian : .english
        case .english:
            return .english
        }
    }

    var body: some View {
        Picker(selection: Binding(
            get: { selectedLanguage },
            set: { languageManager.setLanguage($0) }
        )) {
            ForEach(selectableLanguages) { language in
                Text(language.nativeDisplayName).tag(language)
            }
        } label: {
            Text(t("Language", "Язык"))
        }
        .pickerStyle(.menu)
        .accessibilityIdentifier("settings-app-language-picker")
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}
