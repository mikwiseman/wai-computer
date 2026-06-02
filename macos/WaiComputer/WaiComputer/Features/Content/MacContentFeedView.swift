import SwiftUI
import UniformTypeIdentifiers
import WaiComputerKit

/// The unified "Content" surface on macOS: add anything (link/text) + a
/// filterable feed of non-recording items, with a detail pane showing the
/// summary + key-moments table. Mirrors the web Content view.
struct MacContentFeedView: View {
    let apiClient: APIClient

    @EnvironmentObject private var languageManager: LanguageManager
    @StateObject private var model: MacContentFeedViewModel
    @State private var showingImporter = false

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
        ("document", "Docs"),
        ("presentation", "Slides"),
        ("spreadsheet", "Sheets"),
        ("mcp_resource", "Connected"),
    ]

    private var importTypes: [UTType] {
        // Documents extract inline into an Item; audio/video are transcribed into
        // a Recording. `.audio`/`.movie` cover the common cases; the explicit
        // extensions catch containers that don't conform to them (mkv/webm/opus).
        var types: [UTType] = [
            .pdf, .plainText, .html, .rtf, .commaSeparatedText, .json, .audio, .movie
        ]
        for ext in [
            "md", "doc", "docx", "pptx", "xlsx",
            "mkv", "webm", "opus", "ogg"
        ] {
            if let t = UTType(filenameExtension: ext) { types.append(t) }
        }
        return types
    }

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            addAnythingBar
            errorBanner
            statusBanner
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
        .dropDestination(for: URL.self) { urls, _ in
            guard let url = urls.first else { return false }
            Task { await model.uploadFile(url) }
            return true
        }
        .fileImporter(
            isPresented: $showingImporter,
            allowedContentTypes: importTypes,
            allowsMultipleSelection: false
        ) { result in
            if case let .success(urls) = result, let url = urls.first {
                Task { await model.uploadFile(url) }
            }
        }
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
                showingImporter = true
            } label: {
                Image(systemName: "paperclip")
            }
            .buttonStyle(.bordered)
            .disabled(model.isAdding)
            .help(t("Attach a document, audio, or video file",
                    "Прикрепить документ, аудио или видео"))

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

    @ViewBuilder
    private var statusBanner: some View {
        if let message = model.statusMessage {
            HStack(spacing: Spacing.xs) {
                Image(systemName: "checkmark.circle.fill")
                    .foregroundStyle(.green)
                Text(message)
                    .font(Typography.bodySmall)
                    .foregroundStyle(.secondary)
                    .textSelection(.enabled)
                Spacer()
                Button {
                    model.statusMessage = nil
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
                Text(displayTitle(title: entry.title, url: entry.url))
                    .font(Typography.bodySmall.weight(.medium))
                    .lineLimit(2)
                HStack(spacing: Spacing.xs) {
                    Text(kindLabel(entry.kind))
                        .font(Typography.labelSmall)
                        .foregroundStyle(Palette.textTertiary)
                    if let label = statusLabel(entry.status) {
                        Text(label)
                            .font(Typography.labelSmall)
                            .foregroundStyle(statusColor(entry.status))
                            .help(entry.error?.message ?? "")
                    }
                }
            }
        }
        .padding(.vertical, Spacing.xxs)
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }

    private func displayTitle(title: String?, url: String?) -> String {
        let trimmed = (title ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        if !isPlaceholderTitle(trimmed) {
            return trimmed
        }
        return url ?? t("Untitled", "Без названия")
    }

    private func isPlaceholderTitle(_ value: String) -> Bool {
        let normalized = value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return normalized.isEmpty
            || normalized == "untitled"
            || normalized == "[untitled]"
            || normalized == "без названия"
            || normalized == "[без названия]"
    }

    private func kindLabel(_ kind: String) -> String {
        switch kind {
        case "pdf": return "PDF"
        case "doc", "docx", "document": return t("DOC", "ДОК")
        case "presentation": return t("SLIDES", "СЛАЙДЫ")
        case "spreadsheet": return t("SHEET", "ТАБЛИЦА")
        default: return kind.uppercased()
        }
    }

    private func statusLabel(_ status: String) -> String? {
        switch status {
        case "fetching": return t("fetching…", "загрузка…")
        case "summarizing": return t("summarizing…", "обработка…")
        case "needs_input": return t("needs input", "нужен текст")
        case "failed": return t("failed", "ошибка")
        default: return nil
        }
    }

    private func statusColor(_ status: String) -> Color {
        switch status {
        case "needs_input", "failed": return .red
        default: return Palette.accent
        }
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
