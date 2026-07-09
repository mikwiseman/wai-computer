import SwiftUI
import WaiComputerKit

/// List of saved comparison sets (forward several items → a comparison table).
struct ComparisonListView: View {
    let apiClient: APIClient

    @EnvironmentObject private var languageManager: LanguageManager
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass
    @State private var entries: [ComparisonListEntry] = []
    @State private var loading = true
    @State private var loadError: String?
    @State private var selectedComparisonId: String?

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }

    private var isRegularWidth: Bool {
        horizontalSizeClass == .regular
    }

    var body: some View {
        Group {
            if loading {
                ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if let loadError {
                VStack(spacing: Spacing.md) {
                    ContentUnavailableViewCompat(
                        t("Couldn't load comparisons", "Не удалось загрузить сравнения"),
                        systemImage: "exclamationmark.triangle",
                        description: Text(loadError)
                    )
                    Button(t("Retry", "Повторить")) {
                        Task { await load() }
                    }
                    .buttonStyle(.bordered)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
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
                comparisonContent
            }
        }
        .navigationTitle(t("Comparisons", "Сравнения"))
        .navigationBarTitleDisplayMode(isRegularWidth ? .inline : .large)
        .accessibilityIdentifier("ios-comparison-list-view")
        .task { await load() }
        .onChange(of: entries.map(\.id)) { _, visibleIds in
            guard let selectedComparisonId, !visibleIds.contains(selectedComparisonId) else { return }
            self.selectedComparisonId = nil
        }
    }

    @ViewBuilder
    private var comparisonContent: some View {
        if isRegularWidth {
            regularComparisonLayout
        } else {
            compactComparisonList
        }
    }

    private var compactComparisonList: some View {
        List(entries) { entry in
            NavigationLink {
                ComparisonDetailView(apiClient: apiClient, comparisonId: entry.id)
            } label: {
                comparisonRow(entry)
            }
        }
        .listStyle(.plain)
    }

    private var regularComparisonLayout: some View {
        HStack(spacing: 0) {
            List(entries) { entry in
                Button {
                    selectedComparisonId = entry.id
                } label: {
                    comparisonRow(entry)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .listRowBackground(selectedComparisonId == entry.id ? Palette.accentSubtle : Color.clear)
                .accessibilityIdentifier("ios-comparison-row-\(entry.id)")
            }
            .listStyle(.plain)
            .scrollContentBackground(.hidden)
            .frame(minWidth: 320, idealWidth: 390, maxWidth: 460, maxHeight: .infinity, alignment: .topLeading)
            .background(Palette.surfaceSubtle)
            .accessibilityIdentifier("ios-comparison-list-pane")

            Divider()

            regularComparisonDetailPane
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                .background(Color(uiColor: .systemGroupedBackground))
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .accessibilityIdentifier("ios-comparison-regular-layout")
    }

    private func comparisonRow(_ entry: ComparisonListEntry) -> some View {
        VStack(alignment: .leading, spacing: Spacing.xxs) {
            Text(entry.title ?? t("Comparison", "Сравнение"))
                .font(Typography.body.weight(.medium))
            Text(t(
                entry.itemCount == 1 ? "1 item" : "\(entry.itemCount) items",
                "\(entry.itemCount) \(RussianPlural.form(entry.itemCount, one: "материал", few: "материала", many: "материалов"))"
            ))
                .font(Typography.labelSmall)
                .foregroundStyle(Palette.textTertiary)
        }
    }

    @ViewBuilder
    private var regularComparisonDetailPane: some View {
        if let id = selectedComparisonId,
           entries.contains(where: { $0.id == id }) {
            ComparisonDetailView(apiClient: apiClient, comparisonId: id)
                .id(id)
                .accessibilityIdentifier("ios-comparison-detail-pane")
        } else {
            regularComparisonPlaceholder
        }
    }

    private var regularComparisonPlaceholder: some View {
        VStack(spacing: Spacing.lg) {
            Image(systemName: "tablecells")
                .font(.system(size: 30, weight: .semibold))
                .foregroundStyle(Palette.accent)
                .frame(width: 64, height: 64)
                .background(Palette.accentSubtle)
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))

            VStack(spacing: Spacing.xxs) {
                Text(t("Select a comparison", "Выберите сравнение"))
                    .font(Typography.displaySmall)
                    .foregroundStyle(Palette.textPrimary)
                    .multilineTextAlignment(.center)
                Text(t(
                    "Review saved comparison tables without leaving the list.",
                    "Просматривайте сохранённые таблицы сравнений, не уходя из списка."
                ))
                .font(Typography.bodySmall)
                .foregroundStyle(Palette.textSecondary)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: 420)
            }
        }
        .padding(Spacing.xl)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .accessibilityIdentifier("ios-comparison-placeholder")
    }

    private func load() async {
        #if DEBUG
            if IOSTestingMode.current.isScreenshot {
                entries = IOSScreenshotFixtures.comparisonListEntries
                loadError = nil
                loading = false
                return
            }
        #endif

        loading = true
        defer { loading = false }
        do {
            entries = try await apiClient.listComparisons()
            loadError = nil
        } catch {
            entries = []
            loadError = error.userFacingMessage(context: .generic)
        }
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
    @State private var loadError: String?

    private let maxPolls = 30
    private let titleColumnWidth: CGFloat = 180
    private let valueColumnWidth: CGFloat = 240
    private let rationaleMaxWidth: CGFloat = 720

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }

    var body: some View {
        content
            .navigationTitle(set?.title ?? t("Comparison", "Сравнение"))
            .navigationBarTitleDisplayMode(.inline)
            .accessibilityIdentifier("ios-comparison-detail-view")
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

    private func comparisonTable(
        columns: [ComparisonColumn],
        rows: [ComparisonRow],
        rationale: String?
    ) -> some View {
        ScrollView(.vertical) {
            ScrollView(.horizontal) {
                VStack(alignment: .leading, spacing: Spacing.md) {
                    if let rationale, !rationale.isEmpty {
                        Text(rationale)
                            .font(Typography.bodySmall)
                            .foregroundStyle(Palette.textSecondary)
                            .frame(maxWidth: rationaleMaxWidth, alignment: .leading)
                    }

                    VStack(alignment: .leading, spacing: 0) {
                        comparisonHeaderRow(columns: columns)
                            .padding(.bottom, Spacing.sm)
                        Divider()
                        ForEach(rows) { row in
                            comparisonDataRow(row: row, columns: columns)
                            Divider()
                        }
                    }
                    .frame(width: comparisonTableWidth(columns: columns), alignment: .topLeading)
                    .accessibilityIdentifier("ios-comparison-table")
                }
                .padding(Spacing.lg)
                .frame(width: comparisonTableWidth(columns: columns) + (Spacing.lg * 2), alignment: .topLeading)
            }
            .defaultScrollAnchor(.topLeading)
            .frame(maxWidth: .infinity, alignment: .topLeading)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
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
        return cellWidths + gaps
    }

    private func cell(_ row: ComparisonRow, _ column: String) -> String {
        if let value = row.values[column], let value { return value }
        return "—"
    }

    private func loadUntilReady() async {
        #if DEBUG
            if IOSTestingMode.current.isScreenshot {
                set = IOSScreenshotFixtures.comparison(id: comparisonId)
                loadError = nil
                loading = false
                return
            }
        #endif

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
            do {
                try await Task.sleep(nanoseconds: 2_000_000_000)
            } catch {
                return
            }
        }
    }
}
