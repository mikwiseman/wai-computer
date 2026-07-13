import SwiftUI
import WaiComputerKit

struct DictationHistoryView: View {
    @EnvironmentObject private var historyStore: DictationHistoryStore
    @EnvironmentObject private var languageManager: LanguageManager
    @EnvironmentObject private var learningEngine: DictionaryLearningEngine
    @State private var searchText = ""
    @State private var showClearAllConfirmation = false
    @State private var displayCache = DictationHistoryDisplayCache()

    var body: some View {
        let groups = displayCache.groups(
            for: historyStore.entries,
            revision: historyStore.entriesRevision,
            searchText: searchText,
            language: languageManager.current
        )

        VStack(spacing: 0) {
            // Header with stats
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: Spacing.xs) {
                    Text(t("Dictation History", "История диктовки"))
                        .font(Typography.displaySmall)
                    Text(dictationsCountText(historyStore.entries.count))
                        .font(Typography.bodySmall)
                        .foregroundStyle(Palette.textSecondary)
                }

                Spacer()

                HStack(spacing: Spacing.xl) {
                    statBadge(value: formatNumber(historyStore.totalWords), label: t("total words", "всего слов"))
                    statBadge(value: "\(historyStore.averageWPM)", label: t("wpm", "слов/мин"))
                    statBadge(value: "\(historyStore.streakDays)", label: t("day streak", "дней подряд"))
                }
            }
            .padding(Spacing.xl)

            Divider()

            // Search
            HStack {
                Image(systemName: "magnifyingglass")
                    .foregroundStyle(Palette.textTertiary)
                TextField(t("Search dictations…", "Искать в диктовках…"), text: $searchText)
                    .textFieldStyle(.plain)
                    .font(Typography.body)
            }
            .padding(.horizontal, Spacing.xl)
            .padding(.vertical, Spacing.md)

            Divider()

            // Entries list
            if groups.isEmpty {
                Spacer()
                ContentUnavailableViewCompat(
                    searchText.isEmpty ? t("No Dictations Yet", "Пока нет диктовок") : t("No Results", "Ничего не найдено"),
                    systemImage: searchText.isEmpty ? "mic.badge.plus" : "magnifyingglass",
                    description: Text(searchText.isEmpty
                        ? t("Press your dictation hotkey to start. Your transcriptions will appear here.", "Нажми клавишу диктовки, чтобы начать. Расшифровки появятся здесь.")
                        : t("No dictations match your search.", "По этому запросу диктовок нет."))
                )
                Spacer()
            } else {
                List {
                    ForEach(groups) { group in
                        Section {
                            ForEach(group.entries) { entry in
                                HistoryEntryRow(
                                    entry: entry,
                                    onDelete: { historyStore.delete(entry) },
                                    onCorrect: { newText in applyCorrection(to: entry, newText: newText) }
                                )
                                .listRowInsets(EdgeInsets())
                                .listRowSeparator(.hidden)
                                .listRowBackground(Color.clear)
                            }
                        } header: {
                            Text(group.label)
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
                }
                .listStyle(.plain)
                .scrollContentBackground(.hidden)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                if !historyStore.entries.isEmpty {
                    Button(t("Clear All", "Очистить все")) {
                        showClearAllConfirmation = true
                    }
                    .foregroundStyle(Palette.danger)
                }
            }
        }
        .confirmationDialog(
            t("Clear all dictation history?", "Очистить всю историю диктовки?"),
            isPresented: $showClearAllConfirmation,
            titleVisibility: .visible
        ) {
            Button(t("Clear All", "Очистить все"), role: .destructive) {
                Task { await historyStore.deleteAll() }
            }
            Button(t("Cancel", "Отмена"), role: .cancel) {}
        } message: {
            Text(t(
                "This deletes every dictation on all your devices. This can't be undone.",
                "Это удалит все диктовки на всех твоих устройствах. Это нельзя отменить."
            ))
        }
    }

    // MARK: - Helpers

