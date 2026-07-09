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

    private var kinds: [(key: String?, label: String)] {
        [
            (nil, t("All", "Все")),
            ("article", t("Articles", "Статьи")),
            ("video", t("Videos", "Видео")),
            ("pdf", t("PDFs", "PDF")),
            ("note", t("Notes", "Заметки")),
            ("mcp_resource", t("Connected", "Подключённые")),
        ]
    }

    private var importTypes: [UTType] {
        // Documents extract inline into an Item; audio/video are transcribed into
        // a Recording. `.audio`/`.movie` cover the common cases; the explicit
        // extensions catch containers that don't conform to them (mkv/webm/opus).
        var types: [UTType] = [.pdf, .plainText, .audio, .movie]
        for ext in ["md", "mkv", "webm", "opus", "ogg"] {
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
            .help(t("Attach a PDF or text file", "Прикрепить PDF или текстовый файл"))

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
            InlineStatusBanner(
                systemImage: "exclamationmark.triangle.fill",
                message: message,
                color: Palette.danger,
                autoDismissAfter: nil,
                onDismiss: {
                    withAnimation(.easeInOut(duration: 0.2)) { model.errorMessage = nil }
                }
            )
        }
    }

    @ViewBuilder
    private var statusBanner: some View {
        if let message = model.statusMessage {
            InlineStatusBanner(
                systemImage: "checkmark.circle.fill",
                message: message,
                color: Palette.success,
                autoDismissAfter: InlineStatusBanner.statusDismissDelay,
                onDismiss: {
                    withAnimation(.easeInOut(duration: 0.2)) { model.statusMessage = nil }
                }
            )
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
                List {
                    ForEach(model.entries) { entry in
                        contentRow(entry)
                            .contentShape(Rectangle())
                            .onTapGesture {
                                model.selectedId = entry.id
                                Task { await model.selectItem(entry.id) }
                            }
                    }
                }
                .listStyle(.inset)
            }
        }
    }

    private func contentRow(_ entry: ItemListEntry) -> some View {
        HStack(alignment: .top, spacing: Spacing.sm) {
            VStack(alignment: .leading, spacing: Spacing.xxs) {
                Text(entry.title ?? entry.url ?? t("Untitled", "Без названия"))
                    .font(Typography.bodySmall.weight(.medium))
                    .lineLimit(2)
                HStack(spacing: Spacing.xs) {
                    Text(entry.kind.uppercased())
                        .font(Typography.labelSmall)
                        .foregroundStyle(Palette.textTertiary)
                    if entry.status == "failed" {
                        Text(t("failed", "ошибка"))
                            .font(Typography.labelSmall)
                            .foregroundStyle(Palette.recording)
                    } else if entry.status == "needs_input" {
                        Text(t("needs input", "нужны данные"))
                            .font(Typography.labelSmall)
                            .foregroundStyle(Palette.recording)
                    } else if !entry.hasSummary {
                        Text(t("summarizing…", "обработка…"))
                            .font(Typography.labelSmall)
                            .foregroundStyle(Palette.textSecondary)
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
        if let item = model.selectedItem, item.id == model.selectedId {
            MacItemDetailView(
                item: item,
                onDelete: {
                    Task { await model.deleteSelected() }
                },
                isGeneratingSummaryAudio: model.isGeneratingSummaryAudio(for: item.id) ||
                    item.summaryAudio?.isActive == true,
                isDownloadingSummaryAudio: model.isDownloadingSummaryAudio(for: item.id),
                isPlayingSummaryAudio: model.isPlayingSummaryAudio(for: item.id),
                onGenerateSummaryAudio: {
                    Task { await model.startSummaryAudioGeneration(itemId: item.id) }
                },
                onPlaySummaryAudio: {
                    Task { await model.playOrStopSummaryAudio(itemId: item.id) }
                }
            )
        } else if model.selectedId != nil {
            // Selection changed but the item is still loading — never show the
            // previous item's content under the new selection.
            ProgressView()
                .frame(maxWidth: .infinity, maxHeight: .infinity)
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
