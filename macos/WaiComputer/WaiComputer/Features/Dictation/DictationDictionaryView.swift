import SwiftUI
import WaiComputerKit

struct DictationDictionaryView: View {
    @EnvironmentObject private var dictionaryStore: DictationDictionaryStore
    @EnvironmentObject private var languageManager: LanguageManager
    @EnvironmentObject private var learningEngine: DictionaryLearningEngine
    @State private var newWord = ""
    @State private var newReplacement = ""
    @State private var searchText = ""
    @State private var editingWord: DictionaryWord?

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

            // Suggestions learned from the user's edits (one-tap accept).
            if !learningEngine.suggestions.isEmpty {
                suggestionsSection
                Divider()
            }

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
    private var suggestionsSection: some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            HStack(spacing: 6) {
                Image(systemName: "sparkles")
                    .font(.caption)
                    .foregroundStyle(Palette.accent)
                Text(t("Suggested from your edits", "Подсказки из твоих правок"))
                    .font(Typography.label)
                    .foregroundStyle(Palette.textSecondary)
            }
            ForEach(learningEngine.suggestions) { suggestion in
                suggestionRow(suggestion)
            }
        }
        .padding(.horizontal, Spacing.xl)
        .padding(.vertical, Spacing.md)
    }

    @ViewBuilder
    private func suggestionRow(_ suggestion: DictionarySuggestion) -> some View {
        HStack(spacing: Spacing.sm) {
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Text(suggestion.corrected)
                        .font(Typography.body.weight(.semibold))
                        .foregroundStyle(Palette.textPrimary)
                    Text(verbatim: "·")
                        .foregroundStyle(Palette.textTertiary)
                    Text(correctedCountText(suggestion.hitCount))
                        .font(Typography.caption)
                        .foregroundStyle(Palette.textTertiary)
                }
                Text(t("Heard “\(suggestion.original)”", "Распознано «\(suggestion.original)»"))
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textTertiary)
            }

            Spacer()

            Button(t("Add", "Добавить")) {
                dictionaryStore.add(word: suggestion.corrected, origin: "learned")
                learningEngine.accept(suggestion)
            }
            .help(t("Add as a recognition hint", "Добавить как подсказку распознавания"))

            Button(t("Replace", "Замена")) {
                dictionaryStore.add(word: suggestion.original, replacement: suggestion.corrected, origin: "learned")
                learningEngine.accept(suggestion)
            }
            .buttonStyle(.plain)
            .foregroundStyle(Palette.accent)
            .help(t(
                "Always replace “\(suggestion.original)” with “\(suggestion.corrected)”",
                "Всегда заменять «\(suggestion.original)» на «\(suggestion.corrected)»"
            ))

            Button {
                learningEngine.dismiss(suggestion)
            } label: {
                Image(systemName: "xmark")
                    .font(.caption)
                    .foregroundStyle(Palette.textTertiary)
            }
            .buttonStyle(.plain)
            .help(t("Dismiss", "Скрыть"))
        }
        .padding(Spacing.sm)
        .background(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .fill(Palette.accent.opacity(0.08))
        )
    }

    private func correctedCountText(_ count: Int) -> String {
        if OnboardingL10n.language(for: languageManager.current) == .russian {
            return "исправлено \(count)×"
        }
        return "corrected \(count)×"
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
                    .onSubmit { commitWord() }

                Image(systemName: "arrow.right")
                    .font(.caption)
                    .foregroundStyle(Palette.textTertiary)

                TextField(t("Replace with... (optional)", "Заменять на... (необязательно)"), text: $newReplacement)
                    .textFieldStyle(.roundedBorder)
                    .font(Typography.body)
                    .onSubmit { commitWord() }

                if editingWord != nil {
                    Button(t("Cancel", "Отмена")) { cancelEdit() }
                        .buttonStyle(.plain)
                        .foregroundStyle(Palette.textSecondary)
                }
                Button(editingWord == nil ? t("Add", "Добавить") : t("Save", "Сохранить")) { commitWord() }
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

            if word.isLearned {
                Image(systemName: "sparkles")
                    .font(.caption2)
                    .foregroundStyle(Palette.accent)
                    .help(t("Learned from your edits", "Выучено из твоих правок"))
            }

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
        .contentShape(Rectangle())
        .contextMenu {
            Button(t("Edit…", "Изменить…")) { beginEdit(word) }
            Button(t("Remove word", "Удалить слово"), role: .destructive) {
                dictionaryStore.delete(word)
            }
        }
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

    private func commitWord() {
        if let editing = editingWord {
            let replacementTrimmed = newReplacement.trimmingCharacters(in: .whitespacesAndNewlines)
            let ok = dictionaryStore.update(
                editing,
                newWord: newWord,
                newReplacement: replacementTrimmed.isEmpty ? nil : replacementTrimmed
            )
            if ok { cancelEdit() }
        } else {
            addWord()
        }
    }

    private func beginEdit(_ word: DictionaryWord) {
        editingWord = word
        newWord = word.word
        newReplacement = word.replacement ?? ""
    }

    private func cancelEdit() {
        editingWord = nil
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
