import SwiftUI
import WaiComputerKit

/// Custom dictation dictionary — bias words + auto-corrections, server-synced.
/// iOS-idiomatic port of the macOS `DictationDictionaryView`: explainer + add
/// row in a header section, `.searchable` filter, overuse warning, and a `List`
/// of word rows with bias/replace badges and swipe-to-delete.
struct DictationDictionaryView: View {
    @EnvironmentObject private var dictionaryStore: DictationDictionaryStore
    @EnvironmentObject private var languageManager: LanguageManager
    @EnvironmentObject private var learningEngine: DictionaryLearningEngine
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass
    @State private var newWord = ""
    @State private var newReplacement = ""
    @State private var searchText = ""
    @State private var editingWord: DictionaryWord?
    @State private var displayCache = DictationDictionaryDisplayCache()
    @State private var duplicateWord: String?

    /// Long vocabulary lists confuse the model and degrade language detection.
    /// Surface a hint before recognition quality drops.
    private let warnAboveCount = 30

    var body: some View {
        let visibleWords = displayCache.words(
            for: dictionaryStore.words,
            revision: dictionaryStore.wordsRevision,
            searchText: searchText
        )

        Group {
            if isRegularWidth {
                regularDictionaryLayout(visibleWords)
            } else {
                compactDictionaryList(visibleWords)
            }
        }
        .navigationTitle(t("Dictionary", "Словарь"))
        .navigationBarTitleDisplayMode(isRegularWidth ? .inline : .large)
    }

    private var isRegularWidth: Bool {
        horizontalSizeClass == .regular
    }

    private func regularDictionaryLayout(_ visibleWords: [DictionaryWord]) -> some View {
        VStack(spacing: 0) {
            regularHeader
            Divider()

            if !learningEngine.suggestions.isEmpty {
                suggestionsSection
                    .padding(.horizontal, Spacing.xl)
                    .padding(.vertical, Spacing.md)
                Divider()
            }

            if !dictionaryStore.words.isEmpty {
                regularSearchField
                Divider()
            }

            regularDictionaryResults(visibleWords: visibleWords)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color(uiColor: .systemGroupedBackground))
        .accessibilityIdentifier("ios-dictation-dictionary-regular-layout")
    }

    private func compactDictionaryList(_ visibleWords: [DictionaryWord]) -> some View {
        List {
            Section {
                explainerCopy
                addRow
                if dictionaryStore.words.count >= warnAboveCount {
                    overuseWarning
                }
            }

            if !learningEngine.suggestions.isEmpty {
                Section {
                    suggestionsSection
                }
            }

            if dictionaryStore.words.isEmpty {
                Section {
                    ContentUnavailableViewCompat(
                        t("No Words Yet", "Пока нет слов"),
                        systemImage: "book",
                        description: Text(t(
                            "Add words dictation often misspells — names, acronyms, technical terms.",
                            "Добавь слова, которые диктовка часто путает: имена, аббревиатуры, термины."
                        ))
                    )
                }
            } else if visibleWords.isEmpty {
                Section {
                    ContentUnavailableViewCompat(
                        t("No Results", "Ничего не найдено"),
                        systemImage: "magnifyingglass",
                        description: Text(t("No words match your search.", "По этому запросу слов нет."))
                    )
                }
            } else {
                Section(t("Words", "Слова")) {
                    ForEach(visibleWords) { word in
                        wordRow(word)
                            .swipeActions(edge: .trailing) {
                                Button(role: .destructive) {
                                    dictionaryStore.delete(word)
                                } label: {
                                    Label(t("Remove", "Удалить"), systemImage: "trash")
                                }
                            }
                    }
                }
            }
        }
        .searchable(text: $searchText, prompt: t("Search dictionary", "Искать в словаре"))
        .accessibilityIdentifier("ios-dictation-dictionary-compact-list")
    }

