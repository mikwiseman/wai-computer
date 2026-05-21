import AppKit
import SwiftUI
import WaiComputerKit

struct MacRecordingDetailView: View {
    enum Mode {
        case active
        case trash
    }

    let recordingId: String
    let mode: Mode
    let folders: [Folder]
    var onDelete: (() -> Void)?
    var onRestore: (() -> Void)?
    var onMoveToFolder: ((String?) -> Void)?
    var onDidRename: (() -> Void)?
    @Binding var pendingTitleEditId: String?
    @EnvironmentObject var appState: MacAppState
    @EnvironmentObject private var languageManager: LanguageManager
    @StateObject private var viewModel: MacRecordingDetailViewModel
    @State private var showDeleteConfirmation = false
    @State private var loadTask: Task<Void, Never>?
    @State private var copiedSection: String?
    @State private var isSharing = false
    @State private var pendingSharePayload: SharePickerPayload?
    @State private var isEditingTitle = false
    @State private var titleDraft = ""
    @FocusState private var titleFieldFocused: Bool

    init(
        recordingId: String,
        initialDetail: RecordingDetail? = nil,
        mode: Mode = .active,
        folders: [Folder] = [],
        pendingTitleEditId: Binding<String?> = .constant(nil),
        onDelete: (() -> Void)? = nil,
        onRestore: (() -> Void)? = nil,
        onMoveToFolder: ((String?) -> Void)? = nil,
        onDidRename: (() -> Void)? = nil
    ) {
        self.recordingId = recordingId
        self.mode = mode
        self.folders = folders
        self.onDelete = onDelete
        self.onRestore = onRestore
        self.onMoveToFolder = onMoveToFolder
        self.onDidRename = onDidRename
        _pendingTitleEditId = pendingTitleEditId
        _viewModel = StateObject(wrappedValue: MacRecordingDetailViewModel(initialDetail: initialDetail))
    }

    var body: some View {
        Group {
            if viewModel.isLoading {
                ProgressView(t("Loading...", "Загрузка..."))
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if let error = viewModel.error {
                ContentUnavailableView(
                    t("Error", "Ошибка"),
                    systemImage: "exclamationmark.triangle",
                    description: Text(error)
                )
            } else if let detail = viewModel.recordingDetail {
                VStack(spacing: 0) {
                    detailHeader(detail)

                    WaiDivider()

                    WaiTabBar(
                        tabs: [
                            (t("Transcript", "Транскрипт"), MacRecordingDetailViewModel.Tab.transcript),
                            (t("Summary", "Сводка"), MacRecordingDetailViewModel.Tab.summary),
                        ],
                        selection: $viewModel.selectedTab
                    )

                    WaiDivider()

                    switch viewModel.selectedTab {
                    case .transcript:
                        MacTranscriptView(
                            segments: detail.segments,
                            status: detail.status,
                            recordingId: detail.id,
                            onAssigned: { updated in
                                viewModel.recordingDetail = updated
                            }
                        )
                    case .summary:
                        summaryTab(detail)
                    }
                }
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier("recording-detail-root")
                .background(
                    SharePickerPresenter(payload: $pendingSharePayload)
                        .frame(width: 0, height: 0)
                )
            } else {
                ContentUnavailableView(
                    t("Recording Not Found", "Запись не найдена"),
                    systemImage: "doc.questionmark",
                    description: Text(t("Unable to load this recording.", "Не удалось загрузить эту запись."))
                )
            }
        }
        .onAppear {
            loadTask?.cancel()
            loadTask = Task {
                await loadRecordingDetail(
                    recordingId: recordingId,
                    showLoading: viewModel.recordingDetail?.id != recordingId
                )
            }
        }
        .onDisappear {
            loadTask?.cancel()
        }
        .onChange(of: recordingId) { _, newId in
            loadTask?.cancel()
            loadTask = Task {
                await loadRecordingDetail(
                    recordingId: newId,
                    showLoading: viewModel.recordingDetail?.id != newId
                )
            }
        }
        .task(id: detailRefreshKey) {
            await viewModel.refreshPendingDetailIfNeeded(
                recordingId: recordingId,
                apiClient: appState.getAPIClient(),
                fixtureDetail: { await appState.uiTestRecordingDetail(id: recordingId) }
            )
        }
        .onReceive(NotificationCenter.default.publisher(for: .pendingRecordingSyncDidFinish)) { notification in
            guard let syncedRecordingId = notification.userInfo?["recordingId"] as? String,
                  syncedRecordingId == recordingId else {
                return
            }
            loadTask?.cancel()
            loadTask = Task {
                await loadRecordingDetail(recordingId: recordingId, showLoading: false)
            }
        }
        .onChange(of: pendingTitleEditId) { _, requested in
            guard let requested, requested == recordingId, mode == .active else { return }
            startTitleEdit(currentTitle: viewModel.recordingDetail?.title)
            pendingTitleEditId = nil
        }
    }

    private func startTitleEdit(currentTitle: String?) {
        titleDraft = currentTitle ?? ""
        isEditingTitle = true
        DispatchQueue.main.async {
            titleFieldFocused = true
        }
    }

    private func loadRecordingDetail(recordingId: String, showLoading: Bool) async {
        await viewModel.load(
            recordingId: recordingId,
            apiClient: appState.getAPIClient(),
            fixtureDetail: { await appState.uiTestRecordingDetail(id: recordingId) },
            showLoading: showLoading
        )
    }

    private func commitTitleEdit(originalTitle: String?) {
        let trimmed = titleDraft.trimmingCharacters(in: .whitespacesAndNewlines)
        defer { isEditingTitle = false }
        guard !trimmed.isEmpty, trimmed != (originalTitle ?? "") else { return }
        Task {
            let success = await viewModel.renameRecording(trimmed, apiClient: appState.getAPIClient())
            if success {
                onDidRename?()
            }
        }
    }

    private var detailRefreshKey: String {
        let status = viewModel.recordingDetail?.status.rawValue ?? "none"
        return "\(recordingId)-\(status)"
    }

    private func copyToClipboard(_ text: String, section: String) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
        copiedSection = section
        Task {
            try? await Task.sleep(for: .seconds(1.5))
            if copiedSection == section {
                copiedSection = nil
            }
        }
    }

