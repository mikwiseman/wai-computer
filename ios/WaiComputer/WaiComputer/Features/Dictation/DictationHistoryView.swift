import SwiftUI
import UIKit
import WaiComputerKit

/// Server-synced dictation history. iOS-idiomatic port of the macOS
/// `DictationHistoryView`: stats header, `.searchable` filter, day-grouped
/// `List` with swipe-to-delete, per-row copy (UIPasteboard), and a "Clear All"
/// toolbar action.
struct DictationHistoryView: View {
    @EnvironmentObject private var historyStore: DictationHistoryStore
    @EnvironmentObject private var languageManager: LanguageManager
    @EnvironmentObject private var learningEngine: DictionaryLearningEngine
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass
    @AppStorage(IOSDictationLearningSettings.enabledDefaultsKey) private var learnFromEditsEnabled = true
    @State private var searchText = ""
    @State private var showClearConfirmation = false
    @State private var displayCache = DictationHistoryDisplayCache()

    var body: some View {
        let groups = displayCache.groups(
            for: historyStore.entries,
            revision: historyStore.entriesRevision,
            searchText: searchText,
            language: languageManager.current
        )

        Group {
            if isRegularWidth {
                regularHistoryLayout(groups)
            } else {
                compactHistoryList(groups)
            }
        }
        .navigationTitle(t("Dictation History", "История диктовки"))
        .navigationBarTitleDisplayMode(isRegularWidth ? .inline : .large)
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                if !historyStore.entries.isEmpty {
                    Button(role: .destructive) {
                        showClearConfirmation = true
                    } label: {
                        Text(t("Clear All", "Очистить все"))
                    }
                }
            }
        }
        .confirmationDialog(
            t("Clear all dictation history?", "Очистить всю историю диктовки?"),
            isPresented: $showClearConfirmation,
            titleVisibility: .visible
        ) {
            Button(t("Clear All", "Очистить все"), role: .destructive) {
                Task { await historyStore.deleteAll() }
            }
            Button(t("Cancel", "Отмена"), role: .cancel) {}
        } message: {
            Text(t(
                "This permanently removes every dictation from this device and the server.",
                "Это безвозвратно удалит все диктовки с этого устройства и с сервера."
            ))
        }
    }

    private var isRegularWidth: Bool {
        horizontalSizeClass == .regular
    }

    private func regularHistoryLayout(_ groups: [DictationHistoryDayGroup]) -> some View {
        VStack(spacing: 0) {
            regularHeader
            Divider()
            regularSearchField
            Divider()
            regularHistoryResults(groups: groups)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color(uiColor: .systemGroupedBackground))
        .accessibilityIdentifier("ios-dictation-history-regular-layout")
    }

    private func compactHistoryList(_ groups: [DictationHistoryDayGroup]) -> some View {
        List {
            if !historyStore.entries.isEmpty {
                Section { statsHeader }
            }

            if groups.isEmpty {
                Section {
                    ContentUnavailableViewCompat(
                        searchText.isEmpty ? t("No Dictations Yet", "Пока нет диктовок") : t("No Results", "Ничего не найдено"),
                        systemImage: searchText.isEmpty ? "mic.badge.plus" : "magnifyingglass",
                        description: Text(searchText.isEmpty
                            ? t("Your dictations sync here across your devices.", "Твои диктовки синхронизируются здесь между устройствами.")
                            : t("No dictations match your search.", "По этому запросу диктовок нет."))
                    )
                }
            } else {
                ForEach(groups) { group in
                    Section(group.label) {
                        ForEach(group.entries) { entry in
                            HistoryEntryRow(
                                entry: entry,
                                onDelete: { historyStore.delete(entry) },
                                onCorrect: { correctedText in
                                    applyCorrection(to: entry, correctedText: correctedText)
                                }
                            )
                                .swipeActions(edge: .trailing) {
                                    Button(role: .destructive) {
                                        historyStore.delete(entry)
                                    } label: {
                                        Label(t("Delete", "Удалить"), systemImage: "trash")
                                    }
                                }
                        }
                    }
                }
            }
        }
        .searchable(text: $searchText, prompt: t("Search dictations", "Искать в диктовках"))
        .accessibilityIdentifier("ios-dictation-history-compact-list")
    }

    private var regularHeader: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: Spacing.xs) {
                Text(t("Dictation History", "История диктовки"))
                    .font(Typography.displaySmall)
                    .foregroundStyle(Palette.textPrimary)
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
        .background(Palette.surfaceSubtle)
        .accessibilityIdentifier("ios-dictation-history-regular-header")
    }

    private var regularSearchField: some View {
        HStack(spacing: Spacing.sm) {
            Image(systemName: "magnifyingglass")
                .foregroundStyle(Palette.textTertiary)
            TextField(t("Search dictations…", "Искать в диктовках…"), text: $searchText)
                .textFieldStyle(.plain)
                .font(Typography.body)
                .accessibilityIdentifier("ios-dictation-history-search-field")
        }
        .padding(.horizontal, Spacing.xl)
        .padding(.vertical, Spacing.md)
        .background(Palette.surfaceSubtle)
    }

    @ViewBuilder
    private func regularHistoryResults(groups: [DictationHistoryDayGroup]) -> some View {
        if groups.isEmpty {
            Spacer()
            ContentUnavailableViewCompat(
                searchText.isEmpty ? t("No Dictations Yet", "Пока нет диктовок") : t("No Results", "Ничего не найдено"),
                systemImage: searchText.isEmpty ? "mic.badge.plus" : "magnifyingglass",
                description: Text(searchText.isEmpty
                    ? t("Your dictations sync here across your devices.", "Твои диктовки синхронизируются здесь между устройствами.")
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
                                onCorrect: { correctedText in
                                    applyCorrection(to: entry, correctedText: correctedText)
                                }
                            )
                            .padding(.horizontal, Spacing.xl)
                            .padding(.vertical, Spacing.xs)
                            .listRowInsets(EdgeInsets())
                            .listRowSeparator(.hidden)
                            .listRowBackground(Color.clear)
                            .swipeActions(edge: .trailing) {
                                Button(role: .destructive) {
                                    historyStore.delete(entry)
                                } label: {
                                    Label(t("Delete", "Удалить"), systemImage: "trash")
                                }
                            }
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

    // MARK: - Stats

    private var statsHeader: some View {
        HStack {
            statBadge(value: formatNumber(historyStore.totalWords), label: t("total words", "всего слов"))
            Spacer()
            statBadge(value: "\(historyStore.averageWPM)", label: t("wpm", "слов/мин"))
            Spacer()
            statBadge(value: "\(historyStore.streakDays)", label: t("day streak", "дней подряд"))
        }
        .padding(.vertical, Spacing.xs)
    }

    private func statBadge(value: String, label: String) -> some View {
        VStack(spacing: 2) {
            Text(value)
                .font(Typography.headingLarge)
                .foregroundStyle(Palette.textPrimary)
            Text(label)
                .font(Typography.caption)
                .foregroundStyle(Palette.textTertiary)
        }
        .frame(maxWidth: .infinity)
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

    /// A correction made while reviewing a past dictation. The store persists the
    /// fixed text locally, and the learning engine observes only the token-level
    /// correction candidates it can extract.
    private func applyCorrection(to entry: DictationHistoryEntry, correctedText: String) {
        let original = entry.displayText
        guard historyStore.applyCorrection(to: entry, correctedText: correctedText) else { return }
        if learnFromEditsEnabled {
            learningEngine.observeEdit(produced: original, edited: correctedText, language: nil)
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
        return IOSDateFormatting.string(
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
    @State private var isExpanded = false
    @State private var isEditing = false
    @State private var draft = ""

    var body: some View {
        HStack(alignment: .top, spacing: Spacing.md) {
            Text(IOSDateFormatting.string(
                from: entry.timestamp,
                dateStyle: .none,
                timeStyle: .short,
                language: languageManager.current
            ))
                .font(Typography.mono)
                .foregroundStyle(Palette.textTertiary)
                .frame(width: 64, alignment: .leading)

            if isEditing {
                TextField("", text: $draft, axis: .vertical)
                    .textFieldStyle(.plain)
                    .font(Typography.body)
                    .foregroundStyle(Palette.textPrimary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .onSubmit { commitEdit() }
            } else {
                Text(entry.displayText)
                    .font(Typography.body)
                    .foregroundStyle(Palette.textPrimary)
                    .textSelection(.enabled)
                    .lineLimit(isExpanded ? nil : 4)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .onTapGesture { isExpanded.toggle() }
            }

            HStack(spacing: Spacing.sm) {
                if isEditing {
                    Button { commitEdit() } label: {
                        Image(systemName: "checkmark.circle")
                            .foregroundStyle(.green)
                    }
                    .buttonStyle(.borderless)
                    .accessibilityLabel(t("Save correction", "Сохранить исправление"))

                    Button { cancelEdit() } label: {
                        Image(systemName: "xmark.circle")
                            .foregroundStyle(Palette.textSecondary)
                    }
                    .buttonStyle(.borderless)
                    .accessibilityLabel(t("Cancel editing", "Отменить редактирование"))
                } else {
                    Button {
                        draft = entry.displayText
                        isEditing = true
                    } label: {
                        Image(systemName: "pencil")
                            .foregroundStyle(Palette.textSecondary)
                    }
                    .buttonStyle(.borderless)
                    .accessibilityLabel(t("Fix this dictation and teach the dictionary", "Исправить диктовку и научить словарь"))
                }

                Button {
                    UIPasteboard.general.string = entry.displayText
                    isCopied = true
                    DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { isCopied = false }
                } label: {
                    Image(systemName: isCopied ? "checkmark" : "doc.on.doc")
                        .foregroundStyle(isCopied ? .green : Palette.textSecondary)
                }
                .buttonStyle(.borderless)
                .accessibilityLabel(t("Copy to clipboard", "Скопировать в буфер"))

                Button(action: onDelete) {
                    Image(systemName: "trash")
                        .foregroundStyle(Palette.textSecondary)
                }
                .buttonStyle(.borderless)
                .accessibilityLabel(t("Delete", "Удалить"))
            }
        }
        .padding(.vertical, Spacing.xxs)
        .contextMenu {
            Button {
                UIPasteboard.general.string = entry.displayText
            } label: {
                Label(t("Copy", "Скопировать"), systemImage: "doc.on.doc")
            }
            Button(t("Edit", "Изменить")) {
                draft = entry.displayText
                isEditing = true
            }
            Button(t("Delete", "Удалить"), role: .destructive, action: onDelete)
        }
    }

    private func commitEdit() {
        let trimmed = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        isEditing = false
        guard !trimmed.isEmpty, trimmed != entry.displayText else { return }
        onCorrect(trimmed)
    }

    private func cancelEdit() {
        isEditing = false
        draft = ""
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}
