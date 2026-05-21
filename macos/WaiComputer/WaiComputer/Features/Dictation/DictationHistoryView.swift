import SwiftUI
import WaiComputerKit

struct DictationHistoryView: View {
    @EnvironmentObject private var historyStore: DictationHistoryStore
    @EnvironmentObject private var languageManager: LanguageManager
    @State private var searchText = ""

    private var filteredEntries: [DictationHistoryEntry] {
        if searchText.isEmpty { return historyStore.entries }
        return historyStore.entries.filter {
            $0.displayText.localizedCaseInsensitiveContains(searchText)
        }
    }

    var body: some View {
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
                TextField(t("Search dictations...", "Искать в диктовках..."), text: $searchText)
                    .textFieldStyle(.plain)
                    .font(Typography.body)
            }
            .padding(.horizontal, Spacing.xl)
            .padding(.vertical, Spacing.md)

            Divider()

            // Entries list
            if filteredEntries.isEmpty {
                Spacer()
                ContentUnavailableView(
                    searchText.isEmpty ? t("No Dictations Yet", "Пока нет диктовок") : t("No Results", "Ничего не найдено"),
                    systemImage: searchText.isEmpty ? "mic.badge.plus" : "magnifyingglass",
                    description: Text(searchText.isEmpty
                        ? t("Press your dictation hotkey to start. Your transcriptions will appear here.", "Нажми клавишу диктовки, чтобы начать. Расшифровки появятся здесь.")
                        : t("No dictations match your search.", "По этому запросу диктовок нет."))
                )
                Spacer()
            } else {
                ScrollView {
                    LazyVStack(spacing: 0) {
                        ForEach(groupedByDay, id: \.date) { group in
                            Section {
                                ForEach(group.entries) { entry in
                                    HistoryEntryRow(entry: entry, onDelete: {
                                        historyStore.delete(entry)
                                    })
                                }
                            } header: {
                                Text(group.label)
                                    .font(Typography.label)
                                    .foregroundStyle(Palette.textTertiary)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                    .padding(.horizontal, Spacing.xl)
                                    .padding(.top, Spacing.lg)
                                    .padding(.bottom, Spacing.xs)
                            }
                        }
                    }
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                if !historyStore.entries.isEmpty {
                    Button(t("Clear All", "Очистить все")) {
                        Task { await historyStore.deleteAll() }
                    }
                    .foregroundStyle(.red)
                }
            }
        }
    }

    // MARK: - Grouping

    private struct DayGroup {
        let date: Date
        let label: String
        let entries: [DictationHistoryEntry]
    }

    private var groupedByDay: [DayGroup] {
        let calendar = Calendar.current
        let grouped = Dictionary(grouping: filteredEntries) { entry in
            calendar.startOfDay(for: entry.timestamp)
        }
        return grouped.keys.sorted(by: >).map { date in
            let label: String
            if calendar.isDateInToday(date) {
                label = t("Today", "Сегодня")
            } else if calendar.isDateInYesterday(date) {
                label = t("Yesterday", "Вчера")
            } else {
                label = date.formatted(date: .abbreviated, time: .omitted)
            }
            return DayGroup(date: date, label: label, entries: grouped[date]!.sorted { $0.timestamp > $1.timestamp })
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

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

// MARK: - Entry Row

private struct HistoryEntryRow: View {
    @EnvironmentObject private var languageManager: LanguageManager
    let entry: DictationHistoryEntry
    let onDelete: () -> Void
    @State private var isCopied = false

    var body: some View {
        HStack(alignment: .top, spacing: Spacing.md) {
            Text(entry.timestamp.formatted(date: .omitted, time: .shortened))
                .font(Typography.mono)
                .foregroundStyle(Palette.textTertiary)
                .frame(width: 60, alignment: .leading)

            Text(entry.displayText)
                .font(Typography.body)
                .foregroundStyle(Palette.textPrimary)
                .lineLimit(4)
                .frame(maxWidth: .infinity, alignment: .leading)

            HStack(spacing: Spacing.sm) {
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

                Button(action: onDelete) {
                    Image(systemName: "trash")
                        .foregroundStyle(Palette.textSecondary)
                }
                .buttonStyle(.plain)
                .help(t("Delete", "Удалить"))
            }
        }
        .padding(.horizontal, Spacing.xl)
        .padding(.vertical, Spacing.md)
        .contentShape(Rectangle())
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}