    private func copyActionButton(
        title: String,
        copiedTitle: String,
        text: String,
        section: String
    ) -> some View {
        Button {
            copyToClipboard(text, section: section)
        } label: {
            Label(
                copiedSection == section ? copiedTitle : title,
                systemImage: copiedSection == section ? "checkmark" : "doc.on.doc"
            )
        }
        .buttonStyle(WaiGhostButtonStyle())
        .help(copiedSection == section ? t("Copied!", "Скопировано") : title)
    }

    private func exportRecording(format: String) async {
        guard let id = viewModel.recordingDetail?.id else { return }
        do {
            let content = try await appState.getAPIClient().exportRecording(id: id, format: format)
            let ext = format == "markdown" ? "md" : format
            let title = viewModel.recordingDetail?.title ?? "recording"
            let safeName = title.replacingOccurrences(of: "/", with: "_")

            let panel = NSSavePanel()
            panel.nameFieldStringValue = "\(safeName).\(ext)"
            panel.allowedContentTypes = [.plainText]
            let result = panel.runModal()
            if result == .OK, let url = panel.url {
                try content.write(to: url, atomically: true, encoding: .utf8)
            }
        } catch {
            viewModel.error = error.userFacingMessage(context: .library)
        }
    }

    @MainActor
    private func shareRecording(_ detail: RecordingDetail) async {
        isSharing = true
        defer { isSharing = false }

        do {
            let link = try await appState.getAPIClient().createRecordingShareLink(id: detail.id)
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(link.url.absoluteString, forType: .string)
            copiedSection = "share-link"
            pendingSharePayload = SharePickerPayload(url: link.url)
            Task {
                try? await Task.sleep(for: .seconds(1.5))
                if copiedSection == "share-link" {
                    copiedSection = nil
                }
            }
        } catch {
            viewModel.error = error.userFacingMessage(context: .library)
        }
    }

    private func detailHeader(_ detail: RecordingDetail) -> some View {
        ViewThatFits(in: .horizontal) {
            HStack(alignment: .top, spacing: Spacing.lg) {
                detailHeaderTitle(detail)
                Spacer(minLength: Spacing.md)
                detailHeaderActions(detail)
            }

            VStack(alignment: .leading, spacing: Spacing.md) {
                detailHeaderTitle(detail)
                detailHeaderActions(detail)
            }
        }
        .padding(Spacing.lg)
    }