    private var regularHeader: some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            HStack(alignment: .firstTextBaseline) {
                Text(t("Dictionary", "Словарь"))
                    .font(Typography.displaySmall)
                    .foregroundStyle(Palette.textPrimary)
                Spacer()
                Text(dictionaryCountText(dictionaryStore.words.count))
                    .font(Typography.bodySmall)
                    .foregroundStyle(Palette.textSecondary)
            }

            explainerCopy

            if dictionaryStore.words.count >= warnAboveCount {
                overuseWarning
            }

            addRow
        }
        .padding(Spacing.xl)
        .background(Palette.surfaceSubtle)
        .accessibilityIdentifier("ios-dictation-dictionary-regular-header")
    }

    private var regularSearchField: some View {
        HStack(spacing: Spacing.sm) {
            Image(systemName: "magnifyingglass")
                .foregroundStyle(Palette.textTertiary)
            TextField(t("Search dictionary...", "Искать в словаре..."), text: $searchText)
                .textFieldStyle(.plain)
                .font(Typography.body)
                .accessibilityIdentifier("ios-dictation-dictionary-search-field")
        }
        .padding(.horizontal, Spacing.xl)
        .padding(.vertical, Spacing.md)
        .background(Palette.surfaceSubtle)
    }

    @ViewBuilder
    private func regularDictionaryResults(visibleWords: [DictionaryWord]) -> some View {
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
        } else if visibleWords.isEmpty {
            Spacer()
            ContentUnavailableViewCompat(
                t("No Results", "Ничего не найдено"),
                systemImage: "magnifyingglass",
                description: Text(t("No words match your search.", "По этому запросу слов нет."))
            )
            Spacer()
        } else {
            List {
                Section {
                    ForEach(visibleWords) { word in
                        wordRow(word)
                            .padding(.horizontal, Spacing.xl)
                            .padding(.vertical, Spacing.xs)
                            .listRowInsets(EdgeInsets())
                            .listRowSeparator(.hidden)
                            .listRowBackground(Color.clear)
                    }
                } header: {
                    Text(t("Words", "Слова"))
                        .font(Typography.label)
                        .foregroundStyle(Palette.textTertiary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.horizontal, Spacing.xl)
                        .padding(.top, Spacing.lg)
                        .padding(.bottom, Spacing.xs)
                        .listRowInsets(EdgeInsets())
                        .listRowSeparator(.hidden)
                        .listRowBackground(Color.clear)
                }
            }
            .listStyle(.plain)
            .scrollContentBackground(.hidden)
        }
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
        .padding(.vertical, Spacing.xxs)
    }

    @ViewBuilder
    private func suggestionRow(_ suggestion: DictionarySuggestion) -> some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text(suggestion.corrected)
                    .font(Typography.body.weight(.semibold))
                    .foregroundStyle(Palette.textPrimary)
                Text(verbatim: "·")
                    .foregroundStyle(Palette.textTertiary)
                Text(correctedCountText(suggestion.hitCount))
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textTertiary)
            }

            Text(t("Heard \"\(suggestion.original)\"", "Распознано \"\(suggestion.original)\""))
                .font(Typography.caption)
                .foregroundStyle(Palette.textTertiary)

            HStack(spacing: Spacing.sm) {
                Button(t("Add", "Добавить")) {
                    dictionaryStore.add(word: suggestion.corrected, origin: "learned")
                    learningEngine.accept(suggestion)
                }
                .buttonStyle(.borderedProminent)

                Button(t("Replace", "Замена")) {
                    dictionaryStore.learnReplacement(word: suggestion.original, replacement: suggestion.corrected)
                    learningEngine.accept(suggestion)
                }
                .buttonStyle(.bordered)

                Button {
                    learningEngine.dismiss(suggestion)
                } label: {
                    Image(systemName: "xmark")
                }
                .buttonStyle(.borderless)
                .accessibilityLabel(t("Dismiss", "Скрыть"))
            }
        }
        .padding(Spacing.sm)
        .background(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .fill(Palette.accent.opacity(0.08))
        )
    }

    private func correctedCountText(_ count: Int) -> String {
        if OnboardingL10n.language(for: languageManager.current) == .russian {
            return "исправлено \(count)x"
        }
        return "corrected \(count)x"
    }

    private func dictionaryCountText(_ count: Int) -> String {
        if OnboardingL10n.language(for: languageManager.current) == .russian {
            return "Слов: \(count)"
        }
        return "\(count) word\(count == 1 ? "" : "s")"
    }

    @ViewBuilder
    private var explainerCopy: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(t(
                "Each entry biases the recognizer toward your spelling. Add an optional replacement to also auto-correct a known misspelling after transcription.",
                "Каждая запись подсказывает распознавателю нужное написание. Добавь замену, чтобы автоматически исправлять известную ошибку после распознавания."
            ))
                .font(Typography.bodySmall)
                .foregroundStyle(Palette.textSecondary)
            HStack(spacing: 12) {
                badgeLegend(label: biasBadgeLabel, color: Palette.accent, hint: t("boosts recognition", "помогает распознаванию"))
                badgeLegend(label: replaceBadgeLabel, color: .orange, hint: t("auto-corrects", "автозамена"))
            }
        }
        .padding(.vertical, Spacing.xxs)
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
        VStack(alignment: .leading, spacing: Spacing.sm) {
            TextField(t("Word or phrase", "Слово или фраза"), text: $newWord)
                .textFieldStyle(.roundedBorder)
                .font(Typography.body)
                .onSubmit { commitWord() }

            HStack(spacing: Spacing.sm) {
                Image(systemName: "arrow.right")
                    .font(.caption)
                    .foregroundStyle(Palette.textTertiary)
                TextField(t("Replace with (optional)", "Заменять на (необязательно)"), text: $newReplacement)
                    .textFieldStyle(.roundedBorder)
                    .font(Typography.body)
                    .onSubmit { commitWord() }
            }

            HStack {
                Text(t(
                    "Leave the replacement empty to add a vocabulary booster only.",
                    "Оставь замену пустой, если нужна только подсказка для распознавания."
                ))
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textTertiary)
                Spacer()
                if editingWord != nil {
                    Button(t("Cancel", "Отмена")) { cancelEdit() }
                        .buttonStyle(.plain)
                        .foregroundStyle(Palette.textSecondary)
                }
                Button(editingWord == nil ? t("Add", "Добавить") : t("Save", "Сохранить")) {
                    commitWord()
                }
                    .buttonStyle(.borderedProminent)
                    .disabled(newWord.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }

            if let duplicate = duplicateWord {
                HStack(spacing: 6) {
                    Text(t(
                        "\"\(duplicate)\" is already in your dictionary.",
                        "\"\(duplicate)\" уже есть в словаре."
                    ))
                        .font(Typography.caption)
                        .foregroundStyle(.red)
                    if let existing = existingEntry(matching: duplicate) {
                        Button(t("Edit the existing entry", "Изменить существующую запись")) {
                            beginEdit(existing)
                        }
                        .buttonStyle(.plain)
                        .font(Typography.caption)
                        .foregroundStyle(Palette.accent)
                    }
                }
            }
        }
        .padding(.vertical, Spacing.xxs)
    }

    @ViewBuilder
    private func wordRow(_ word: DictionaryWord) -> some View {
        HStack(alignment: .top, spacing: Spacing.md) {
            VStack(alignment: .leading, spacing: Spacing.xs) {
                HStack(alignment: .firstTextBaseline, spacing: Spacing.xs) {
                    Text(word.word)
                        .font(Typography.headingMedium)
                        .foregroundStyle(Palette.textPrimary)
                        .lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)

                    if word.isLearned {
                        Image(systemName: "sparkles")
                            .font(Typography.labelSmall)
                            .foregroundStyle(Palette.accent)
                            .accessibilityLabel(t("Learned from your edits", "Выучено из твоих правок"))
                    }
                }

                if let replacement = word.replacement, replacement != word.word {
                    HStack(alignment: .firstTextBaseline, spacing: Spacing.xs) {
                        Image(systemName: "arrow.right")
                            .font(Typography.labelSmall)
                            .foregroundStyle(Palette.textTertiary)
                        Text(replacement)
                            .font(Typography.bodySmall)
                            .foregroundStyle(Palette.textSecondary)
                            .lineLimit(2)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }

                dictionaryWordBadges(for: word)
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            Button {
                dictionaryStore.delete(word)
            } label: {
                Image(systemName: "xmark.circle.fill")
                    .font(Typography.label)
                    .foregroundStyle(Palette.textTertiary)
            }
            .buttonStyle(.borderless)
            .accessibilityLabel(t("Remove word", "Удалить слово"))
        }
        .padding(.vertical, Spacing.sm)
        .contentShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        .contextMenu {
            Button(t("Edit", "Изменить")) { beginEdit(word) }
            Button(t("Remove word", "Удалить слово"), role: .destructive) {
                dictionaryStore.delete(word)
            }
        }
    }

    @ViewBuilder
    private func dictionaryWordBadges(for word: DictionaryWord) -> some View {
        HStack(spacing: Spacing.xs) {
            if let replacement = word.replacement, replacement != word.word {
                badge(label: replaceBadgeLabel, color: .orange)
            } else {
                badge(label: biasBadgeLabel, color: Palette.accent)
            }

            if word.isLearned {
                badge(label: t("LEARNED", "ВЫУЧЕНО"), color: Palette.accent)
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
        guard dictionaryStore.add(word: trimmed, replacement: replacement) else {
            duplicateWord = trimmed
            return
        }
        duplicateWord = nil
        newWord = ""
        newReplacement = ""
    }

    private func commitWord() {
        if let editing = editingWord {
            let trimmed = newWord.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !trimmed.isEmpty else { return }
            let replacementTrimmed = newReplacement.trimmingCharacters(in: .whitespacesAndNewlines)
            let ok = dictionaryStore.update(
                editing,
                newWord: trimmed,
                newReplacement: replacementTrimmed.isEmpty ? nil : replacementTrimmed
            )
            if ok {
                cancelEdit()
            } else {
                duplicateWord = trimmed
            }
        } else {
            addWord()
        }
    }

    private func existingEntry(matching word: String) -> DictionaryWord? {
        dictionaryStore.words.first {
            $0.word.lowercased() == word.lowercased() && $0.id != editingWord?.id
        }
    }

    private func beginEdit(_ word: DictionaryWord) {
        editingWord = word
        newWord = word.word
        newReplacement = word.replacement ?? ""
        duplicateWord = nil
    }

    private func cancelEdit() {
        editingWord = nil
        newWord = ""
        newReplacement = ""
        duplicateWord = nil
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

private final class DictationDictionaryDisplayCache {
    private var lastWordsRevision: Int?
    private var lastSearchText = ""
    private var cachedWords: [DictionaryWord] = []

    func words(for words: [DictionaryWord], revision: Int, searchText: String) -> [DictionaryWord] {
        let normalizedSearch = searchText.trimmingCharacters(in: .whitespacesAndNewlines)
        if revision == lastWordsRevision, normalizedSearch == lastSearchText {
            return cachedWords
        }
        if normalizedSearch.isEmpty {
            cachedWords = words
        } else {
            cachedWords = words.filter {
                $0.word.localizedCaseInsensitiveContains(normalizedSearch)
                    || ($0.replacement?.localizedCaseInsensitiveContains(normalizedSearch) ?? false)
            }
        }
        lastWordsRevision = revision
        lastSearchText = normalizedSearch
        return cachedWords
    }
}
