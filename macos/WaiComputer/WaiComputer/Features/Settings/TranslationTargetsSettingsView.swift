import SwiftUI
import WaiComputerKit

/// Typeless-style "Translation targets" editor: an ordered list of preset
/// target languages with one active selection. The active target can also be
/// switched from the dictation overlay mid-translation; this view manages the
/// preset list itself (add, remove, reorder).
struct TranslationTargetsSettingsView: View {
    @ObservedObject var store: TranslationLanguageStore
    @ObservedObject private var languageManager = LanguageManager.shared
    let isEnabled: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            HStack {
                Text(t("Translation targets", "Языки перевода"))
                    .font(Typography.body)
                Spacer()
                addLanguageMenu
            }

            ForEach(Array(store.enabledEntries.enumerated()), id: \.element.id) { index, entry in
                targetRow(entry: entry, index: index)
            }
        }
        .disabled(!isEnabled)
        .accessibilityIdentifier("settings-translation-targets-editor")
    }

    private func targetRow(entry: TranslationLanguageCatalog.Entry, index: Int) -> some View {
        HStack(spacing: Spacing.sm) {
            Button {
                store.selectLanguage(entry.code)
            } label: {
                Image(systemName: store.selectedLanguageCode == entry.code
                    ? "largecircle.fill.circle"
                    : "circle")
                    .foregroundStyle(store.selectedLanguageCode == entry.code
                        ? Palette.accent
                        : Palette.textTertiary)
            }
            .buttonStyle(.plain)
            .accessibilityLabel(t("Use \(entry.englishName)", "Использовать \(entry.englishName)"))

            Text(entry.displayName)
                .font(Typography.body)

            Spacer()

            Button {
                store.moveEnabledLanguages(
                    fromOffsets: IndexSet(integer: index),
                    toOffset: max(index - 1, 0)
                )
            } label: {
                Image(systemName: "chevron.up")
            }
            .buttonStyle(.borderless)
            .disabled(index == 0)

            Button {
                store.moveEnabledLanguages(
                    fromOffsets: IndexSet(integer: index),
                    toOffset: min(index + 2, store.enabledLanguageCodes.count)
                )
            } label: {
                Image(systemName: "chevron.down")
            }
            .buttonStyle(.borderless)
            .disabled(index == store.enabledLanguageCodes.count - 1)

            Button {
                store.disableLanguage(entry.code)
            } label: {
                Image(systemName: "minus.circle")
            }
            .buttonStyle(.borderless)
            .disabled(store.enabledLanguageCodes.count <= 1)
            .accessibilityLabel(t("Remove \(entry.englishName)", "Убрать \(entry.englishName)"))
        }
    }

    private var addLanguageMenu: some View {
        Menu {
            ForEach(availableEntries) { entry in
                Button(entry.displayName) {
                    store.enableLanguage(entry.code)
                }
            }
        } label: {
            Label(t("Add language", "Добавить язык"), systemImage: "plus")
                .font(Typography.caption)
        }
        .menuStyle(.borderlessButton)
        .fixedSize()
        .disabled(availableEntries.isEmpty)
        .accessibilityIdentifier("settings-translation-targets-add")
    }

    private var availableEntries: [TranslationLanguageCatalog.Entry] {
        TranslationLanguageCatalog.all.filter { !store.enabledLanguageCodes.contains($0.code) }
    }

    private func t(_ english: String, _ russian: String) -> String {
        languageManager.current == .russian ? russian : english
    }
}