    private func detailHeaderTitle(_ detail: RecordingDetail) -> some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            if isEditingTitle && mode == .active {
                TextField(t("Title", "Название"), text: $titleDraft)
                    .textFieldStyle(.plain)
                    .font(Typography.displayMedium)
                    .lineLimit(2)
                    .focused($titleFieldFocused)
                    .onSubmit { commitTitleEdit(originalTitle: detail.title) }
                    .onKeyPress(.escape) {
                        isEditingTitle = false
                        return .handled
                    }
                    .onChange(of: titleFieldFocused) { _, focused in
                        if !focused && isEditingTitle {
                            commitTitleEdit(originalTitle: detail.title)
                        }
                    }
                    .accessibilityIdentifier("recording-title-edit")
            } else {
                Text(detail.title ?? t("Untitled", "Без названия"))
                    .font(Typography.displayMedium)
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
                    .accessibilityElement(children: .ignore)
                    .accessibilityIdentifier("recording-title")
                    .contentShape(Rectangle())
                    .onTapGesture(count: 2) {
                        guard mode == .active else { return }
                        startTitleEdit(currentTitle: detail.title)
                    }
                    .help(mode == .active ? t("Double-click to rename", "Двойной клик для переименования") : "")
            }

            HStack(spacing: Spacing.sm) {
                Text(recordingTypeLabel(detail.type))
                    .font(Typography.label)
                    .foregroundStyle(Palette.typeColor(detail.type))

                Text(MacDateFormatting.string(
                    from: detail.createdAt,
                    dateStyle: .long,
                    timeStyle: .short,
                    language: languageManager.current
                ))
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textSecondary)

