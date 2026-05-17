import SwiftUI

/// Reusable language picker — used in onboarding and Settings. Lets the user
/// pick zero (auto-detect), one (single-language for lowest latency), or many
/// (multilingual hint set) languages.
struct LanguagePickerView: View {
    @ObservedObject var store: DictationLanguageStore
    /// Optional cap on the visible list; nil shows all entries. Onboarding
    /// uses a smaller cap to keep the screen tidy; Settings shows all.
    let maxVisibleLanguages: Int?

    init(store: DictationLanguageStore, maxVisibleLanguages: Int? = nil) {
        self.store = store
        self.maxVisibleLanguages = maxVisibleLanguages
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
            }
        } label: {
            HStack(spacing: Spacing.md) {
                Image(systemName: store.isAutoDetect ? "checkmark.circle.fill" : "circle")
                    .foregroundStyle(store.isAutoDetect ? Palette.accent : Palette.textTertiary)
                    .font(.system(size: 18))
                VStack(alignment: .leading, spacing: 2) {
                    Text("Auto-detect any language")
                        .font(Typography.body)
                        .foregroundStyle(Palette.textPrimary)
                    Text("Best when you switch languages often. Slightly slower start than picking one.")
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
        } label: {
            HStack(spacing: Spacing.md) {
                Image(systemName: isSelected ? "checkmark.square.fill" : "square")
                    .foregroundStyle(isSelected ? Palette.accent : Palette.textTertiary)
                    .font(.system(size: 16))
                VStack(alignment: .leading, spacing: 1) {
                    Text(entry.englishName)
                        .font(Typography.body)
                        .foregroundStyle(Palette.textPrimary)
                    if entry.nativeName != entry.englishName {
                        Text(entry.nativeName)
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
                Text("Auto-detect mode — the model identifies the language from your audio.")
            } else if count == 1, let only = store.selectedLanguages.first,
                      let entry = DictationLanguageCatalog.entry(for: only) {
                Text("\(entry.englishName) only — fastest, lowest latency.")
            } else {
                let names = store.selectedLanguages
                    .compactMap { DictationLanguageCatalog.entry(for: $0)?.englishName }
                    .sorted()
                    .joined(separator: ", ")
                Text("\(count) languages selected (\(names)). Multilingual auto-detect is used at the model layer.")
            }
        }
        .font(Typography.caption)
        .foregroundStyle(Palette.textSecondary)
        .padding(.top, 4)
        .accessibilityIdentifier("language-picker-summary")
    }
}
