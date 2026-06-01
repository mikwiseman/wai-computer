import SwiftUI
import WaiComputerKit

/// Reusable transcription-language picker — auto-detect or one explicit
/// language hint for lowest latency. Ported from macOS (pure SwiftUI + shared
/// LanguageManager + iOS DesignSystem tokens).
struct LanguagePickerView: View {
    @EnvironmentObject private var languageManager: LanguageManager

    @ObservedObject var store: DictationLanguageStore
    /// Optional cap on the visible list; nil shows all entries.
    let maxVisibleLanguages: Int?
    let onSelectionChanged: (() -> Void)?

    init(
        store: DictationLanguageStore,
        maxVisibleLanguages: Int? = nil,
        onSelectionChanged: (() -> Void)? = nil
    ) {
        self.store = store
        self.maxVisibleLanguages = maxVisibleLanguages
        self.onSelectionChanged = onSelectionChanged
    }

    private var entries: [DictationLanguageCatalog.Entry] {
        if let cap = maxVisibleLanguages {
            return Array(DictationLanguageCatalog.all.prefix(cap))
        }
        return DictationLanguageCatalog.all
    }

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            autoDetectRow
            Divider()
                .padding(.vertical, 4)
            languageList
            footerHint
        }
    }

    // MARK: - Subviews

    private var autoDetectRow: some View {
        Button {
            if !store.isAutoDetect {
                store.setAutoDetect()
                onSelectionChanged?()
            }
        } label: {
            HStack(spacing: Spacing.md) {
                Image(systemName: store.isAutoDetect ? "checkmark.circle.fill" : "circle")
                    .foregroundStyle(store.isAutoDetect ? Palette.accent : Palette.textTertiary)
                    .font(.system(size: 18))
                VStack(alignment: .leading, spacing: 2) {
                    Text(t("Auto-detect any language", "Автоопределение языка"))
                        .font(Typography.body)
                        .foregroundStyle(Palette.textPrimary)
                    Text(t(
                        "Best when you switch languages often. Slightly slower start than picking one.",
                        "Лучше, если ты часто переключаешься между языками. Запуск чуть медленнее, чем с одним языком."
                    ))
                        .font(Typography.caption)
                        .foregroundStyle(Palette.textTertiary)
                }
                Spacer()
            }
            .padding(.vertical, 4)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("language-picker-auto")
    }

    private var languageList: some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(entries) { entry in
                row(for: entry)
            }
        }
    }

    private func row(for entry: DictationLanguageCatalog.Entry) -> some View {
        let isSelected = store.selectedLanguages.contains(entry.code)
        return Button {
            store.toggle(entry.code)
            onSelectionChanged?()
        } label: {
            HStack(spacing: Spacing.md) {
                Image(systemName: isSelected ? "checkmark.circle.fill" : "circle")
                    .foregroundStyle(isSelected ? Palette.accent : Palette.textTertiary)
                    .font(.system(size: 16))
                VStack(alignment: .leading, spacing: 1) {
                    Text(primaryName(for: entry))
                        .font(Typography.body)
                        .foregroundStyle(Palette.textPrimary)
                    let secondary = secondaryName(for: entry)
                    if !secondary.isEmpty {
                        Text(secondary)
                            .font(Typography.caption)
                            .foregroundStyle(Palette.textTertiary)
                    }
                }
                Spacer()
                Text(entry.code)
                    .font(Typography.mono)
                    .foregroundStyle(Palette.textTertiary)
            }
            .padding(.vertical, 6)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("language-picker-row-\(entry.code)")
    }

    @ViewBuilder
    private var footerHint: some View {
        let count = store.selectedLanguages.count
        Group {
            if count == 0 {
                Text(t(
                    "Auto-detect mode — the model identifies the language from your audio.",
                    "Автоопределение — модель сама распознает язык по аудио."
                ))
            } else if let only = store.selectedLanguages.first,
                      let entry = DictationLanguageCatalog.entry(for: only) {
                Text(t(
                    "\(entry.englishName) only — fastest, lowest latency.",
                    "Только \(entry.nativeName) — самый быстрый режим с минимальной задержкой."
                ))
            } else {
                Text(t(
                    "Auto-detect mode — the model identifies the language from your audio.",
                    "Автоопределение — модель сама распознает язык по аудио."
                ))
            }
        }
        .font(Typography.caption)
        .foregroundStyle(Palette.textSecondary)
        .padding(.top, 4)
        .accessibilityIdentifier("language-picker-summary")
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }

    private func primaryName(for entry: DictationLanguageCatalog.Entry) -> String {
        guard languageManager.current == .russian else { return entry.englishName }
        switch entry.code {
        case "en": return "Английский"
        case "ru": return "Русский"
        case "es": return "Испанский"
        case "de": return "Немецкий"
        case "fr": return "Французский"
        case "it": return "Итальянский"
        case "pt": return "Португальский"
        case "ja": return "Японский"
        case "ko": return "Корейский"
        case "hi": return "Хинди"
        case "ar": return "Арабский"
        case "uk": return "Украинский"
        case "pl": return "Польский"
        case "nl": return "Нидерландский"
        case "tr": return "Турецкий"
        default: return entry.nativeName
        }
    }

    private func secondaryName(for entry: DictationLanguageCatalog.Entry) -> String {
        if languageManager.current == .russian {
            return entry.nativeName == primaryName(for: entry) ? "" : entry.nativeName
        }
        return entry.nativeName == entry.englishName ? "" : entry.nativeName
    }
}