                if let duration = detail.durationSeconds, duration > 0 {
                    let mins = duration / 60
                    let secs = duration % 60
                    Text(String(format: "%d:%02d", mins, secs))
                        .font(Typography.mono)
                        .foregroundStyle(Palette.textSecondary)
                }
            }
            .lineLimit(1)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func detailHeaderActions(_ detail: RecordingDetail) -> some View {
        ViewThatFits(in: .horizontal) {
            detailHeaderActionRow(detail, showsLabels: true)
            detailHeaderActionRow(detail, showsLabels: false)
        }
    }

    private func detailHeaderActionRow(_ detail: RecordingDetail, showsLabels: Bool) -> some View {
        HStack(spacing: Spacing.md) {
            if mode == .active {
                Menu {
                    Button(t("Export Markdown (.md)", "Экспорт Markdown (.md)")) {
                        Task { await exportRecording(format: "markdown") }
                    }
                    Button(t("Export Plain Text (.txt)", "Экспорт TXT (.txt)")) {
                        Task { await exportRecording(format: "txt") }
                    }
                    Button(t("Export Subtitles (.srt)", "Экспорт субтитров (.srt)")) {
                        Task { await exportRecording(format: "srt") }
                    }
                } label: {
                    if showsLabels {
                        Label(t("Export", "Экспорт"), systemImage: "square.and.arrow.down")
                    } else {
                        Image(systemName: "square.and.arrow.down")
                    }
                }
                .buttonStyle(WaiGhostButtonStyle())
                .help(t("Export Recording", "Экспортировать запись"))

                Button {
                    Task {
                        await shareRecording(detail)
                    }
                } label: {
                    if showsLabels {
                        Label(
                            copiedSection == "share-link" ? t("Copied", "Скопировано") : t("Share", "Поделиться"),
                            systemImage: copiedSection == "share-link" ? "checkmark" : "square.and.arrow.up"
                        )
                    } else {
                        Image(systemName: copiedSection == "share-link" ? "checkmark" : "square.and.arrow.up")
                    }
                }
                .buttonStyle(WaiGhostButtonStyle())
                .help(t("Create a web share link", "Создать ссылку для просмотра"))
                .disabled(isSharing)

                moveToFolderMenu(detail, showsLabel: showsLabels)
            }

            if mode == .trash {
                Button {
                    Task {
                        let restored = await viewModel.restoreRecording(apiClient: appState.getAPIClient())
                        if restored {
                            onRestore?()
                        }
                    }
                } label: {
                    Image(systemName: "arrow.uturn.backward")
                        .foregroundStyle(Palette.textSecondary)
                }
                .buttonStyle(.plain)
                .help(t("Restore Recording", "Восстановить запись"))
            }

            deleteRecordingButton
        }
        .fixedSize(horizontal: true, vertical: false)
    }

    private func moveToFolderMenu(_ detail: RecordingDetail, showsLabel: Bool) -> some View {
        Menu {
            if detail.folderId != nil {
                Button(t("Remove from Folder", "Убрать из папки")) {
                    Task {
                        let didMove = await viewModel.moveRecording(
                            to: nil,
                            apiClient: appState.getAPIClient()
                        )
                        if didMove {
                            onMoveToFolder?(nil)
                        }
                    }
                }
            }

            ForEach(folders) { folder in
                Button(folder.name) {
                    Task {
                        let didMove = await viewModel.moveRecording(
                            to: folder.id,
                            apiClient: appState.getAPIClient()
                        )
                        if didMove {
                            onMoveToFolder?(folder.id)
                        }
                    }
                }
            }
        } label: {
            if showsLabel {
                Label(t("Move to Folder", "Переместить в папку"), systemImage: "folder")
            } else {
                Image(systemName: "folder")
            }
        }
        .buttonStyle(WaiGhostButtonStyle())
        .help(t("Move to Folder", "Переместить в папку"))
        .disabled(detail.folderId == nil && folders.isEmpty)
        .accessibilityIdentifier("recording-detail-move-to-folder-menu")
    }

    private var deleteRecordingButton: some View {
        Button {
            showDeleteConfirmation = true
        } label: {
            Image(systemName: mode == .trash ? "trash.slash" : "trash")
                .foregroundStyle(mode == .trash ? Palette.recording : Palette.textSecondary)
        }
        .buttonStyle(.plain)
        .help(mode == .trash ? t("Delete Permanently", "Удалить навсегда") : t("Move to Trash", "Переместить в корзину"))
        .confirmationDialog(
            mode == .trash ? t("Delete this recording permanently?", "Удалить запись навсегда?") : t("Move this recording to trash?", "Переместить запись в корзину?"),
            isPresented: $showDeleteConfirmation
        ) {
            Button(mode == .trash ? t("Delete Permanently", "Удалить навсегда") : t("Move to Trash", "Переместить в корзину"), role: .destructive) {
                Task {
                    let didDelete = await viewModel.deleteRecording(
                        apiClient: appState.getAPIClient(),
                        permanent: mode == .trash
                    )
                    if didDelete {
                        onDelete?()
                    }
                }
            }
            Button(t("Cancel", "Отмена"), role: .cancel) {}
        } message: {
            Text(
                mode == .trash
                    ? t("This action cannot be undone.", "Это действие нельзя отменить.")
                    : t("You can restore it later from Trash.", "Позже запись можно восстановить из корзины.")
            )
        }
    }

    private func fullSummaryText(_ summary: Summary) -> String {
        var parts: [String] = []
        if let text = summary.summary { parts.append(text) }
        if let points = summary.keyPoints, !points.isEmpty {
            parts.append("\n\(t("Key Points", "Ключевые пункты")):\n" + points.map { "— \($0)" }.joined(separator: "\n"))
        }
        if let topics = summary.topics, !topics.isEmpty {
            parts.append("\n\(t("Topics", "Темы")): " + topics.joined(separator: ", "))
        }
        if let people = summary.peopleMentioned, !people.isEmpty {
            parts.append("\n\(t("People", "Люди")): " + people.joined(separator: ", "))
        }
        return parts.joined(separator: "\n")
    }

    @ViewBuilder
    private func summaryTab(_ detail: RecordingDetail) -> some View {
        let isGeneratingSummary = viewModel.isGeneratingSummary(for: detail.id)

        if let summary = detail.summary {
            ScrollView {
                VStack(alignment: .leading, spacing: Spacing.xl) {
                    HStack {
                        Text(t("Summary", "Сводка"))
                            .waiSectionHeader()
                        Spacer()
                        copyActionButton(
                            title: t("Copy Summary", "Скопировать сводку"),
                            copiedTitle: t("Copied", "Скопировано"),
                            text: fullSummaryText(summary),
                            section: "summary-all"
                        )
                    }

                    if let text = summary.summary {
                        VStack(alignment: .leading, spacing: Spacing.sm) {
                            Text(t("Overview", "Обзор"))
                                .waiSectionHeader()
                            Text(text)
                                .font(Typography.reading)
                                .lineSpacing(6)
                                .textSelection(.enabled)
                        }
                    }

                    if let points = summary.keyPoints, !points.isEmpty {
                        VStack(alignment: .leading, spacing: Spacing.sm) {
                            Text(t("Key Points", "Ключевые пункты"))
                                .waiSectionHeader()
                            ForEach(points, id: \.self) { point in
                                HStack(alignment: .firstTextBaseline, spacing: Spacing.sm) {
                                    Text("\u{2014}")
                                        .font(Typography.reading)
                                        .foregroundStyle(Palette.textTertiary)
                                    Text(point)
                                        .font(Typography.reading)
                                        .lineSpacing(6)
                                        .textSelection(.enabled)
                                }
                            }
                        }
                    }

                    if let topics = summary.topics, !topics.isEmpty {
                        VStack(alignment: .leading, spacing: Spacing.sm) {
                            Text(t("Topics", "Темы"))
                                .waiSectionHeader()
                            Text(topics.joined(separator: " \u{00B7} "))
                                .font(Typography.body)
                                .foregroundStyle(Palette.textSecondary)
                                .textSelection(.enabled)
                        }
                    }

                    if let people = summary.peopleMentioned, !people.isEmpty {
                        VStack(alignment: .leading, spacing: Spacing.sm) {
                            Text(t("People", "Люди"))
                                .waiSectionHeader()
                            Text(people.joined(separator: ", "))
                                .font(Typography.body)
                                .foregroundStyle(Palette.textSecondary)
                                .textSelection(.enabled)
                        }
                    }
                }
                .padding(.horizontal, Spacing.xxl)
                .padding(.vertical, Spacing.xl)
            }
            .accessibilityIdentifier("summary-content")
        } else {
            VStack(spacing: Spacing.lg) {
                Spacer().frame(height: Spacing.xxxl)
                ContentUnavailableView(
                    t("No Summary", "Нет сводки"),
                    systemImage: "doc.text",
                    description: Text(t("Generate a summary to see key points and insights.", "Сгенерируй сводку, чтобы увидеть ключевые пункты."))
                )

                Button(action: {
                    Task {
                        await viewModel.generateSummary(apiClient: appState.getAPIClient())
                    }
                }) {
                    Text(t("Generate Summary", "Сгенерировать сводку"))
                }
                .buttonStyle(WaiPrimaryButtonStyle(isDisabled: isGeneratingSummary))
                .disabled(isGeneratingSummary)

                if isGeneratingSummary {
                    ProgressView(t("Generating summary...", "Генерируем сводку..."))
                }
                Spacer()
            }
            .accessibilityIdentifier("summary-empty-state")
        }
    }

    private func recordingTypeLabel(_ type: RecordingType) -> String {
        switch type {
        case .meeting:
            return t("Meeting", "Встреча")
        case .note:
            return t("Note", "Заметка")
        case .reflection:
            return t("Reflection", "Рефлексия")
        }
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

private struct SharePickerPayload: Identifiable, Equatable {
    let id = UUID()
    let url: URL
}

private struct SharePickerPresenter: NSViewRepresentable {
    @Binding var payload: SharePickerPayload?

    func makeNSView(context: Context) -> NSView {
        NSView(frame: .zero)
    }

    func updateNSView(_ nsView: NSView, context: Context) {
        guard let payload else { return }

        DispatchQueue.main.async {
            let picker = NSSharingServicePicker(items: [payload.url])
            picker.show(relativeTo: nsView.bounds, of: nsView, preferredEdge: .minY)
            self.payload = nil
        }
    }
}

// MARK: - ViewModel

@MainActor
class MacRecordingDetailViewModel: ObservableObject {
    enum Tab: Hashable {
        case transcript, summary
    }

    @Published var recordingDetail: RecordingDetail?
    @Published var isLoading = false
    @Published var error: String?
    @Published var selectedTab: Tab = .transcript
    @Published private var generatingSummaryRecordingId: String?

    private var loadGeneration = 0

    init(initialDetail: RecordingDetail? = nil) {
        recordingDetail = initialDetail
    }

    func isGeneratingSummary(for recordingId: String) -> Bool {
        generatingSummaryRecordingId == recordingId
    }

    func load(
        recordingId: String,
        apiClient: APIClient,
        fixtureDetail: (() async -> RecordingDetail?)? = nil,
        showLoading: Bool = true
    ) async {
        loadGeneration += 1
        let generation = loadGeneration
        if showLoading {
            isLoading = true
        }
        error = nil

        defer {
            if showLoading, generation == loadGeneration {
                isLoading = false
            }
        }

        do {
            let detail: RecordingDetail
            if let fixture = await fixtureDetail?() {
                detail = fixture
            } else {
                detail = try await apiClient.getRecording(id: recordingId)
            }
            guard generation == loadGeneration else { return }
            recordingDetail = detail
        } catch {
            guard generation == loadGeneration else { return }
            if recordingDetail?.id != recordingId {
                self.error = error.userFacingMessage(context: .library)
            }
        }
    }

    func refreshPendingDetailIfNeeded(
        recordingId: String,
        apiClient: APIClient,
        fixtureDetail: (() async -> RecordingDetail?)? = nil
    ) async {
        guard recordingDetail?.id == recordingId else { return }
        guard shouldAutoRefresh(for: recordingDetail?.status) else { return }

        while !Task.isCancelled,
              recordingDetail?.id == recordingId,
              shouldAutoRefresh(for: recordingDetail?.status) {
            try? await Task.sleep(for: .seconds(recordingDetail?.status == .processing ? 4 : 2))
            guard !Task.isCancelled else { return }
            await load(
                recordingId: recordingId,
                apiClient: apiClient,
                fixtureDetail: fixtureDetail,
                showLoading: false
            )
        }
    }

    func generateSummary(apiClient: APIClient) async {
        guard let id = recordingDetail?.id else { return }
        generatingSummaryRecordingId = id
        defer {
            if generatingSummaryRecordingId == id {
                generatingSummaryRecordingId = nil
            }
        }

        do {
            _ = try await apiClient.generateSummary(recordingId: id)
            let detail = try await apiClient.getRecording(id: id)
            if recordingDetail?.id == id {
                recordingDetail = detail
                selectedTab = .summary
            }
        } catch {
            self.error = error.userFacingMessage(context: .library)
        }
    }

    func deleteRecording(apiClient: APIClient, permanent: Bool = false) async -> Bool {
        guard let id = recordingDetail?.id else { return false }
        do {
            try await apiClient.deleteRecording(id: id, permanent: permanent)
            return true
        } catch {
            self.error = error.userFacingMessage(context: .library)
            return false
        }
    }

    func restoreRecording(apiClient: APIClient) async -> Bool {
        guard let id = recordingDetail?.id else { return false }
        do {
            _ = try await apiClient.restoreRecording(id: id)
            return true
        } catch {
            self.error = error.userFacingMessage(context: .library)
            return false
        }
    }

    func moveRecording(to folderId: String?, apiClient: APIClient) async -> Bool {
        guard let id = recordingDetail?.id else { return false }
        do {
            _ = try await apiClient.moveRecording(id: id, folderId: folderId)
            recordingDetail = try await apiClient.getRecording(id: id)
            return true
        } catch {
            self.error = error.userFacingMessage(context: .library)
            return false
        }
    }

    func renameRecording(_ newTitle: String, apiClient: APIClient) async -> Bool {
        guard let id = recordingDetail?.id else { return false }
        let trimmed = newTitle.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return false }
        do {
            _ = try await apiClient.updateRecording(id: id, title: trimmed)
            recordingDetail = try await apiClient.getRecording(id: id)
            return true
        } catch {
            self.error = error.userFacingMessage(context: .library)
            return false
        }
    }

    private func shouldAutoRefresh(for status: RecordingStatus?) -> Bool {
        switch status {
        case .pendingUpload, .uploading, .processing:
            return true
        case .ready, .failed, .none:
            return false
        }
    }
}
