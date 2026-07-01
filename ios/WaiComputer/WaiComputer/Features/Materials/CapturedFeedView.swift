import SwiftUI
import WaiComputerKit

/// The captured-items feed (links, notes, files) — the Materials tab's main
/// list. Includes the multi-select → Compare flow.
struct CapturedFeedView: View {
    @EnvironmentObject private var languageManager: LanguageManager
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass
    @ObservedObject var model: ContentFeedViewModel
    let folders: [Folder]
    let onFolderContentChanged: (() async -> Void)?
    let selectedMaterialId: Binding<String?>?
    @State private var draft = ""
    @State private var showAdd = false
    @State private var showFileImporter = false
    @State private var comparisonRoute: ComparisonRoute?

    private struct ComparisonRoute: Identifiable, Hashable { let id: String }

    init(
        model: ContentFeedViewModel,
        folders: [Folder] = [],
        onFolderContentChanged: (() async -> Void)? = nil,
        selectedMaterialId: Binding<String?>? = nil
    ) {
        _model = ObservedObject(wrappedValue: model)
        self.folders = folders
        self.onFolderContentChanged = onFolderContentChanged
        self.selectedMaterialId = selectedMaterialId
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }

    var body: some View {
        List {
            inlineCapturePanel
                .listRowInsets(EdgeInsets())
                .listRowSeparator(.hidden)
                .listRowBackground(Color.clear)

            if model.entries.isEmpty {
                emptyState
                    .listRowInsets(EdgeInsets())
                    .listRowSeparator(.hidden)
                    .listRowBackground(Color.clear)
            } else {
                ForEach(model.entries) { entry in
                    if model.isSelecting {
                        Button { model.toggleCompare(entry.id) } label: {
                            HStack(spacing: Spacing.sm) {
                                Image(systemName: model.compareSelection.contains(entry.id) ? "checkmark.circle.fill" : "circle")
                                    .foregroundStyle(model.compareSelection.contains(entry.id) ? Palette.accent : Palette.textTertiary)
                                row(entry)
                            }
                        }
                        .buttonStyle(.plain)
                    } else {
                        entryRow(entry)
                            .draggable(IOSInboxDragItem(kind: .item, id: entry.id))
                            .contextMenu {
                                itemContextMenu(for: entry)
                            }
                            .swipeActions(edge: .leading) {
                                if entry.folderId != nil {
                                    Button {
                                        Task { await moveItem(entry.id, to: nil) }
                                    } label: {
                                        Label(t("Unfiled", "Без папки"), systemImage: "tray")
                                    }
                                    .tint(.blue)
                                }
                            }
                    }
                }
                .onDelete { offsets in
                    let ids = offsets.map { model.entries[$0].id }
                    Task {
                        if let selected = selectedMaterialId?.wrappedValue, ids.contains(selected) {
                            selectedMaterialId?.wrappedValue = nil
                        }
                        for id in ids {
                            await model.delete(id)
                        }
                        await refreshFolderContent()
                    }
                }
            }
        }
        .listStyle(.plain)
        .scrollContentBackground(.hidden)
        .background(Color(uiColor: .systemGroupedBackground))
        .navigationTitle(t("Materials", "Материалы"))
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarLeading) {
                if !model.entries.isEmpty {
                    Button(model.isSelecting ? t("Done", "Готово") : t("Select", "Выбрать")) {
                        model.toggleSelecting()
                    }
                }
            }
            ToolbarItemGroup(placement: .topBarTrailing) {
                if model.isSelecting {
                    Button {
                        Task {
                            await model.compareSelected()
                            if let id = model.createdComparisonId {
                                comparisonRoute = ComparisonRoute(id: id)
                                model.createdComparisonId = nil
                            }
                        }
                    } label: {
                        Text(model.isComparing
                             ? t("Comparing…", "Сравниваю…")
                             : t("Compare (\(model.compareSelection.count))", "Сравнить (\(model.compareSelection.count))"))
                    }
                    .disabled(!model.canCompare || model.isComparing)
                } else {
                    Menu {
                        Button {
                            showAdd = true
                        } label: {
                            Label(t("Paste Link or Text", "Вставить ссылку или текст"), systemImage: "doc.text")
                        }

                        Button {
                            showFileImporter = true
                        } label: {
                            Label(t("Upload File", "Загрузить файл"), systemImage: "paperclip")
                        }
                    } label: {
                        Label(t("Add", "Добавить"), systemImage: "plus")
                    }
                    .disabled(model.isAdding || model.isUploadingFile)
                    .accessibilityIdentifier("materials-add-menu")
                }
            }
        }
        .navigationDestination(item: $comparisonRoute) { route in
            ComparisonDetailView(apiClient: model.apiClient, comparisonId: route.id)
        }
        .sheet(isPresented: $showAdd) {
            AddAnythingSheet(isPresented: $showAdd, isAdding: model.isAdding) { text in
                Task {
                    if await model.add(text) != nil {
                        showAdd = false
                        await refreshFolderContent()
                    }
                }
            }
        }
        .fileImporter(
            isPresented: $showFileImporter,
            allowedContentTypes: ContentFeedViewModel.importContentTypes,
            allowsMultipleSelection: false
        ) { result in
            switch result {
            case .success(let urls):
                guard let url = urls.first else { return }
                Task {
                    if await model.uploadFile(url) != nil {
                        await refreshFolderContent()
                    }
                }
            case .failure(let error):
                model.errorMessage = error.localizedDescription
            }
        }
        .refreshable { await loadFeed() }
        .task { await loadFeed() }
        .overlay(alignment: .bottom) {
            VStack(spacing: Spacing.xs) {
                if model.isUploadingFile {
                    Text(t("Uploading file...", "Загружаем файл..."))
                        .font(Typography.bodySmall)
                        .foregroundStyle(.white)
                        .padding(Spacing.sm)
                        .background(Palette.accent, in: Capsule())
                } else if let status = model.statusMessage {
                    Button {
                        model.statusMessage = nil
                    } label: {
                        Text(status)
                            .font(Typography.bodySmall)
                            .foregroundStyle(.white)
                            .padding(Spacing.sm)
                            .background(.green, in: Capsule())
                    }
                    .buttonStyle(.plain)
                }

                if let error = model.errorMessage {
                    Text(error)
                        .font(Typography.bodySmall)
                        .foregroundStyle(.white)
                        .padding(Spacing.sm)
                        .background(.red, in: Capsule())
                }
            }
            .padding(.bottom, Spacing.md)
        }
    }

    private var isRegularSplitPane: Bool {
        selectedMaterialId != nil && horizontalSizeClass == .regular
    }

    @ViewBuilder
    private var inlineCapturePanel: some View {
        if isRegularSplitPane {
            regularCapturePanel
        } else {
            compactCapturePanel
        }
    }

    private var regularCapturePanel: some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            HStack(alignment: .center, spacing: Spacing.sm) {
                Label {
                    Text(t("Capture", "Добавить"))
                        .font(Typography.label)
                } icon: {
                    Image(systemName: "tray.and.arrow.down")
                }
                .foregroundStyle(Palette.textSecondary)

                Spacer(minLength: Spacing.sm)

                captureActions
            }

            captureDraftField(minHeight: 72)

            filterChips
                .padding(.top, Spacing.xxs)
        }
        .padding(Spacing.md)
        .background(Palette.surfaceSubtle)
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(Palette.border, lineWidth: 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        .padding(.horizontal, Spacing.md)
        .padding(.top, Spacing.md)
        .accessibilityIdentifier("materials-regular-capture-panel")
    }

    private var compactCapturePanel: some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            HStack(alignment: .bottom, spacing: Spacing.sm) {
                captureDraftField(minHeight: 44)

                uploadIconButton
                addIconButton
            }

            filterChips
        }
        .padding(Spacing.md)
        .background(Palette.surfaceSubtle)
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(Palette.border, lineWidth: 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        .padding(.horizontal, Spacing.md)
        .padding(.top, Spacing.md)
        .accessibilityIdentifier("materials-compact-capture-panel")
    }

    private var captureActions: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: Spacing.xs) {
                uploadIconButton
                addIconButton
            }

            VStack(spacing: Spacing.xs) {
                uploadIconButton
                addIconButton
            }
        }
        .accessibilityIdentifier("materials-capture-actions")
    }

    private func captureDraftField(minHeight: CGFloat) -> some View {
        TextField(
            t("Paste a link or any text...", "Вставьте ссылку или любой текст..."),
            text: $draft,
            axis: .vertical
        )
        .textFieldStyle(.plain)
        .font(Typography.body)
        .lineLimit(1...4)
        .submitLabel(.done)
        .onSubmit { submitDraft() }
        .padding(Spacing.sm)
        .frame(minHeight: minHeight, alignment: .topLeading)
        .background(Palette.surfaceHover)
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(Palette.border, lineWidth: 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        .accessibilityIdentifier("materials-inline-draft-field")
    }

    private var uploadIconButton: some View {
        Button {
            showFileImporter = true
        } label: {
            Image(systemName: "paperclip")
                .frame(width: 20, height: 20)
        }
        .buttonStyle(.bordered)
        .disabled(model.isAdding || model.isUploadingFile)
        .accessibilityLabel(t("Upload File", "Загрузить файл"))
        .accessibilityIdentifier("materials-inline-upload-button")
    }

    private var addIconButton: some View {
        Button {
            submitDraft()
        } label: {
            if model.isAdding {
                ProgressView()
                    .controlSize(.small)
                    .frame(width: 20, height: 20)
            } else {
                Image(systemName: "plus")
                    .frame(width: 20, height: 20)
            }
        }
        .buttonStyle(.borderedProminent)
        .disabled(trimmedDraft.isEmpty || model.isAdding || model.isUploadingFile)
        .accessibilityLabel(t("Add", "Добавить"))
        .accessibilityIdentifier("materials-inline-add-button")
    }

    private var filterChips: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: Spacing.xs) {
                ForEach(CapturedFeedKindFilter.all) { filter in
                    Button {
                        Task { await model.setKind(filter.kind) }
                    } label: {
                        Text(filter.title(language: languageManager.current))
                            .font(Typography.label)
                            .foregroundStyle(model.kind == filter.kind ? Palette.accent : Palette.textSecondary)
                            .padding(.horizontal, Spacing.sm)
                            .padding(.vertical, Spacing.xxs)
                    }
                    .buttonStyle(.plain)
                    .background(
                        Capsule()
                            .fill(model.kind == filter.kind ? Palette.accentSubtle : Color.clear)
                    )
                    .overlay(
                        Capsule()
                            .stroke(model.kind == filter.kind ? Color.clear : Palette.border, lineWidth: 1)
                    )
                    .accessibilityIdentifier("materials-kind-filter-\(filter.id)")
                }
            }
            .padding(.horizontal, Spacing.md)
        }
        .padding(.horizontal, -Spacing.md)
        .accessibilityIdentifier("materials-kind-filter-chips")
    }

    private var emptyState: some View {
        VStack(spacing: Spacing.lg) {
            Image(systemName: "doc.text")
                .font(.system(size: 30, weight: .semibold))
                .foregroundStyle(Palette.accent)
                .frame(width: 62, height: 62)
                .background(Palette.accentSubtle)
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))

            VStack(spacing: Spacing.xs) {
                Text(t("Nothing here yet", "Пока пусто"))
                    .font(Typography.displaySmall)
                    .foregroundStyle(Palette.textPrimary)
                Text(emptyStateMessage)
                    .font(Typography.bodySmall)
                    .foregroundStyle(Palette.textSecondary)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
            }

            HStack(spacing: Spacing.sm) {
                Button {
                    showAdd = true
                } label: {
                    Label(t("Paste Link or Text", "Вставить ссылку или текст"), systemImage: "doc.text")
                }
                .buttonStyle(.borderedProminent)
                .tint(Palette.accent)

                Button {
                    showFileImporter = true
                } label: {
                    Label(t("Upload File", "Загрузить файл"), systemImage: "paperclip")
                }
                .buttonStyle(.bordered)
            }
        }
        .padding(Spacing.xl)
        .frame(maxWidth: .infinity)
        .accessibilityIdentifier("materials-empty-state")
    }

    private func row(_ entry: ItemListEntry) -> some View {
        VStack(alignment: .leading, spacing: Spacing.xxs) {
            Text(entry.title ?? entry.url ?? t("Untitled", "Без названия"))
                .font(Typography.body.weight(.medium))
                .foregroundStyle(Palette.textPrimary)
                .lineLimit(2)
            HStack(spacing: Spacing.xs) {
                Text(entry.kind.uppercased())
                    .font(Typography.labelSmall)
                    .foregroundStyle(Palette.accent)
                if let status = statusLabel(for: entry) {
                    Text(status)
                        .font(Typography.labelSmall)
                        .foregroundStyle(statusColor(for: entry))
                }
            }
        }
        .padding(.vertical, Spacing.xxs)
    }

    @ViewBuilder
    private func entryRow(_ entry: ItemListEntry) -> some View {
        if selectedMaterialId != nil {
            Button {
                selectedMaterialId?.wrappedValue = entry.id
            } label: {
                row(entry)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .listRowBackground(selectedMaterialId?.wrappedValue == entry.id ? Palette.accentSubtle : Color.clear)
        } else {
            NavigationLink {
                ItemDetailView(itemId: entry.id, apiClient: model.apiClient) {
                    Task { await loadFeed() }
                }
            } label: {
                row(entry)
            }
        }
    }

    @ViewBuilder
    private func itemContextMenu(for entry: ItemListEntry) -> some View {
        if entry.folderId != nil || !folders.isEmpty {
            Menu(t("Move to Folder", "Переместить в папку")) {
                if entry.folderId != nil {
                    Button(t("Remove from Folder", "Убрать из папки")) {
                        Task { await moveItem(entry.id, to: nil) }
                    }
                }

                ForEach(folders) { folder in
                    if folder.id != entry.folderId {
                        Button(folder.name) {
                            Task { await moveItem(entry.id, to: folder.id) }
                        }
                    }
                }
            }
        }

        Button(t("Delete", "Удалить"), role: .destructive) {
            Task {
                if selectedMaterialId?.wrappedValue == entry.id {
                    selectedMaterialId?.wrappedValue = nil
                }
                await model.delete(entry.id)
                await refreshFolderContent()
            }
        }
    }

    private var trimmedDraft: String {
        draft.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private var emptyStateMessage: String {
        if model.kind != nil {
            return t(
                "Try another filter, paste text above, or upload a file.",
                "Выберите другой фильтр, вставьте текст выше или загрузите файл."
            )
        }
        return t(
            "Paste a link or text above, or upload a file.",
            "Вставьте ссылку или текст выше либо загрузите файл."
        )
    }

    private func submitDraft() {
        let text = trimmedDraft
        guard !text.isEmpty, !model.isAdding, !model.isUploadingFile else { return }
        Task {
            if await model.add(text) != nil {
                draft = ""
                await refreshFolderContent()
            }
        }
    }

    private func statusLabel(for entry: ItemListEntry) -> String? {
        if entry.status == "failed" {
            return t("failed", "ошибка")
        }
        if entry.status == "needs_input" {
            return t("needs input", "нужны данные")
        }
        if !entry.hasSummary {
            return t("summarizing...", "конспект...")
        }
        return nil
    }

    private func statusColor(for entry: ItemListEntry) -> Color {
        if entry.status == "failed" || entry.status == "needs_input" {
            return .red
        }
        return Palette.textTertiary
    }

    private func loadFeed() async {
        #if DEBUG
        if IOSTestingMode.current.isScreenshot {
            model.loadScreenshotFixtures()
            return
        }
        #endif
        await model.load()
    }

    private func moveItem(_ id: String, to folderId: String?) async {
        guard await model.moveItem(id, to: folderId) else { return }
        await refreshFolderContent()
    }

    private func refreshFolderContent() async {
        if let onFolderContentChanged {
            await onFolderContentChanged()
        }
    }
}

private struct CapturedFeedKindFilter: Identifiable, Equatable {
    let kind: String?
    let englishTitle: String
    let russianTitle: String

    var id: String { kind ?? "all" }

    static let all: [CapturedFeedKindFilter] = [
        .init(kind: nil, englishTitle: "All", russianTitle: "Все"),
        .init(kind: "article", englishTitle: "Articles", russianTitle: "Статьи"),
        .init(kind: "video", englishTitle: "Videos", russianTitle: "Видео"),
        .init(kind: "pdf", englishTitle: "PDFs", russianTitle: "PDF"),
        .init(kind: "note", englishTitle: "Notes", russianTitle: "Заметки"),
        .init(kind: "mcp_resource", englishTitle: "Connected", russianTitle: "Подключенные"),
    ]

    func title(language: LanguageManager.SupportedLanguage) -> String {
        OnboardingL10n.text(englishTitle, russianTitle, language: language)
    }
}
