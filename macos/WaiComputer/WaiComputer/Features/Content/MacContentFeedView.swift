import SwiftUI
import WaiComputerKit

/// The unified "Content" surface on macOS: add anything (link/text) + a
/// filterable feed of non-recording items, with a detail pane showing the
/// summary + key-moments table. Mirrors the web Content view.
struct MacContentFeedView: View {
    let apiClient: APIClient

    @EnvironmentObject private var languageManager: LanguageManager
    @StateObject private var model: MacContentFeedViewModel

    init(apiClient: APIClient) {
        self.apiClient = apiClient
        _model = StateObject(wrappedValue: MacContentFeedViewModel(apiClient: apiClient))
    }

    private let kinds: [(key: String?, label: String)] = [
        (nil, "All"),
        ("article", "Articles"),
        ("video", "Videos"),
        ("pdf", "PDFs"),
        ("note", "Notes"),
        ("mcp_resource", "Connected"),
    ]

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            addAnythingBar
            errorBanner
            Divider()
            filterChips
            Divider()
            HStack(spacing: 0) {
                listColumn
                    .frame(minWidth: 240, maxWidth: 340)
                Divider()
                detailColumn
                    .frame(maxWidth: .infinity)
            }
        }
        .task { await model.load() }
        .sheet(isPresented: Binding(
            get: { model.activeComparisonId != nil },
            set: { if !$0 { model.clearComparison() } }
        )) {
            if let comparisonId = model.activeComparisonId {
                MacComparisonView(
                    apiClient: model.apiClient,
                    comparisonId: comparisonId,
                    onClose: { model.clearComparison() }
                )
                .frame(minWidth: 640, minHeight: 480)
            }
        }
    }

    private var header: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: Spacing.xs) {
                Text(t("Content", "Материалы"))
                    .font(Typography.displaySmall)
                Text(t("Everything you've added — articles, links, notes, connected sources.",
                       "Всё, что вы добавили — статьи, ссылки, заметки, подключённые источники."))
                    .font(Typography.bodySmall)
                    .foregroundStyle(Palette.textSecondary)
            }
            Spacer()
        }
        .padding(Spacing.xl)
    }

    private var addAnythingBar: some View {
        HStack(spacing: Spacing.sm) {
            TextField(
                t("Paste a link or any text…", "Вставьте ссылку или текст…"),
                text: $model.draft,
                axis: .vertical
            )
            .textFieldStyle(.plain)
            .font(Typography.body)
            .lineLimit(1...4)
            .onSubmit { Task { await model.addDraft() } }

            Button {
                Task { await model.addDraft() }
            } label: {
                if model.isAdding {
                    ProgressView().controlSize(.small)
                } else {
                    Text(t("Add", "Добавить"))
                }
            }
            .buttonStyle(.borderedProminent)
            .disabled(model.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || model.isAdding)
        }
        .padding(.horizontal, Spacing.xl)
        .padding(.vertical, Spacing.md)
    }

    @ViewBuilder
    private var errorBanner: some View {
        if let message = model.errorMessage {
            HStack(spacing: Spacing.xs) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .foregroundStyle(.red)
                Text(message)
                    .font(Typography.bodySmall)
                    .foregroundStyle(.red)
                    .textSelection(.enabled)
                Spacer()
                Button {
                    model.errorMessage = nil
                } label: {
                    Image(systemName: "xmark")
                }
                .buttonStyle(.plain)
                .help(t("Dismiss", "Закрыть"))
            }
            .padding(.horizontal, Spacing.xl)
            .padding(.vertical, Spacing.sm)
            .background(Palette.surfaceSubtle)
        }
    }

    private var filterChips: some View {
        HStack(spacing: Spacing.xs) {
            ForEach(kinds, id: \.label) { kind in
                Button {
                    Task { await model.setKind(kind.key) }
                } label: {
                    Text(kind.label)
                        .font(Typography.label)
                        .padding(.horizontal, Spacing.sm)
                        .padding(.vertical, Spacing.xxs)
                }
                .buttonStyle(.plain)
                .background(
                    Capsule().fill(model.kind == kind.key ? Palette.accentSubtle : Color.clear)
                )
                .overlay(
                    Capsule().stroke(Palette.border, lineWidth: model.kind == kind.key ? 0 : 1)
                )
            }
            Spacer()
            if model.canCompare {
                Button {
                    Task { await model.compareSelected() }
                } label: {
                    if model.isComparing {
                        ProgressView().controlSize(.small)
                    } else {
                        Label(
                            t("Compare (\(model.compareSelection.count))",
                              "Сравнить (\(model.compareSelection.count))"),
                            systemImage: "tablecells"
                        )
                    }
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.small)
            }
        }
        .padding(.horizontal, Spacing.xl)
        .padding(.vertical, Spacing.sm)
    }

    private var listColumn: some View {
        Group {
            if model.isLoading {
                ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if model.entries.isEmpty {
                ContentUnavailableViewCompat(
                    t("Nothing here yet", "Пока пусто"),
                    systemImage: "tray",
                    description: Text(t("Add a link or text above, or connect a source.",
                                        "Добавьте ссылку или текст выше, либо подключите источник."))
                )
            } else {
                List(selection: Binding(
                    get: { model.selectedId },
                    set: { newValue in
                        model.selectedId = newValue
                        if let newValue {
                            Task { await model.selectItem(newValue) }
                        } else {
                            model.selectedItem = nil
                        }
                    }
                )) {
                    ForEach(model.entries) { entry in
                        contentRow(entry).tag(entry.id)
                    }
                }
                .listStyle(.inset)
            }
        }
    }

    private func contentRow(_ entry: ItemListEntry) -> some View {
        HStack(alignment: .top, spacing: Spacing.sm) {
            Button {
                model.toggleCompare(entry.id)
            } label: {
                Image(systemName: model.compareSelection.contains(entry.id)
                      ? "checkmark.circle.fill" : "circle")
                    .foregroundStyle(model.compareSelection.contains(entry.id)
                                     ? Palette.accent : Palette.textTertiary)
            }
            .buttonStyle(.plain)
            .help(t("Select to compare", "Выбрать для сравнения"))

            VStack(alignment: .leading, spacing: Spacing.xxs) {
                Text(entry.title ?? entry.url ?? t("Untitled", "Без названия"))
                    .font(Typography.bodySmall.weight(.medium))
                    .lineLimit(2)
                HStack(spacing: Spacing.xs) {
                    Text(entry.kind.uppercased())
                        .font(Typography.labelSmall)
                        .foregroundStyle(Palette.textTertiary)
                    if !entry.hasSummary {
                        Text(t("summarizing…", "обработка…"))
                            .font(Typography.labelSmall)
                            .foregroundStyle(Palette.accent)
                    }
                }
            }
        }
        .padding(.vertical, Spacing.xxs)
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }

    @ViewBuilder
    private var detailColumn: some View {
        if let item = model.selectedItem {
            MacItemDetailView(item: item, onDelete: {
                Task { await model.deleteSelected() }
            })
        } else {
            ContentUnavailableViewCompat(
                t("Select an item", "Выберите материал"),
                systemImage: "doc.text.magnifyingglass",
                description: Text(t("See its summary and key moments.",
                                    "Посмотрите краткое содержание и ключевые моменты."))
            )
        }
    }
}
