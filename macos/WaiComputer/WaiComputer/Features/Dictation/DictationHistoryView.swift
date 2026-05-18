import SwiftUI

struct DictationHistoryView: View {
    @EnvironmentObject private var historyStore: DictationHistoryStore
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
                    Text("Dictation History")
                        .font(Typography.displaySmall)
                    Text("\(historyStore.entries.count) dictations")
                        .font(Typography.bodySmall)
                        .foregroundStyle(Palette.textSecondary)
                }

                Spacer()

                HStack(spacing: Spacing.xl) {
                    statBadge(value: formatNumber(historyStore.totalWords), label: "total words")
                    statBadge(value: "\(historyStore.averageWPM)", label: "wpm")
                    statBadge(value: "\(historyStore.streakDays)", label: "day streak")
                }
            }
            .padding(Spacing.xl)

            Divider()

            // Search
            HStack {
                Image(systemName: "magnifyingglass")
                    .foregroundStyle(Palette.textTertiary)
                TextField("Search dictations...", text: $searchText)
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
                    searchText.isEmpty ? "No Dictations Yet" : "No Results",
                    systemImage: searchText.isEmpty ? "mic.badge.plus" : "magnifyingglass",
                    description: Text(searchText.isEmpty
                        ? "Press your dictation hotkey to start. Your transcriptions will appear here."
                        : "No dictations match your search.")
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
                    Button("Clear All") {
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
                label = "Today"
            } else if calendar.isDateInYesterday(date) {
                label = "Yesterday"
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
}

// MARK: - Entry Row

private struct HistoryEntryRow: View {
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
                .help("Copy to clipboard")

                Button(action: onDelete) {
                    Image(systemName: "trash")
                        .foregroundStyle(Palette.textSecondary)
                }
                .buttonStyle(.plain)
                .help("Delete")
            }
        }
        .padding(.horizontal, Spacing.xl)
        .padding(.vertical, Spacing.md)
        .contentShape(Rectangle())
    }
}
