import SwiftUI
import WaiComputerKit

/// List of saved comparison sets (forward several items → a comparison table).
struct ComparisonListView: View {
    let apiClient: APIClient

    @EnvironmentObject private var languageManager: LanguageManager
    @State private var entries: [ComparisonListEntry] = []
    @State private var loading = true

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }

    var body: some View {
        Group {
            if loading {
                ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if entries.isEmpty {
                ContentUnavailableViewCompat(
                    t("No comparisons yet", "Пока нет сравнений"),
                    systemImage: "tablecells",
                    description: Text(t(
                        "Select several items to compare them side by side.",
                        "Выберите несколько материалов, чтобы сравнить их рядом."
                    ))
                )
            } else {
                List(entries) { entry in
                    NavigationLink {
                        ComparisonDetailView(apiClient: apiClient, comparisonId: entry.id)
                    } label: {
                        VStack(alignment: .leading, spacing: Spacing.xxs) {
                            Text(entry.title ?? t("Comparison", "Сравнение"))
                                .font(Typography.body.weight(.medium))
                            Text(t("\(entry.itemCount) items", "\(entry.itemCount) материалов"))
                                .font(Typography.labelSmall)
                                .foregroundStyle(Palette.textTertiary)
                        }
                    }
                }
                .listStyle(.plain)
            }
        }
        .navigationTitle(t("Comparisons", "Сравнения"))
        .navigationBarTitleDisplayMode(.inline)
        .task { await load() }
    }

    private func load() async {
        loading = true
        defer { loading = false }
        entries = (try? await apiClient.listComparisons()) ?? []
    }
}

/// Renders one ComparisonSet as a table. Polls briefly while the background
/// build runs (status "generating" → "ready"). Ported from macOS MacComparisonView.
struct ComparisonDetailView: View {
    let apiClient: APIClient
    let comparisonId: String

    @EnvironmentObject private var languageManager: LanguageManager
    @State private var set: ComparisonSet?
    @State private var loading = true
    @State private var pollCount = 0

    private let maxPolls = 30

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }

    var body: some View {
        content
            .navigationTitle(set?.title ?? t("Comparison", "Сравнение"))
            .navigationBarTitleDisplayMode(.inline)
            .task { await loadUntilReady() }
    }

    @ViewBuilder
    private var content: some View {
        if loading || set?.status == "generating" {
            VStack(spacing: Spacing.sm) {
                ProgressView()
                Text(t("Building comparison…", "Строим сравнение…"))
                    .font(Typography.bodySmall)
                    .foregroundStyle(Palette.textSecondary)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        } else if set?.status == "failed" {
            ContentUnavailableViewCompat(
                t("Couldn't build comparison", "Не удалось построить сравнение"),
                systemImage: "exclamationmark.triangle",
                description: Text(set?.schemaRationale ?? "")
            )
        } else if let set, let columns = set.columns, let rows = set.rows, !columns.isEmpty {
            comparisonTable(columns: columns, rows: rows, rationale: set.schemaRationale)
        } else {
            ContentUnavailableViewCompat(
                t("No comparison data", "Нет данных"),
                systemImage: "tablecells"
            )
        }
    }

    private func comparisonTable(
        columns: [ComparisonColumn],
        rows: [ComparisonRow],
        rationale: String?
    ) -> some View {
        ScrollView([.horizontal, .vertical]) {
            VStack(alignment: .leading, spacing: Spacing.md) {
                if let rationale, !rationale.isEmpty {
                    Text(rationale)
                        .font(Typography.bodySmall)
                        .foregroundStyle(Palette.textSecondary)
                }
                Grid(alignment: .topLeading, horizontalSpacing: Spacing.lg, verticalSpacing: Spacing.sm) {
                    GridRow {
                        Text(t("Item", "Материал")).font(Typography.labelSmall.weight(.semibold))
                        ForEach(columns) { column in
                            Text(column.name).font(Typography.labelSmall.weight(.semibold))
                        }
                    }
                    Divider()
                    ForEach(rows) { row in
                        GridRow {
                            Text(row.title).font(Typography.bodySmall.weight(.medium))
                            ForEach(columns) { column in
                                Text(cell(row, column.name))
                                    .font(Typography.bodySmall)
                                    .foregroundStyle(Palette.textSecondary)
                            }
                        }
                    }
                }
            }
            .padding(Spacing.lg)
        }
    }

    private func cell(_ row: ComparisonRow, _ column: String) -> String {
        if let value = row.values[column], let value { return value }
        return "—"
    }

    private func loadUntilReady() async {
        while pollCount < maxPolls {
            do {
                let result = try await apiClient.getComparison(id: comparisonId)
                set = result
                loading = false
                if result.status != "generating" { return }
            } catch {
                loading = false
                return
            }
            pollCount += 1
            try? await Task.sleep(nanoseconds: 2_000_000_000)
        }
    }
}
