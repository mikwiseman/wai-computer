import SwiftUI
import WaiComputerKit

/// Settings row that lets the user switch the UI language at runtime.
///
/// Backed by ``LanguageManager.shared`` in ``WaiComputerKit``. Selecting a
/// language updates ``\.environment(\.locale)`` on the root view so every
/// SwiftUI ``Text("key")`` re-resolves instantly — no relaunch required.
/// The choice persists in ``UserDefaults`` under ``waiUserLanguage``.
struct AppLanguagePicker: View {
    @EnvironmentObject var languageManager: LanguageManager

    var body: some View {
        Picker(selection: Binding(
            get: { languageManager.current },
            set: { languageManager.setLanguage($0) }
        )) {
            ForEach(LanguageManager.SupportedLanguage.allCases) { language in
                Text(language.nativeDisplayName).tag(language)
            }
        } label: {
            Text("settings.language.title", bundle: .main)
        }
        .pickerStyle(.menu)
        .accessibilityIdentifier("settings-app-language-picker")
    }
}
