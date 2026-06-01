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
    @State private var searchText = ""
    @State private var showClearConfirmation = false

    private var filteredEntries: [DictationHistoryEntry] {
        if searchText.isEmpty { return historyStore.entries }
        return historyStore.entries.filter {
            $0.displayText.localizedCaseInsensitiveContains(searchText)
        }
    }

    var body: some View {
        List {
            if !historyStore.entries.isEmpty {
                Section { statsHeader }
            }

            if filteredEntries.isEmpty {
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
                ForEach(groupedByDay, id: \.date) { group in
                    Section(group.label) {
                        ForEach(group.entries) { entry in
                            HistoryEntryRow(entry: entry)
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
        .navigationTitle(t("Dictation History", "История диктовки"))
        .navigationBarTitleDisplayMode(.inline)
        .searchable(text: $searchText, prompt: t("Search dictations", "Искать в диктовках"))
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
                label = IOSDateFormatting.string(
                    from: date,
                    dateStyle: .long,
                    timeStyle: .none,
                    language: languageManager.current
                )
            }
            return DayGroup(date: date, label: label, entries: grouped[date]!.sorted { $0.timestamp > $1.timestamp })
        }
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

// MARK: - Entry Row

private struct HistoryEntryRow: View {
    @EnvironmentObject private var languageManager: LanguageManager
    let entry: DictationHistoryEntry
    @State private var isCopied = false

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

            Text(entry.displayText)
                .font(Typography.body)
                .foregroundStyle(Palette.textPrimary)
                .lineLimit(4)
                .frame(maxWidth: .infinity, alignment: .leading)

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
        }
        .padding(.vertical, Spacing.xxs)
        .contextMenu {
            Button {
                UIPasteboard.general.string = entry.displayText
            } label: {
                Label(t("Copy", "Скопировать"), systemImage: "doc.on.doc")
            }
        }
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}
