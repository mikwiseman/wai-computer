import SwiftUI
import WaiComputerKit

struct DictationDictionaryView: View {
    @EnvironmentObject private var dictionaryStore: DictationDictionaryStore
    @EnvironmentObject private var languageManager: LanguageManager
    @State private var newWord = ""
    @State private var newReplacement = ""
    @State private var searchText = ""

    /// SuperWhisper warns that very long vocabulary lists confuse the model
    /// and degrade language detection. ~50 entries on the wire is the
    /// soft-cap; we surface a hint earlier so users course-correct before
    /// recognition quality drops.
    private let warnAboveCount = 30

    private var filteredWords: [DictionaryWord] {
        if searchText.isEmpty { return dictionaryStore.words }
        return dictionaryStore.words.filter {
            $0.word.localizedCaseInsensitiveContains(searchText)
                || ($0.replacement?.localizedCaseInsensitiveContains(searchText) ?? false)
        }
    }

    var body: some View {
        VStack(spacing: 0) {
            // Header
            VStack(alignment: .leading, spacing: Spacing.md) {
                Text(t("Dictionary", "Словарь"))
                    .font(Typography.displaySmall)

                explainerCopy

                if dictionaryStore.words.count >= warnAboveCount {
                    overuseWarning
                }

                addRow
            }
            .padding(Spacing.xl)

            Divider()

            // Search
            if !dictionaryStore.words.isEmpty {
                HStack {
                    Image(systemName: "magnifyingglass")
                        .foregroundStyle(Palette.textTertiary)
                    TextField(t("Search dictionary...", "Искать в словаре..."), text: $searchText)
                        .textFieldStyle(.plain)
                        .font(Typography.body)
                }
                .padding(.horizontal, Spacing.xl)
                .padding(.vertical, Spacing.md)

                Divider()
            }

            // Word list
            if dictionaryStore.words.isEmpty {
                Spacer()
                ContentUnavailableViewCompat(
                    t("No Words Yet", "Пока нет слов"),
                    systemImage: "book",
                    description: Text(t(
                        "Add words dictation often misspells — names, acronyms, technical terms.",
                        "Добавь слова, которые диктовка часто путает: имена, аббревиатуры, термины."
                    ))
                )
                Spacer()
            } else if filteredWords.isEmpty {
                Spacer()
                ContentUnavailableViewCompat(
                    t("No Results", "Ничего не найдено"),
                    systemImage: "magnifyingglass",
                    description: Text(t("No words match your search.", "По этому запросу слов нет."))
                )
                Spacer()
            } else {
                List {
                    ForEach(filteredWords) { word in
                        wordRow(word)
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    @ViewBuilder
    private var explainerCopy: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(t(
                "Each entry biases the recognizer toward your spelling. Add an optional replacement to also auto-correct a known misspelling after transcription.",
                "Каждая запись подсказывает распознавателю нужное написание. Добавь замену, чтобы автоматически исправлять известную ошибку после распознавания."
            ))
                .font(Typography.bodySmall)
                .foregroundStyle(Palette.textSecondary)
            HStack(spacing: 12) {
                badgeLegend(label: biasBadgeLabel, color: Palette.accent, hint: t("Word boosts recognition", "Помогает распознаванию"))
                badgeLegend(label: replaceBadgeLabel, color: .orange, hint: t("Auto-corrects to replacement", "Автоматически заменяет"))
            }
        }
    }

    @ViewBuilder
    private var overuseWarning: some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.caption)
                .foregroundStyle(.orange)
            Text(t(
                "\(dictionaryStore.words.count) entries — long vocabulary lists can confuse the recognizer and slow language detection. Keep entries focused on words that genuinely get misheard.",
                "\(dictionaryStore.words.count) записей — длинные словари могут путать распознаватель и замедлять определение языка. Оставляй только слова, которые действительно часто слышатся неверно."
            ))
                .font(Typography.caption)
                .foregroundStyle(Palette.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(10)
        .background(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .fill(Color.orange.opacity(0.10))
        )
    }

    @ViewBuilder
    private var addRow: some View {
        VStack(spacing: Spacing.xs) {
            HStack(spacing: Spacing.sm) {
                TextField(t("Word or phrase...", "Слово или фраза..."), text: $newWord)
                    .textFieldStyle(.roundedBorder)
                    .font(Typography.body)
                    .onSubmit { addWord() }

                Image(systemName: "arrow.right")
                    .font(.caption)
                    .foregroundStyle(Palette.textTertiary)

                TextField(t("Replace with... (optional)", "Заменять на... (необязательно)"), text: $newReplacement)
                    .textFieldStyle(.roundedBorder)
                    .font(Typography.body)
                    .onSubmit { addWord() }

                Button(t("Add", "Добавить")) { addWord() }
                    .disabled(newWord.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
            HStack(spacing: 6) {
                Text(t(
                    "Leave the right field empty to add a vocabulary booster only.",
                    "Оставь правое поле пустым, если нужна только подсказка для распознавания."
                ))
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textTertiary)
                Spacer()
            }
        }
    }

    @ViewBuilder
    private func wordRow(_ word: DictionaryWord) -> some View {
        HStack(spacing: 8) {
            Text(word.word)
                .font(Typography.body)
                .foregroundStyle(Palette.textPrimary)

            if let replacement = word.replacement, replacement != word.word {
                Image(systemName: "arrow.right")
                    .font(.caption)
                    .foregroundStyle(Palette.textTertiary)
                Text(replacement)
                    .font(Typography.body)
                    .foregroundStyle(Palette.textSecondary)
                badge(label: replaceBadgeLabel, color: .orange)
            } else {
                badge(label: biasBadgeLabel, color: Palette.accent)
            }

            Spacer()

            Button {
                dictionaryStore.delete(word)
            } label: {
                Image(systemName: "xmark")
                    .font(.caption)
                    .foregroundStyle(Palette.textTertiary)
            }
            .buttonStyle(.plain)
            .help(t("Remove word", "Удалить слово"))
        }
        .padding(.vertical, Spacing.xs)
    }

    @ViewBuilder
    private func badge(label: String, color: Color) -> some View {
        Text(label)
            .font(.system(size: 9, weight: .semibold, design: .monospaced))
            .tracking(0.6)
            .foregroundStyle(color)
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(
                RoundedRectangle(cornerRadius: 4, style: .continuous)
                    .fill(color.opacity(0.12))
            )
    }

    @ViewBuilder
    private func badgeLegend(label: String, color: Color, hint: String) -> some View {
        HStack(spacing: 4) {
            badge(label: label, color: color)
            Text(hint)
                .font(Typography.caption)
                .foregroundStyle(Palette.textTertiary)
        }
    }

    private func addWord() {
        let trimmed = newWord.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        let replacementTrimmed = newReplacement.trimmingCharacters(in: .whitespacesAndNewlines)
        let replacement = replacementTrimmed.isEmpty ? nil : replacementTrimmed
        dictionaryStore.add(word: trimmed, replacement: replacement)
        newWord = ""
        newReplacement = ""
    }

    private var biasBadgeLabel: String {
        t("BIAS", "СЛОВО")
    }

    private var replaceBadgeLabel: String {
        t("REPLACE", "ЗАМЕНА")
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}
