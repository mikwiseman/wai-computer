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
            if viewModel.isLoading && viewModel.recordingDetail == nil {
                ProgressView(t("Loading...", "Загрузка..."))
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if let detail = viewModel.recordingDetail {
                VStack(spacing: 0) {
                    if let error = viewModel.error {
                        RecordingDetailInlineErrorBanner(
                            message: error,
                            onDismiss: { viewModel.error = nil }
                        )
                        .padding(.horizontal, Spacing.lg)
                        .padding(.top, Spacing.md)
                    }

                    detailHeader(detail)

                    WaiDivider()

                    WaiTabBar(
                        tabs: [
                            (t("Transcript", "Расшифровка"), MacRecordingDetailViewModel.Tab.transcript),
                            (t("Summary", "Сводка"), MacRecordingDetailViewModel.Tab.summary),
                        ],
                        selection: $viewModel.selectedTab
                    )

                    WaiDivider()

                    switch viewModel.selectedTab {
                    case .transcript:
                        MacTranscriptView(
                            segments: detail.segments,
                            availability: viewModel.transcriptAvailability,
                            localRecoveryManifest: viewModel.localRecoveryManifest,
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
            } else if let error = viewModel.error {
                RecordingDetailLoadErrorView(
                    title: t("Couldn’t Load Recording", "Не удалось загрузить запись"),
                    message: error,
                    retryTitle: t("Try Again", "Повторить"),
                    onRetry: retryLoad
                )
            } else {
                ContentUnavailableView(
                    t("Recording Not Found", "Запись не найдена"),
                    systemImage: "doc.questionmark",
                    description: Text(t("Unable to load this recording.", "Не удалось загрузить эту запись."))
                )
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
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

    private func retryLoad() {
        loadTask?.cancel()
        loadTask = Task {
            await loadRecordingDetail(recordingId: recordingId, showLoading: true)
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
        let summaryStatus = viewModel.recordingDetail?.summaryGeneration?.status ?? "none"
        let summaryStage = viewModel.recordingDetail?.summaryGeneration?.stage ?? "none"
        return "\(recordingId)-\(status)-\(summaryStatus)-\(summaryStage)"
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
                    .frame(
                        minWidth: MacMainLayoutMetrics.recordingTitleEditMinWidth,
                        maxWidth: .infinity,
                        alignment: .leading
                    )
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
        let generationState = detail.summaryGeneration
        let isGeneratingSummary = viewModel.isGeneratingSummary(for: detail.id) ||
            generationState?.isActive == true
        let generationFailed = generationState?.isFailed == true

        if let summary = detail.summary {
            ScrollView {
                VStack(alignment: .leading, spacing: Spacing.xl) {
                    if isGeneratingSummary {
                        summaryGenerationProgress(state: generationState)
                    }

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
                        await viewModel.startSummaryGeneration(
                            recordingId: detail.id,
                            apiClient: appState.getAPIClient()
                        )
                    }
                }) {
                    Text(summaryGenerationButtonTitle(isGenerating: isGeneratingSummary, failed: generationFailed))
                }
                .buttonStyle(WaiPrimaryButtonStyle(isDisabled: isGeneratingSummary))
                .disabled(isGeneratingSummary)

                if isGeneratingSummary {
                    summaryGenerationProgress(state: generationState)
                } else if generationFailed {
                    summaryGenerationFailure(state: generationState)
                }
                Spacer()
            }
            .accessibilityIdentifier("summary-empty-state")
        }
    }

    private func summaryGenerationButtonTitle(isGenerating: Bool, failed: Bool) -> String {
        if isGenerating {
            return t("Generating Summary", "Генерируем сводку")
        }
        if failed {
            return t("Try Again", "Повторить")
        }
        return t("Generate Summary", "Сгенерировать сводку")
    }

    private func summaryGenerationStatusText(_ state: SummaryGenerationState?) -> String {
        guard let state else {
            return t("Starting summary generation...", "Запускаем генерацию сводки...")
        }

        switch state.status {
        case "queued":
            return t("Summary generation is queued.", "Генерация сводки в очереди.")
        case "running":
            switch state.stage {
            case "preparing_transcript":
                return t("Preparing transcript...", "Подготавливаем расшифровку...")
            case "saving_summary":
                return t("Saving summary...", "Сохраняем сводку...")
            default:
                return t("Generating summary...", "Генерируем сводку...")
            }
        default:
            return t("Generating summary...", "Генерируем сводку...")
        }
    }

    private func summaryGenerationFailureText(_ state: SummaryGenerationState?) -> String {
        let message = state?.errorMessage?.trimmingCharacters(in: .whitespacesAndNewlines)
        if let message, !message.isEmpty {
            return message
        }
        return t("Summary generation failed.", "Не удалось сгенерировать сводку.")
    }

    private func summaryGenerationProgress(state: SummaryGenerationState?) -> some View {
        HStack(alignment: .center, spacing: Spacing.sm) {
            ProgressView()
                .controlSize(.small)
            Text(summaryGenerationStatusText(state))
                .font(Typography.bodySmall)
                .foregroundStyle(Palette.textSecondary)
        }
        .padding(.horizontal, Spacing.md)
        .padding(.vertical, Spacing.sm)
        .background(Palette.recording.opacity(0.10))
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .accessibilityIdentifier("summary-generation-progress")
    }

    private func summaryGenerationFailure(state: SummaryGenerationState?) -> some View {
        Text(summaryGenerationFailureText(state))
            .font(Typography.caption)
            .foregroundStyle(Palette.recording)
            .multilineTextAlignment(.center)
            .fixedSize(horizontal: false, vertical: true)
            .accessibilityIdentifier("summary-generation-failure")
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

private struct RecordingDetailInlineErrorBanner: View {
    let message: String
    let onDismiss: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: Spacing.sm) {
            Image(systemName: "wifi.exclamationmark")
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(Palette.recording)

            Text(message)
                .font(Typography.bodySmall)
                .foregroundStyle(Palette.textSecondary)
                .fixedSize(horizontal: false, vertical: true)

            Spacer(minLength: Spacing.md)

            Button(action: onDismiss) {
                Image(systemName: "xmark")
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(Palette.textTertiary)
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Dismiss recording detail message")
        }
        .padding(.horizontal, Spacing.md)
        .padding(.vertical, Spacing.sm)
        .background(Palette.recording.opacity(0.10))
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .accessibilityIdentifier("recording-detail-inline-error")
    }
}

private struct RecordingDetailLoadErrorView: View {
    let title: String
    let message: String
    let retryTitle: String
    let onRetry: () -> Void

    var body: some View {
        VStack(spacing: Spacing.lg) {
            ContentUnavailableView(
                title,
                systemImage: "wifi.exclamationmark",
                description: Text(message)
            )

            Button(retryTitle, action: onRetry)
                .buttonStyle(WaiPrimaryButtonStyle(isDisabled: false))
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .accessibilityIdentifier("recording-detail-load-error")
    }
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