    private func statBadge(value: String, label: String) -> some View {
        VStack(spacing: 2) {
            Text(value)
                .font(Typography.headingLarge)
                .foregroundStyle(Palette.textPrimary)
            Text(label)
                .font(Typography.caption)
                .foregroundStyle(Palette.textTertiary)
        }
    }

    private func formatNumber(_ n: Int) -> String {
        if n >= 1000 {
            return String(format: "%.1fK", Double(n) / 1000.0)
        }
        return "\(n)"
    }

    private func dictationsCountText(_ count: Int) -> String {
        if OnboardingL10n.language(for: languageManager.current) == .russian {
            return "Диктовок: \(count)"
        }
        return "\(count) dictation\(count == 1 ? "" : "s")"
    }

    /// A correction the user made while reviewing a past dictation. Persists the
    /// fixed text locally and teaches the dictionary on-device (when enabled).
    private func applyCorrection(to entry: DictationHistoryEntry, newText: String) {
        let original = entry.displayText
        guard historyStore.applyCorrection(to: entry, correctedText: newText) else { return }
        let learnEnabled = UserDefaults.standard.object(
            forKey: DictationEditWatcher.enabledDefaultsKey
        ) as? Bool ?? true
        if learnEnabled {
            learningEngine.observeEdit(produced: original, edited: newText, language: nil)
        }
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

// MARK: - Display Projection

private struct DictationHistoryDayGroup: Identifiable {
    let date: Date
    let label: String
    let entries: [DictationHistoryEntry]

    var id: Date { date }
}

/// The history list can grow to thousands of local dictations. Search,
/// grouping, day sorting, and localized section labels are an O(N log N)
/// projection, so keep that work out of ordinary SwiftUI row/body updates.
private final class DictationHistoryDisplayCache {
    private var lastEntriesRevision: Int?
    private var lastSearchText = ""
    private var lastLanguage: LanguageManager.SupportedLanguage?
    private var cachedGroups: [DictationHistoryDayGroup] = []

    func groups(
        for entries: [DictationHistoryEntry],
        revision: Int,
        searchText: String,
        language: LanguageManager.SupportedLanguage
    ) -> [DictationHistoryDayGroup] {
        let normalizedSearch = searchText.trimmingCharacters(in: .whitespacesAndNewlines)
        if revision == lastEntriesRevision,
           normalizedSearch == lastSearchText,
           language == lastLanguage {
            return cachedGroups
        }

        let filtered: [DictationHistoryEntry]
        if normalizedSearch.isEmpty {
            filtered = entries
        } else {
            filtered = entries.filter {
                $0.displayText.localizedCaseInsensitiveContains(normalizedSearch)
            }
        }

        let calendar = Calendar.current
        let grouped = Dictionary(grouping: filtered) { entry in
            calendar.startOfDay(for: entry.timestamp)
        }
        cachedGroups = grouped.keys.sorted(by: >).map { date in
            DictationHistoryDayGroup(
                date: date,
                label: Self.label(for: date, calendar: calendar, language: language),
                entries: grouped[date]?.sorted { $0.timestamp > $1.timestamp } ?? []
            )
        }
        lastEntriesRevision = revision
        lastSearchText = normalizedSearch
        lastLanguage = language
        return cachedGroups
    }

    private static func label(
        for date: Date,
        calendar: Calendar,
        language: LanguageManager.SupportedLanguage
    ) -> String {
        if calendar.isDateInToday(date) {
            return OnboardingL10n.text("Today", "Сегодня", language: language)
        }
        if calendar.isDateInYesterday(date) {
            return OnboardingL10n.text("Yesterday", "Вчера", language: language)
        }
        return MacDateFormatting.string(
            from: date,
            dateStyle: .long,
            timeStyle: .none,
            language: language
        )
    }
}

// MARK: - Entry Row

private struct HistoryEntryRow: View {
    @EnvironmentObject private var languageManager: LanguageManager
    let entry: DictationHistoryEntry
    let onDelete: () -> Void
    let onCorrect: (String) -> Void
    @State private var isCopied = false
    @State private var isHovered = false
    @State private var isExpanded = false
    @State private var isEditing = false
    @State private var draft = ""
    @State private var showDeleteConfirm = false

    var body: some View {
        HStack(alignment: .top, spacing: Spacing.md) {
            Text(MacDateFormatting.string(
                from: entry.timestamp,
                dateStyle: .none,
                timeStyle: .short,
                language: languageManager.current
            ))
                .font(Typography.mono)
                .foregroundStyle(Palette.textTertiary)
                .frame(width: 60, alignment: .leading)

            if isEditing {
                TextField("", text: $draft, axis: .vertical)
                    .textFieldStyle(.plain)
                    .font(Typography.body)
                    .foregroundStyle(Palette.textPrimary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .onSubmit { commitEdit() }
                    .onEscapeKeyCompat { cancelEdit() }
            } else {
                Text(entry.displayText)
                    .font(Typography.body)
                    .foregroundStyle(Palette.textPrimary)
                    .textSelection(.enabled)
                    .lineLimit(isExpanded ? nil : 4)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .help(t("Click to expand", "Нажмите, чтобы развернуть"))
                    .onTapGesture { isExpanded.toggle() }
            }

            HStack(spacing: Spacing.sm) {
                if isEditing {
                    Button { commitEdit() } label: {
                        Image(systemName: "checkmark.circle")
                            .foregroundStyle(Palette.success)
                    }
                    .buttonStyle(.plain)
                    .help(t("Save correction", "Сохранить исправление"))

                    Button { cancelEdit() } label: {
                        Image(systemName: "xmark.circle")
                            .foregroundStyle(Palette.textSecondary)
                    }
                    .buttonStyle(.plain)
                    .help(t("Cancel editing (Esc)", "Отменить редактирование (Esc)"))
                } else {
                    Button {
                        draft = entry.displayText
                        isEditing = true
                    } label: {
                        Image(systemName: "pencil")
                            .foregroundStyle(Palette.textSecondary)
                    }
                    .buttonStyle(.plain)
                    .help(t("Fix this dictation & teach the dictionary", "Исправить диктовку и научить словарь"))
                }

                Button {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(entry.displayText, forType: .string)
                    isCopied = true
                    DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { isCopied = false }
                } label: {
                    Image(systemName: isCopied ? "checkmark" : "doc.on.doc")
                        .foregroundStyle(isCopied ? .green : Palette.textSecondary)
                }
                .buttonStyle(.plain)
                .help(t("Copy to clipboard", "Скопировать в буфер"))

                Button { showDeleteConfirm = true } label: {
                    Image(systemName: "trash")
                        .foregroundStyle(isHovered ? Palette.danger : Palette.textSecondary)
                }
                .buttonStyle(.plain)
                .help(t("Delete", "Удалить"))
                .accessibilityLabel(t("Delete", "Удалить"))
                .confirmationDialog(
                    t("Delete this dictation?", "Удалить эту диктовку?"),
                    isPresented: $showDeleteConfirm,
                    titleVisibility: .visible
                ) {
                    Button(t("Delete", "Удалить"), role: .destructive) { onDelete() }
                    Button(t("Cancel", "Отмена"), role: .cancel) {}
                } message: {
                    Text(t("This can't be undone.", "Это действие нельзя отменить."))
                }
            }
        }
        .padding(.horizontal, Spacing.xl)
        .padding(.vertical, Spacing.md)
        .background(isHovered ? Palette.surfaceHover : Color.clear)
        .contentShape(Rectangle())
        .onHover { isHovered = $0 }
    }

    private func commitEdit() {
        let trimmed = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        isEditing = false
        guard !trimmed.isEmpty, trimmed != entry.displayText else { return }
        onCorrect(trimmed)
    }

    /// Abandon the draft without committing — an accidental commit would
    /// both rewrite the entry and teach the learned dictionary.
    private func cancelEdit() {
        isEditing = false
        draft = ""
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}
