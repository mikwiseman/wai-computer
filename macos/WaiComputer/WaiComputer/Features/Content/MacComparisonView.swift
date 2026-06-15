import SwiftUI
import WaiComputerKit

/// Renders a multi-item ComparisonSet as a table. Polls briefly while the
/// background build runs (status "generating" -> "ready").
struct MacComparisonView: View {
    let apiClient: APIClient
    let comparisonId: String
    let onClose: () -> Void

    @EnvironmentObject private var languageManager: LanguageManager
    @State private var set: ComparisonSet?
    @State private var loading = true
    @State private var pollCount = 0
    @State private var loadError: String?

    private let maxPolls = 30

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Divider()
            content
        }
        .task { await loadUntilReady() }
    }

    private var header: some View {
        HStack {
            Text(set?.title ?? t("Comparison", "Сравнение"))
                .font(Typography.displaySmall)
            Spacer()
            Button(t("Close", "Закрыть"), action: onClose)
                .buttonStyle(.bordered)
        }
        .padding(Spacing.xl)
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
        } else if let loadError {
            ContentUnavailableViewCompat(
                t("Couldn't load comparison", "Не удалось загрузить сравнение"),
                systemImage: "exclamationmark.triangle",
                description: Text(loadError)
            )
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

    // LLM-generated values can be sentence-long. Cap each column and let text
    // wrap so the table remains readable without asking SwiftUI for unbounded
    // ideal widths.
    private let titleColumnWidth: CGFloat = 200
    private let valueColumnWidth: CGFloat = 260
    private let rationaleMaxWidth: CGFloat = 720

    private func comparisonTable(
        columns: [ComparisonColumn],
        rows: [ComparisonRow],
        rationale: String?
    ) -> some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            if let rationale, !rationale.isEmpty {
                Text(rationale)
                    .font(Typography.bodySmall)
                    .foregroundStyle(Palette.textSecondary)
                    .frame(maxWidth: rationaleMaxWidth, alignment: .leading)
                    .padding(.horizontal, Spacing.xl)
                    .padding(.top, Spacing.xl)
            }

            ScrollView(.horizontal) {
                VStack(alignment: .leading, spacing: 0) {
                    comparisonHeaderRow(columns: columns)
                        .padding(.horizontal, Spacing.xl)
                        .padding(.top, Spacing.md)
                        .padding(.bottom, Spacing.sm)
                    Divider()
                        .padding(.horizontal, Spacing.xl)

                    List {
                        ForEach(rows) { row in
                            comparisonDataRow(row: row, columns: columns)
                                .listRowInsets(EdgeInsets(
                                    top: 0,
                                    leading: Spacing.xl,
                                    bottom: 0,
                                    trailing: Spacing.xl
                                ))
                                .listRowSeparator(.hidden)
                                .listRowBackground(Color.clear)
                        }
                    }
                    .listStyle(.plain)
                    .scrollContentBackground(.hidden)
                    .frame(width: comparisonTableWidth(columns: columns))
                }
                .frame(width: comparisonTableWidth(columns: columns), alignment: .leading)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        }
    }

    private func comparisonHeaderRow(columns: [ComparisonColumn]) -> some View {
        HStack(alignment: .top, spacing: Spacing.lg) {
            Text(t("Item", "Материал"))
                .font(Typography.labelSmall.weight(.semibold))
                .frame(width: titleColumnWidth, alignment: .topLeading)

            ForEach(columns) { column in
                Text(column.name)
                    .font(Typography.labelSmall.weight(.semibold))
                    .frame(width: valueColumnWidth, alignment: .topLeading)
            }
        }
    }

    private func comparisonDataRow(
        row: ComparisonRow,
        columns: [ComparisonColumn]
    ) -> some View {
        HStack(alignment: .top, spacing: Spacing.lg) {
            Text(row.title)
                .font(Typography.bodySmall.weight(.medium))
                .frame(width: titleColumnWidth, alignment: .topLeading)

            ForEach(columns) { column in
                Text(cell(row, column.name))
                    .font(Typography.bodySmall)
                    .foregroundStyle(Palette.textSecondary)
                    .frame(width: valueColumnWidth, alignment: .topLeading)
            }
        }
        .padding(.vertical, Spacing.sm)
        .textSelection(.enabled)
    }

    private func comparisonTableWidth(columns: [ComparisonColumn]) -> CGFloat {
        let cellWidths = titleColumnWidth + CGFloat(columns.count) * valueColumnWidth
        let gaps = CGFloat(columns.count) * Spacing.lg
        return cellWidths + gaps + (Spacing.xl * 2)
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
                loadError = error.userFacingMessage(context: .generic)
                loading = false
                return
            }
            pollCount += 1
            try? await Task.sleep(nanoseconds: 2_000_000_000)
        }
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}
