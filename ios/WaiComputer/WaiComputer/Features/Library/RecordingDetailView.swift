import SwiftUI
import UniformTypeIdentifiers
import WaiComputerKit

private func visibleSummaryActionItems(_ actionItems: [ActionItem]) -> [ActionItem] {
    actionItems.filter { $0.status != .cancelled }
}

struct RecordingDetailView: View {
    @EnvironmentObject var appState: AppState
    @EnvironmentObject private var languageManager: LanguageManager
    @Environment(\.dismiss) private var dismiss
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass
    let recording: Recording
    let isTrash: Bool
    let folders: [Folder]
    var onMoveToFolder: ((String?) -> Void)?
    var onTrash: (() -> Void)?
    var onRestore: (() -> Void)?
    var onPermanentDelete: (() -> Void)?
    var onDidRename: (() -> Void)?

    @StateObject private var viewModel = RecordingDetailViewModel()
    @State private var selectedTab = 0
    @State private var showDeleteConfirmation = false
    @State private var showRenameAlert = false
    @State private var renameDraft = ""
    @State private var exportShareItem: ExportShareItem?
    @State private var isExporting = false
    @State private var isSharing = false
    @State private var copiedSection: String?

    private var isScreenshotMode: Bool {
        IOSTestingMode.current.isScreenshot
    }

    init(
        recording: Recording,
        isTrash: Bool = false,
        folders: [Folder] = [],
        onMoveToFolder: ((String?) -> Void)? = nil,
        onTrash: (() -> Void)? = nil,
        onRestore: (() -> Void)? = nil,
        onPermanentDelete: (() -> Void)? = nil,
        onDidRename: (() -> Void)? = nil
    ) {
        self.recording = recording
        self.isTrash = isTrash
        self.folders = folders
        self.onMoveToFolder = onMoveToFolder
        self.onTrash = onTrash
        self.onRestore = onRestore
        self.onPermanentDelete = onPermanentDelete
        self.onDidRename = onDidRename
    }

    var body: some View {
        Group {
            if viewModel.isLoading && viewModel.detail == nil {
                ProgressView()
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if viewModel.detail == nil, let error = viewModel.error {
                loadErrorState(message: error)
            } else {
                content
            }
        }
        .navigationTitle(viewModel.detail?.title ?? recording.title ?? t("Recording", "Запись"))
        .navigationBarTitleDisplayMode(.inline)
        .toolbar { toolbarContent }
        .confirmationDialog(
            isTrash
                ? t("Delete this recording permanently?", "Удалить запись навсегда?")
                : t("Move this recording to trash?", "Переместить запись в корзину?"),
            isPresented: $showDeleteConfirmation,
            titleVisibility: .visible
        ) {
            Button(
                isTrash ? t("Delete Permanently", "Удалить навсегда") : t("Move to Trash", "Переместить в корзину"),
                role: .destructive
            ) {
                if isTrash {
                    onPermanentDelete?()
                } else {
                    onTrash?()
                }
                dismiss()
            }
            Button(t("Cancel", "Отмена"), role: .cancel) {}
        } message: {
            Text(
                isTrash
                    ? t("This action cannot be undone.", "Это действие нельзя отменить.")
                    : t("You can restore it later from Trash.", "Позже запись можно восстановить из корзины.")
            )
        }
        .alert(t("Rename Recording", "Переименовать запись"), isPresented: $showRenameAlert) {
            TextField(t("Title", "Название"), text: $renameDraft)
            Button(t("Save", "Сохранить")) {
                let title = renameDraft
                Task {
                    let success = await viewModel.renameRecording(title, apiClient: appState.getAPIClient())
                    if success { onDidRename?() }
                }
            }
            Button(t("Cancel", "Отмена"), role: .cancel) {}
        }
        .sheet(item: $exportShareItem) { item in
            ShareLink(item: item.url) {
                Label(t("Share Export", "Поделиться экспортом"), systemImage: "square.and.arrow.up")
            }
            .presentationDetents([.medium])
        }
        .task(id: recording.id) {
            if isScreenshotMode {
                viewModel.loadScreenshotFixture(recordingId: recording.id)
            } else {
                await viewModel.loadDetail(recordingId: recording.id, apiClient: appState.getAPIClient())
            }
        }
        .task(id: detailRefreshKey) {
            guard !isScreenshotMode else { return }
            await viewModel.refreshPendingDetailIfNeeded(
                recordingId: recording.id,
                apiClient: appState.getAPIClient()
            )
        }
        .onChange(of: recording.id) {
            selectedTab = 0
        }
        .onAppear {
            selectedTab = screenshotSelectedTab
        }
        .onReceive(NotificationCenter.default.publisher(for: .pendingRecordingSyncDidFinish)) { notification in
            guard !isScreenshotMode else { return }
            guard let syncedRecordingId = notification.userInfo?["recordingId"] as? String,
                  syncedRecordingId == recording.id else {
                return
            }
            Task {
                await viewModel.loadDetail(
                    recordingId: recording.id,
                    apiClient: appState.getAPIClient(),
                    showLoading: false
                )
            }
        }
    }

    // MARK: - Content

    private var content: some View {
        Group {
            if horizontalSizeClass == .regular, let detail = viewModel.detail {
                regularWidthContent(detail)
            } else {
                compactTabbedContent
            }
        }
        .overlay {
            if viewModel.isLoading {
                ProgressView()
            }
        }
    }

    private var compactTabbedContent: some View {
        VStack(spacing: 0) {
            // Dismissible inline banner for post-load errors.
            if viewModel.detail != nil, let error = viewModel.error {
                RecordingDetailInlineErrorBanner(
                    message: error,
                    onDismiss: { viewModel.error = nil }
                )
                .padding(.horizontal)
                .padding(.top, 8)
            }

            // Tab picker
            Picker(t("View", "Вид"), selection: $selectedTab) {
                Text(t("Transcript", "Расшифровка")).tag(0)
                Text(t("Summary", "Сводка")).tag(1)
                Text(t("Actions", "Задачи")).tag(2)
            }
            .pickerStyle(.segmented)
            .padding()

            // Content
            TabView(selection: $selectedTab) {
                TranscriptView(
                    segments: viewModel.detail?.segments ?? [],
                    availability: viewModel.transcriptAvailability,
                    localRecoveryManifest: viewModel.localRecoveryManifest,
                    recordingId: viewModel.detail?.id,
                    onAssigned: { updated in
                        viewModel.detail = updated
                    }
                )
                .tag(0)

                SummaryTabView(
                    summary: viewModel.detail?.summary,
                    actionItems: viewModel.detail?.actionItems ?? [],
                    generationState: viewModel.detail?.summaryGeneration,
                    audioState: viewModel.detail?.summaryAudio,
                    isGenerating: isGeneratingSummary,
                    isGeneratingAudio: isGeneratingSummaryAudio,
                    isDownloadingAudio: viewModel.isDownloadingSummaryAudio(for: recording.id),
                    isPlayingAudio: viewModel.isPlayingSummaryAudio(for: recording.id),
                    onGenerate: {
                        Task {
                            await viewModel.startSummaryGeneration(
                                recordingId: recording.id,
                                apiClient: appState.getAPIClient()
                            )
                        }
                    },
                    onGenerateAudio: {
                        Task {
                            await viewModel.startSummaryAudioGeneration(
                                recordingId: recording.id,
                                apiClient: appState.getAPIClient()
                            )
                        }
                    },
                    onPlayAudio: {
                        Task {
                            await viewModel.playOrStopSummaryAudio(
                                recordingId: recording.id,
                                apiClient: appState.getAPIClient()
                            )
                        }
                    }
                )
                .tag(1)

                ActionItemsTabView(actionItems: viewModel.detail?.actionItems ?? [])
                    .tag(2)
            }
            .tabViewStyle(.page(indexDisplayMode: .never))
        }
        .accessibilityIdentifier("recording-detail-compact-layout")
    }

    private func regularWidthContent(_ detail: RecordingDetail) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Spacing.xxl) {
                regularHeader(detail)
                regularSummarySection(detail)
                regularTranscriptSection(detail)
            }
            .frame(maxWidth: 920, alignment: .leading)
            .padding(.horizontal, Spacing.xxl)
            .padding(.vertical, Spacing.xl)
            .frame(maxWidth: .infinity, alignment: .topLeading)
        }
        .background(Color(uiColor: .systemGroupedBackground))
        .safeAreaInset(edge: .top, spacing: 0) {
            if let error = viewModel.error {
                RecordingDetailInlineErrorBanner(
                    message: error,
                    onDismiss: { viewModel.error = nil }
                )
                .padding(.horizontal, Spacing.xxl)
                .padding(.vertical, Spacing.sm)
            }
        }
        .accessibilityIdentifier("recording-detail-regular-layout")
    }

    private func regularHeader(_ detail: RecordingDetail) -> some View {
        ViewThatFits(in: .horizontal) {
            HStack(alignment: .top, spacing: Spacing.xl) {
                regularHeaderText(detail)
                Spacer(minLength: Spacing.xl)
                regularHeaderActions(detail)
            }

            VStack(alignment: .leading, spacing: Spacing.lg) {
                regularHeaderText(detail)
                regularHeaderActions(detail)
            }
        }
        .padding(.bottom, Spacing.sm)
        .accessibilityIdentifier("recording-detail-regular-header")
    }

    private func regularHeaderText(_ detail: RecordingDetail) -> some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            Text(detail.title ?? recording.title ?? t("Recording", "Запись"))
                .font(Typography.displayMedium)
                .foregroundStyle(Palette.textPrimary)
                .lineLimit(2)
                .textSelection(.enabled)

            HStack(spacing: Spacing.sm) {
                Text(IOSDateFormatting.string(
                    from: detail.createdAt,
                    dateStyle: .long,
                    timeStyle: .short,
                    language: languageManager.current
                ))
                .font(Typography.caption)
                .foregroundStyle(Palette.textSecondary)

                if let duration = detail.durationSeconds, duration > 0 {
                    Text(formatDuration(duration))
                        .font(Typography.mono)
                        .foregroundStyle(Palette.textSecondary)
                }
            }
            .lineLimit(1)
        }
    }

    private func regularHeaderActions(_ detail: RecordingDetail) -> some View {
        ViewThatFits(in: .horizontal) {
            regularHeaderActionRow(detail, showsLabels: true)
            regularHeaderActionRow(detail, showsLabels: false)
        }
    }

    private func regularHeaderActionRow(_ detail: RecordingDetail, showsLabels: Bool) -> some View {
        HStack(spacing: Spacing.md) {
            if isTrash {
                if onRestore != nil {
                    regularActionButton(
                        title: t("Restore", "Восстановить"),
                        systemImage: "arrow.uturn.backward",
                        showsLabels: showsLabels
                    ) {
                        onRestore?()
                        dismiss()
                    }
                }
            } else {
                regularActionButton(
                    title: t("Rename", "Переименовать"),
                    systemImage: "pencil",
                    showsLabels: showsLabels
                ) {
                    renameDraft = detail.title ?? recording.title ?? ""
                    showRenameAlert = true
                }

                regularExportMenu(showsLabels: showsLabels)

                regularActionButton(
                    title: isSharing ? t("Sharing", "Готовим") : t("Share", "Поделиться"),
                    systemImage: "square.and.arrow.up",
                    showsLabels: showsLabels
                ) {
                    Task { await runShare() }
                }
                .disabled(isSharing)

                if detail.summary != nil {
                    regularSummaryAudioButton(detail, showsLabels: showsLabels)
                }

                if onMoveToFolder != nil {
                    regularMoveToFolderMenu(detail, showsLabels: showsLabels)
                }
            }

            if (isTrash && onPermanentDelete != nil) || (!isTrash && onTrash != nil) {
                regularActionButton(
                    title: isTrash
                        ? t("Delete Permanently", "Удалить навсегда")
                        : t("Move to Trash", "Переместить в корзину"),
                    systemImage: isTrash ? "trash.slash" : "trash",
                    role: .destructive,
                    showsLabels: showsLabels
                ) {
                    showDeleteConfirmation = true
                }
            }
        }
        .fixedSize(horizontal: true, vertical: false)
    }

    private func regularActionButton(
        title: String,
        systemImage: String,
        role: ButtonRole? = nil,
        showsLabels: Bool,
        action: @escaping () -> Void
    ) -> some View {
        Button(role: role, action: action) {
            if showsLabels {
                Label(title, systemImage: systemImage)
            } else {
                Image(systemName: systemImage)
            }
        }
        .buttonStyle(.bordered)
        .controlSize(.regular)
        .tint(role == .destructive ? Palette.recording : Palette.accent)
        .accessibilityLabel(title)
    }

    private func regularExportMenu(showsLabels: Bool) -> some View {
        Menu {
            Button {
                Task { await runExport(format: "markdown") }
            } label: {
                Label(t("Markdown (.md)", "Markdown (.md)"), systemImage: "doc.richtext")
            }

            Button {
                Task { await runExport(format: "txt") }
            } label: {
                Label(t("Plain Text (.txt)", "Текст (.txt)"), systemImage: "doc.plaintext")
            }

            Button {
                Task { await runExport(format: "txt", style: "timestamped") }
            } label: {
                Label(t("Plain Text + timestamps (.txt)", "Текст с тайм-кодами (.txt)"), systemImage: "clock")
            }

            Button {
                Task { await runExport(format: "srt") }
            } label: {
                Label(t("Subtitles (.srt)", "Субтитры (.srt)"), systemImage: "captions.bubble")
            }
        } label: {
            if showsLabels {
                Label(t("Export", "Экспорт"), systemImage: "square.and.arrow.down")
            } else {
                Image(systemName: "square.and.arrow.down")
            }
        }
        .buttonStyle(.bordered)
        .controlSize(.regular)
        .tint(Palette.accent)
        .disabled(isExporting)
        .accessibilityLabel(t("Export Recording", "Экспортировать запись"))
    }

    private func regularSummaryAudioButton(_ detail: RecordingDetail, showsLabels: Bool) -> some View {
        let audioState = detail.summaryAudio
        let isGeneratingAudio = isGeneratingSummaryAudio
        let isDownloadingAudio = viewModel.isDownloadingSummaryAudio(for: detail.id)
        let isPlayingAudio = viewModel.isPlayingSummaryAudio(for: detail.id)
        let title = audioState?.isSucceeded == true
            ? summaryAudioPlaybackButtonTitle(
                isDownloading: isDownloadingAudio,
                isPlaying: isPlayingAudio
            )
            : summaryAudioButtonTitle(state: audioState, isGenerating: isGeneratingAudio)
        let icon = audioState?.isSucceeded == true
            ? (isPlayingAudio ? "stop.fill" : "play.fill")
            : (audioState?.isFailed == true ? "arrow.clockwise" : "waveform")

        return regularActionButton(
            title: title,
            systemImage: icon,
            showsLabels: showsLabels
        ) {
            Task {
                if audioState?.isSucceeded == true {
                    await viewModel.playOrStopSummaryAudio(
                        recordingId: detail.id,
                        apiClient: appState.getAPIClient()
                    )
                } else {
                    await viewModel.startSummaryAudioGeneration(
                        recordingId: detail.id,
                        apiClient: appState.getAPIClient()
                    )
                }
            }
        }
        .disabled(isGeneratingAudio || isDownloadingAudio)
        .accessibilityIdentifier(audioState?.isSucceeded == true
            ? "recording-detail-summary-audio-play-button"
            : "recording-detail-summary-audio-create-button")
    }

    private func regularMoveToFolderMenu(_ detail: RecordingDetail, showsLabels: Bool) -> some View {
        Menu {
            if detail.folderId != nil {
                Button(t("Remove from Folder", "Убрать из папки")) {
                    onMoveToFolder?(nil)
                }
            }

            ForEach(folders) { folder in
                if detail.folderId != folder.id {
                    Button(folder.name) {
                        onMoveToFolder?(folder.id)
                    }
                }
            }
        } label: {
            if showsLabels {
                Label(t("Move to Folder", "Переместить в папку"), systemImage: "folder")
            } else {
                Image(systemName: "folder")
            }
        }
        .buttonStyle(.bordered)
        .controlSize(.regular)
        .tint(Palette.accent)
        .disabled(detail.folderId == nil && folders.isEmpty)
        .accessibilityLabel(t("Move to Folder", "Переместить в папку"))
        .accessibilityIdentifier("recording-detail-move-to-folder-menu")
    }

    private func regularSummarySection(_ detail: RecordingDetail) -> some View {
        VStack(alignment: .leading, spacing: Spacing.lg) {
            HStack(alignment: .center, spacing: Spacing.md) {
                Label(t("Summary", "Сводка"), systemImage: "doc.text.magnifyingglass")
                    .waiSectionHeader()
                Spacer()
                if let summary = detail.summary {
                    CopyButton(
                        text: fullSummaryText(summary, actionItems: detail.actionItems),
                        section: "summary-all",
                        copiedSection: $copiedSection
                    )
                    .accessibilityLabel(t("Copy Summary", "Скопировать сводку"))
                }
            }

            if isGeneratingSummary && detail.summary != nil {
                regularProgressRow(
                    text: summaryGenerationStatusText(state: detail.summaryGeneration),
                    identifier: "summary-generation-progress"
                )
            }

            if let summary = detail.summary {
                if isGeneratingSummaryAudio {
                    regularProgressRow(
                        text: detail.summaryAudio?.message ?? t("Creating summary audio...", "Создаем аудио сводки..."),
                        identifier: "summary-audio-progress"
                    )
                } else if detail.summaryAudio?.isFailed == true {
                    regularFailureText(
                        detail.summaryAudio?.errorMessage ?? t(
                            "Summary audio generation failed.",
                            "Не удалось создать аудио сводки."
                        ),
                        identifier: "summary-audio-failure"
                    )
                }

                regularSummaryBody(summary, actionItems: detail.actionItems)
            } else {
                regularSummaryEmptyState(detail)
            }
        }
        .accessibilityIdentifier(detail.summary == nil ? "summary-empty-state" : "summary-content")
    }

    @ViewBuilder
    private func regularSummaryBody(_ summary: Summary, actionItems: [ActionItem]) -> some View {
        let visibleActionItems = visibleSummaryActionItems(actionItems)

        if let text = summary.summary {
            regularTextSection(title: t("Overview", "Обзор"), text: text)
        }

        if let keyPoints = summary.keyPoints, !keyPoints.isEmpty {
            regularBulletSection(title: t("Key Points", "Ключевые пункты"), rows: keyPoints)
        }

        if !visibleActionItems.isEmpty {
            regularActionItemsSection(visibleActionItems)
        }

        if let topics = summary.topics, !topics.isEmpty {
            regularTagSection(title: t("Topics", "Темы"), values: topics, systemImage: nil)
        }

        if let people = summary.peopleMentioned, !people.isEmpty {
            regularTagSection(title: t("People", "Люди"), values: people, systemImage: "person.circle.fill")
        }
    }

    private func regularSummaryEmptyState(_ detail: RecordingDetail) -> some View {
        let generationState = detail.summaryGeneration
        let isGeneratingSummary = isGeneratingSummary
        let generationFailed = generationState?.isFailed == true
        let transcriptPending = detail.segments.isEmpty && (
            detail.status == .pendingUpload ||
            detail.status == .uploading ||
            detail.status == .processing
        )

        return VStack(alignment: .leading, spacing: Spacing.md) {
            if transcriptPending {
                regularProgressRow(
                    text: t(
                        "The summary will start when the transcript is available.",
                        "Сводка запустится, когда расшифровка будет готова."
                    ),
                    identifier: "summary-waiting-for-transcript"
                )
            } else {
                Text(t("Summary is not ready yet.", "Сводка еще не готова."))
                    .font(Typography.body)
                    .foregroundStyle(Palette.textPrimary)

                Button {
                    Task {
                        await viewModel.startSummaryGeneration(
                            recordingId: detail.id,
                            apiClient: appState.getAPIClient()
                        )
                    }
                } label: {
                    Text(summaryGenerationButtonTitle(
                        isGenerating: isGeneratingSummary,
                        failed: generationFailed,
                        state: generationState
                    ))
                }
                .buttonStyle(WaiPrimaryButtonStyle(isDisabled: isGeneratingSummary))
                .disabled(isGeneratingSummary)

                if isGeneratingSummary {
                    regularProgressRow(
                        text: summaryGenerationStatusText(state: generationState),
                        identifier: "summary-generation-progress"
                    )
                } else if generationFailed {
                    regularFailureText(
                        summaryGenerationFailureText(state: generationState),
                        identifier: "summary-generation-failure"
                    )
                }
            }
        }
        .padding(Spacing.lg)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Palette.surfaceSubtle)
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }

    private func regularTranscriptSection(_ detail: RecordingDetail) -> some View {
        VStack(alignment: .leading, spacing: Spacing.lg) {
            HStack(alignment: .center, spacing: Spacing.md) {
                Label(t("Transcript", "Расшифровка"), systemImage: "text.alignleft")
                    .waiSectionHeader()
                Spacer()
                if !detail.segments.isEmpty {
                    transcriptCopyMenu(detail.segments)
                }
            }

            if detail.segments.isEmpty {
                regularTranscriptEmptyState
            } else {
                LazyVStack(alignment: .leading, spacing: Spacing.lg) {
                    ForEach(TranscriptRendering.mergeTurns(detail.segments, languageCode: speakerLanguageCode)) { turn in
                        SegmentView(
                            segment: turn.displaySegment,
                            recordingId: detail.id,
                            onAssigned: { updated in
                                viewModel.detail = updated
                            }
                        )
                    }
                }
            }
        }
        .accessibilityIdentifier("transcript-content")
    }

    @ViewBuilder
    private var regularTranscriptEmptyState: some View {
        switch viewModel.transcriptAvailability {
        case .savedLocally:
            regularMutedState(
                title: t("Saved locally", "Сохранено локально"),
                message: t(
                    "This recording is stored on this device and will sync automatically.",
                    "Эта запись сохранена на устройстве и синхронизируется автоматически."
                ),
                systemImage: "externaldrive",
                identifier: "transcript-local-recovery-state"
            )
        case .processing:
            regularMutedState(
                title: t("Transcript is processing", "Расшифровка готовится"),
                message: t(
                    "The transcript will appear here automatically.",
                    "Расшифровка появится здесь автоматически."
                ),
                systemImage: "hourglass",
                identifier: "transcript-processing-state"
            )
        case .content, .empty:
            regularMutedState(
                title: t("No Transcript", "Нет расшифровки"),
                message: t(
                    "Transcript will appear here during and after recording.",
                    "Расшифровка появится здесь во время и после записи."
                ),
                systemImage: "text.quote",
                identifier: "transcript-empty-state"
            )
        }
    }

    private func transcriptCopyMenu(_ segments: [Segment]) -> some View {
        Menu {
            Button {
                copyTranscript(segments, style: .plain)
            } label: {
                Label(t("Copy text", "Скопировать текст"), systemImage: "doc.on.doc")
            }
            .accessibilityIdentifier("transcript-copy-plain")

            Button {
                copyTranscript(segments, style: .timestamped)
            } label: {
                Label(t("Copy with timestamps", "Скопировать с тайм-кодами"), systemImage: "clock")
            }
            .accessibilityIdentifier("transcript-copy-timestamped")
        } label: {
            Label(copiedSection == "transcript-all" ? t("Copied", "Скопировано") : t("Copy Transcript", "Скопировать расшифровку"), systemImage: copiedSection == "transcript-all" ? "checkmark" : "doc.on.doc")
        } primaryAction: {
            copyTranscript(segments, style: .plain)
        }
        .buttonStyle(.bordered)
        .tint(Palette.accent)
        .fixedSize()
        .accessibilityIdentifier("transcript-copy-menu")
        .accessibilityLabel(t("Copy transcript", "Скопировать расшифровку"))
    }

    private func copyTranscript(_ segments: [Segment], style: TranscriptStyle) {
        UIPasteboard.general.string = TranscriptRendering.transcriptText(
            segments,
            style: style,
            languageCode: speakerLanguageCode
        )
        copiedSection = "transcript-all"
        Task {
            try? await Task.sleep(for: .seconds(1.5))
            if copiedSection == "transcript-all" {
                copiedSection = nil
            }
        }
    }

    private func regularTextSection(title: String, text: String) -> some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            Text(title).waiSectionHeader()
            Text(text)
                .font(Typography.reading)
                .lineSpacing(6)
                .foregroundStyle(Palette.textPrimary)
                .textSelection(.enabled)
        }
    }

    private func regularBulletSection(title: String, rows: [String]) -> some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            Text(title).waiSectionHeader()
            ForEach(rows, id: \.self) { row in
                HStack(alignment: .firstTextBaseline, spacing: Spacing.sm) {
                    Circle()
                        .fill(Palette.accent)
                        .frame(width: 5, height: 5)
                    Text(row)
                        .font(Typography.reading)
                        .lineSpacing(6)
                        .textSelection(.enabled)
                }
            }
        }
    }

    private func regularActionItemsSection(_ actionItems: [ActionItem]) -> some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            Text(t("Action Items", "Задачи")).waiSectionHeader()
            ForEach(actionItems) { item in
                RecordingDetailActionItemRow(item: item)
            }
        }
        .accessibilityIdentifier("summary-action-items-ipad")
    }

    private func regularTagSection(title: String, values: [String], systemImage: String?) -> some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            Text(title).waiSectionHeader()
            FlowLayout(spacing: Spacing.sm) {
                ForEach(values, id: \.self) { value in
                    HStack(spacing: Spacing.xs) {
                        if let systemImage {
                            Image(systemName: systemImage)
                        }
                        Text(value)
                    }
                    .font(Typography.labelSmall)
                    .foregroundStyle(Palette.textSecondary)
                    .padding(.horizontal, Spacing.sm)
                    .padding(.vertical, 4)
                    .background(Palette.surfaceSubtle)
                    .clipShape(Capsule())
                }
            }
        }
    }

    private func regularProgressRow(text: String, identifier: String) -> some View {
        HStack(alignment: .center, spacing: Spacing.sm) {
            ProgressView()
                .controlSize(.small)
            Text(text)
                .font(Typography.bodySmall)
                .foregroundStyle(Palette.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.horizontal, Spacing.md)
        .padding(.vertical, Spacing.sm)
        .background(Palette.accent.opacity(0.10))
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        .accessibilityIdentifier(identifier)
    }

    private func regularFailureText(_ text: String, identifier: String) -> some View {
        Text(text)
            .font(Typography.bodySmall)
            .foregroundStyle(Palette.recording)
            .fixedSize(horizontal: false, vertical: true)
            .accessibilityIdentifier(identifier)
    }

    private func regularMutedState(
        title: String,
        message: String,
        systemImage: String,
        identifier: String
    ) -> some View {
        HStack(alignment: .top, spacing: Spacing.md) {
            Image(systemName: systemImage)
                .font(Typography.headingLarge)
                .foregroundStyle(Palette.textSecondary)
                .frame(width: 28)

            VStack(alignment: .leading, spacing: Spacing.xs) {
                Text(title)
                    .font(Typography.headingMedium)
                    .foregroundStyle(Palette.textPrimary)
                Text(message)
                    .font(Typography.bodySmall)
                    .foregroundStyle(Palette.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(Spacing.lg)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Palette.surfaceSubtle)
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        .accessibilityIdentifier(identifier)
    }

    private var isGeneratingSummary: Bool {
        viewModel.isGeneratingSummary(for: recording.id)
            || viewModel.detail?.summaryGeneration?.isActive == true
    }

    private var isGeneratingSummaryAudio: Bool {
        viewModel.isGeneratingSummaryAudio(for: recording.id)
            || viewModel.detail?.summaryAudio?.isActive == true
    }

    @ViewBuilder
    private func loadErrorState(message: String) -> some View {
        VStack(spacing: 16) {
            ContentUnavailableView(
                t("Couldn’t Load Recording", "Не удалось загрузить запись"),
                systemImage: "wifi.exclamationmark",
                description: Text(message)
            )

            Button(t("Try Again", "Повторить")) {
                Task {
                    await viewModel.loadDetail(recordingId: recording.id, apiClient: appState.getAPIClient())
                }
            }
            .buttonStyle(WaiPrimaryButtonStyle())
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .accessibilityIdentifier("recording-detail-load-error")
    }

    // MARK: - Toolbar

    @ToolbarContentBuilder
    private var toolbarContent: some ToolbarContent {
        ToolbarItem(placement: .primaryAction) {
            Menu {
                if isTrash {
                    if onRestore != nil {
                        Button {
                            onRestore?()
                            dismiss()
                        } label: {
                            Label(t("Restore", "Восстановить"), systemImage: "arrow.uturn.backward")
                        }
                    }

                    // Only offer permanent delete when a handler is wired;
                    // otherwise the action would silently no-op (no-fallbacks).
                    if onPermanentDelete != nil {
                        Button(role: .destructive) {
                            showDeleteConfirmation = true
                        } label: {
                            Label(t("Delete Permanently", "Удалить навсегда"), systemImage: "trash.slash")
                        }
                    }
                } else {
                    Button {
                        renameDraft = viewModel.detail?.title ?? recording.title ?? ""
                        showRenameAlert = true
                    } label: {
                        Label(t("Rename", "Переименовать"), systemImage: "pencil")
                    }

                    compactExportMenu

                    Button {
                        Task { await runShare() }
                    } label: {
                        Label(t("Share Link", "Поделиться ссылкой"), systemImage: "link")
                    }
                    .disabled(isSharing)

                    if !folders.isEmpty {
                        Menu {
                            if recording.folderId != nil {
                                Button(t("Unfiled", "Без папки")) {
                                    onMoveToFolder?(nil)
                                }
                            }

                            ForEach(folders) { folder in
                                if recording.folderId != folder.id {
                                    Button(folder.name) {
                                        onMoveToFolder?(folder.id)
                                    }
                                }
                            }
                        } label: {
                            Label(t("Move to Folder", "Переместить в папку"), systemImage: "folder")
                        }
                    }

                    // Only offer trash when a handler is wired; without it the
                    // action would silently no-op (no-fallbacks). Search-result
                    // detail now passes a real onTrash, so this stays available
                    // there too.
                    if onTrash != nil {
                        Button(role: .destructive) {
                            showDeleteConfirmation = true
                        } label: {
                            Label(t("Move to Trash", "Переместить в корзину"), systemImage: "trash")
                        }
                    }
                }
            } label: {
                Image(systemName: "ellipsis.circle")
            }
        }
    }

    private var compactExportMenu: some View {
        Menu {
            Button {
                Task { await runExport(format: "markdown") }
            } label: {
                Label(t("Markdown (.md)", "Markdown (.md)"), systemImage: "doc.richtext")
            }

            Button {
                Task { await runExport(format: "txt") }
            } label: {
                Label(t("Plain Text (.txt)", "Текст (.txt)"), systemImage: "doc.plaintext")
            }

            Button {
                Task { await runExport(format: "txt", style: "timestamped") }
            } label: {
                Label(t("Plain Text + timestamps (.txt)", "Текст с тайм-кодами (.txt)"), systemImage: "clock")
            }
            .accessibilityIdentifier("recording-detail-export-timestamped-text")

            Button {
                Task { await runExport(format: "srt") }
            } label: {
                Label(t("Subtitles (.srt)", "Субтитры (.srt)"), systemImage: "captions.bubble")
            }
        } label: {
            Label(t("Export", "Экспорт"), systemImage: "square.and.arrow.down")
        }
        .accessibilityIdentifier("recording-detail-compact-export-menu")
    }

    // MARK: - Export / Share

    private func runExport(format: String, style: String? = nil) async {
        guard !isExporting else { return }
        isExporting = true
        defer { isExporting = false }

        guard let content = await viewModel.exportRecording(
            format: format,
            locale: exportLocale,
            style: style,
            apiClient: appState.getAPIClient()
        ) else { return }

        let ext = format == "markdown" ? "md" : format
        let title = viewModel.detail?.title ?? recording.title ?? "recording"
        let safeName = title.replacingOccurrences(of: "/", with: "_")
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent(safeName)
            .appendingPathExtension(ext)

        do {
            try content.write(to: url, atomically: true, encoding: .utf8)
            exportShareItem = ExportShareItem(url: url)
        } catch {
            viewModel.error = error.userFacingMessage(context: .library)
        }
    }

    private func runShare() async {
        guard !isSharing else { return }
        isSharing = true
        defer { isSharing = false }

        guard let url = await viewModel.createShareLink(apiClient: appState.getAPIClient()) else { return }
        UIPasteboard.general.string = url.absoluteString
        exportShareItem = ExportShareItem(url: url)
    }

    private var exportLocale: String {
        switch languageManager.current {
        case .russian:
            return "ru"
        case .english:
            return "en"
        case .followSystem:
            return languageManager.preferredLocale.language.languageCode?.identifier == "ru" ? "ru" : "en"
        }
    }

    private func formatDuration(_ seconds: Int) -> String {
        String(format: "%d:%02d", seconds / 60, seconds % 60)
    }

    private var speakerLanguageCode: String {
        switch languageManager.current {
        case .followSystem:
            return languageManager.preferredLocale.identifier
        case .english, .russian:
            return languageManager.current.rawValue
        }
    }

    private func summaryAudioPlaybackButtonTitle(isDownloading: Bool, isPlaying: Bool) -> String {
        if isDownloading {
            return t("Loading audio", "Загружаем аудио")
        }
        return isPlaying
            ? t("Stop", "Стоп")
            : t("Play summary", "Слушать сводку")
    }

    private func summaryAudioButtonTitle(state: SummaryAudioState?, isGenerating: Bool) -> String {
        if isGenerating {
            return t("Creating Audio", "Создаем аудио")
        }
        if state?.isFailed == true {
            return t("Try Audio Again", "Повторить аудио")
        }
        if state?.isSucceeded == true {
            return t("Audio Ready", "Аудио готово")
        }
        return t("Create Audio", "Создать аудио")
    }

    private func summaryGenerationButtonTitle(
        isGenerating: Bool,
        failed: Bool,
        state: SummaryGenerationState?
    ) -> String {
        if isGenerating {
            return t("Generating Summary", "Генерируем сводку")
        }
        if failed || state?.isFailed == true {
            return t("Try Again", "Повторить")
        }
        return t("Generate Summary", "Сгенерировать сводку")
    }

    private func summaryGenerationStatusText(state: SummaryGenerationState?) -> String {
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

    private func summaryGenerationFailureText(state: SummaryGenerationState?) -> String {
        let message = state?.errorMessage?.trimmingCharacters(in: .whitespacesAndNewlines)
        if let message, !message.isEmpty {
            return message
        }
        return t("Summary generation failed.", "Не удалось сгенерировать сводку.")
    }

    private func fullSummaryText(_ summary: Summary, actionItems: [ActionItem]) -> String {
        let visibleActionItems = visibleSummaryActionItems(actionItems)
        var parts: [String] = []
        if let text = summary.summary { parts.append(text) }
        if let points = summary.keyPoints, !points.isEmpty {
            parts.append("\n\(t("Key Points", "Ключевые пункты")):\n" + points.map { "- \($0)" }.joined(separator: "\n"))
        }
        if !visibleActionItems.isEmpty {
            parts.append("\n\(t("Action Items", "Задачи")):\n" + visibleActionItems.map { "- \($0.task)" }.joined(separator: "\n"))
        }
        if let topics = summary.topics, !topics.isEmpty {
            parts.append("\n\(t("Topics", "Темы")): " + topics.joined(separator: ", "))
        }
        if let people = summary.peopleMentioned, !people.isEmpty {
            parts.append("\n\(t("People", "Люди")): " + people.joined(separator: ", "))
        }
        return parts.joined(separator: "\n")
    }

    private var detailRefreshKey: String {
        let status = viewModel.detail?.status.rawValue ?? "none"
        let summaryStatus = viewModel.detail?.summaryGeneration?.status ?? "none"
        let summaryStage = viewModel.detail?.summaryGeneration?.stage ?? "none"
        let audioStatus = viewModel.detail?.summaryAudio?.status ?? "none"
        let audioStage = viewModel.detail?.summaryAudio?.stage ?? "none"
        return "\(recording.id)-\(status)-\(summaryStatus)-\(summaryStage)-\(audioStatus)-\(audioStage)"
    }

    private var screenshotSelectedTab: Int {
        switch ProcessInfo.processInfo.environment["WAICOMPUTER_DETAIL_TAB"] {
        case "summary":
            return 1
        case "actions":
            return 2
        default:
            return 0
        }
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

private struct ExportShareItem: Identifiable {
    let id = UUID()
    let url: URL
}

private struct RecordingDetailInlineErrorBanner: View {
    let message: String
    let onDismiss: () -> Void
    @EnvironmentObject private var languageManager: LanguageManager

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "wifi.exclamationmark")
                .foregroundStyle(.white)

            Text(message)
                .font(.caption)
                .foregroundStyle(.white)
                .lineLimit(2)

            Spacer(minLength: 8)

            Button(action: onDismiss) {
                Image(systemName: "xmark")
                    .foregroundStyle(.white.opacity(0.9))
            }
            .buttonStyle(.plain)
            .accessibilityLabel(OnboardingL10n.text("Dismiss", "Закрыть", language: languageManager.current))
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .background(Color.orange)
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .shadow(color: .black.opacity(0.15), radius: 10, y: 4)
        .accessibilityIdentifier("recording-detail-inline-error")
    }
}

struct SummaryTabView: View {
    let summary: Summary?
    let actionItems: [ActionItem]
    var generationState: SummaryGenerationState?
    var audioState: SummaryAudioState?
    var isGenerating: Bool = false
    var isGeneratingAudio: Bool = false
    var isDownloadingAudio: Bool = false
    var isPlayingAudio: Bool = false
    let onGenerate: () -> Void
    let onGenerateAudio: () -> Void
    var onPlayAudio: () -> Void = {}
    @EnvironmentObject private var languageManager: LanguageManager
    @State private var copiedSection: String?

    private var generationFailed: Bool {
        generationState?.isFailed == true
    }

    private var isActive: Bool {
        isGenerating || generationState?.isActive == true
    }

    private var visibleActionItems: [ActionItem] {
        visibleSummaryActionItems(actionItems)
    }

    var body: some View {
        ScrollView {
            if let summary = summary {
                VStack(alignment: .leading, spacing: 16) {
                    if isActive {
                        summaryGenerationProgress
                    }

                    summaryHeader(summary)

                    VStack(alignment: .leading, spacing: 8) {
                        Button(action: onGenerateAudio) {
                            Text(summaryAudioButtonTitle)
                        }
                        .buttonStyle(WaiPrimaryButtonStyle(isDisabled: summaryAudioDisabled))
                        .disabled(summaryAudioDisabled)

                        if isGeneratingAudio {
                            summaryAudioProgress
                        } else if audioState?.isFailed == true {
                            summaryAudioFailure
                        } else if audioState?.status == "succeeded" {
                            Button(action: onPlayAudio) {
                                HStack(spacing: 6) {
                                    if isDownloadingAudio {
                                        ProgressView().controlSize(.small)
                                    } else {
                                        Image(systemName: isPlayingAudio ? "stop.fill" : "play.fill")
                                    }
                                    Text(isPlayingAudio
                                         ? t("Stop", "Стоп")
                                         : t("Play summary", "Слушать сводку"))
                                }
                            }
                            .buttonStyle(.bordered)
                            .disabled(isDownloadingAudio)
                            .accessibilityIdentifier("summary-audio-ready")
                        }
                    }

                    // Summary text
                    if let text = summary.summary {
                        SectionView(title: t("Overview", "Обзор")) {
                            Text(text)
                                .textSelection(.enabled)
                        } trailing: {
                            CopyButton(text: text, section: "summary-text", copiedSection: $copiedSection)
                        }
                    }

                    // Key points
                    if let keyPoints = summary.keyPoints, !keyPoints.isEmpty {
                        SectionView(title: t("Key Points", "Ключевые пункты")) {
                            ForEach(keyPoints, id: \.self) { point in
                                HStack(alignment: .top) {
                                    Image(systemName: "circle.fill")
                                        .font(.system(size: 6))
                                        .padding(.top, 6)
                                    Text(point)
                                        .textSelection(.enabled)
                                }
                            }
                        } trailing: {
                            CopyButton(
                                text: keyPoints.map { "- \($0)" }.joined(separator: "\n"),
                                section: "summary-points",
                                copiedSection: $copiedSection
                            )
                        }
                    }

                    if !visibleActionItems.isEmpty {
                        summaryActionItemsSection(visibleActionItems)
                    }

                    // Topics
                    if let topics = summary.topics, !topics.isEmpty {
                        SectionView(title: t("Topics", "Темы")) {
                            FlowLayout(spacing: 8) {
                                ForEach(topics, id: \.self) { topic in
                                    summaryTagPill(topic)
                                }
                            }
                        } trailing: {
                            CopyButton(
                                text: topics.joined(separator: ", "),
                                section: "summary-topics",
                                copiedSection: $copiedSection
                            )
                        }
                    }

                    // People
                    if let people = summary.peopleMentioned, !people.isEmpty {
                        SectionView(title: t("People", "Люди")) {
                            FlowLayout(spacing: 8) {
                                ForEach(people, id: \.self) { person in
                                    summaryTagPill(person, systemImage: "person.circle.fill")
                                }
                            }
                        } trailing: {
                            CopyButton(
                                text: people.joined(separator: ", "),
                                section: "summary-people",
                                copiedSection: $copiedSection
                            )
                        }
                    }
                }
                .padding(24)
            } else {
                ContentUnavailableView(
                    t("No Summary", "Нет сводки"),
                    systemImage: "text.alignleft",
                    description: Text(t(
                        "Generate a summary to see key points and action items",
                        "Сгенерируй сводку, чтобы увидеть ключевые пункты и задачи"
                    ))
                )
                .overlay(alignment: .bottom) {
                    VStack(spacing: 12) {
                        Button(action: onGenerate) {
                            Text(summaryButtonTitle)
                        }
                        .buttonStyle(WaiPrimaryButtonStyle(isDisabled: isActive))
                        .disabled(isActive)

                        if isActive {
                            summaryGenerationProgress
                        } else if generationFailed {
                            summaryGenerationFailure
                        }
                    }
                    .padding(.bottom, 32)
                }
            }
        }
    }

    private func summaryActionItemsSection(_ actionItems: [ActionItem]) -> some View {
        SectionView(title: t("Action Items", "Задачи")) {
            VStack(alignment: .leading, spacing: Spacing.sm) {
                ForEach(actionItems) { item in
                    RecordingDetailActionItemRow(item: item)
                }
            }
        } trailing: {
            CopyButton(
                text: actionItems.map { "- \($0.task)" }.joined(separator: "\n"),
                section: "summary-action-items",
                copiedSection: $copiedSection
            )
        }
        .accessibilityIdentifier("summary-action-items")
    }

    private func summaryTagPill(_ text: String, systemImage: String? = nil) -> some View {
        HStack(spacing: Spacing.xs) {
            if let systemImage {
                Image(systemName: systemImage)
            }
            Text(text)
        }
        .font(Typography.labelSmall)
        .foregroundStyle(Palette.textSecondary)
        .padding(.horizontal, Spacing.sm)
        .padding(.vertical, 4)
        .background(Palette.surfaceSubtle)
        .clipShape(Capsule())
    }

    private func summaryHeader(_ summary: Summary) -> some View {
        HStack(alignment: .center, spacing: Spacing.md) {
            Label(t("Summary", "Сводка"), systemImage: "doc.text.magnifyingglass")
                .waiSectionHeader()
            Spacer()
            Button {
                UIPasteboard.general.string = fullSummaryText(summary, actionItems: actionItems)
                copiedSection = "summary-all"
                Task {
                    try? await Task.sleep(for: .seconds(1.5))
                    if copiedSection == "summary-all" {
                        copiedSection = nil
                    }
                }
            } label: {
                Label(copiedSection == "summary-all" ? t("Copied", "Скопировано") : t("Copy Summary", "Скопировать сводку"), systemImage: copiedSection == "summary-all" ? "checkmark" : "doc.on.doc")
            }
            .buttonStyle(.bordered)
            .tint(Palette.accent)
            .fixedSize()
            .accessibilityIdentifier("summary-copy-menu")
            .accessibilityLabel(t("Copy Summary", "Скопировать сводку"))
        }
    }

    private var summaryButtonTitle: String {
        if isActive {
            return t("Generating Summary", "Генерируем сводку")
        }
        if generationFailed {
            return t("Try Again", "Повторить")
        }
        return t("Generate Summary", "Сгенерировать сводку")
    }

    private var summaryAudioDisabled: Bool {
        isGeneratingAudio || audioState?.status == "succeeded"
    }

    private var summaryAudioButtonTitle: String {
        if isGeneratingAudio {
            return t("Creating Audio", "Создаем аудио")
        }
        if audioState?.status == "failed" {
            return t("Try Audio Again", "Повторить аудио")
        }
        if audioState?.status == "succeeded" {
            return t("Audio Ready", "Аудио готово")
        }
        return t("Create Audio", "Создать аудио")
    }

    private var summaryAudioProgress: some View {
        HStack(spacing: 8) {
            ProgressView()
                .controlSize(.small)
            Text(audioState?.message ?? t("Creating summary audio...", "Создаем аудио сводки..."))
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(Palette.recording.opacity(0.10))
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .accessibilityIdentifier("summary-audio-progress")
    }

    private var summaryAudioFailure: some View {
        Text(audioState?.errorMessage ?? t("Summary audio generation failed.", "Не удалось создать аудио сводки."))
            .font(.caption)
            .foregroundStyle(Palette.recording)
            .multilineTextAlignment(.leading)
            .fixedSize(horizontal: false, vertical: true)
            .accessibilityIdentifier("summary-audio-failure")
    }

    private var summaryGenerationProgress: some View {
        HStack(spacing: 8) {
            ProgressView()
                .controlSize(.small)
            Text(summaryGenerationStatusText)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(Palette.recording.opacity(0.10))
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .accessibilityIdentifier("summary-generation-progress")
    }

    private var summaryGenerationFailure: some View {
        Text(summaryGenerationFailureText)
            .font(.caption)
            .foregroundStyle(Palette.recording)
            .multilineTextAlignment(.center)
            .fixedSize(horizontal: false, vertical: true)
            .accessibilityIdentifier("summary-generation-failure")
    }

    private var summaryGenerationStatusText: String {
        guard let state = generationState else {
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

    private var summaryGenerationFailureText: String {
        let message = generationState?.errorMessage?.trimmingCharacters(in: .whitespacesAndNewlines)
        if let message, !message.isEmpty {
            return message
        }
        return t("Summary generation failed.", "Не удалось сгенерировать сводку.")
    }

    private func fullSummaryText(_ summary: Summary, actionItems: [ActionItem]) -> String {
        let visibleActionItems = visibleSummaryActionItems(actionItems)
        var parts: [String] = []
        if let text = summary.summary { parts.append(text) }
        if let points = summary.keyPoints, !points.isEmpty {
            parts.append("\n\(t("Key Points", "Ключевые пункты")):\n" + points.map { "- \($0)" }.joined(separator: "\n"))
        }
        if !visibleActionItems.isEmpty {
            parts.append("\n\(t("Action Items", "Задачи")):\n" + visibleActionItems.map { "- \($0.task)" }.joined(separator: "\n"))
        }
        if let topics = summary.topics, !topics.isEmpty {
            parts.append("\n\(t("Topics", "Темы")): " + topics.joined(separator: ", "))
        }
        if let people = summary.peopleMentioned, !people.isEmpty {
            parts.append("\n\(t("People", "Люди")): " + people.joined(separator: ", "))
        }
        return parts.joined(separator: "\n")
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

struct ActionItemsTabView: View {
    let actionItems: [ActionItem]
    @EnvironmentObject private var languageManager: LanguageManager
    @State private var copiedSection: String?

    private var visibleActionItems: [ActionItem] {
        visibleSummaryActionItems(actionItems)
    }

    var body: some View {
        if visibleActionItems.isEmpty {
            ContentUnavailableView(
                t("No Action Items", "Нет задач"),
                systemImage: "checklist",
                description: Text(t(
                    "Action items will appear here after generating a summary",
                    "Задачи появятся здесь после генерации сводки"
                ))
            )
        } else {
            ScrollView {
                VStack(alignment: .leading, spacing: Spacing.lg) {
                    SectionView(title: t("Action Items", "Задачи")) {
                        VStack(alignment: .leading, spacing: Spacing.sm) {
                            ForEach(visibleActionItems) { item in
                                RecordingDetailActionItemRow(item: item)
                            }
                        }
                    } trailing: {
                        CopyButton(
                            text: visibleActionItems.map { "- \($0.task)" }.joined(separator: "\n"),
                            section: "actions-tab-action-items",
                            copiedSection: $copiedSection
                        )
                    }
                }
                .padding(24)
                .frame(maxWidth: .infinity, alignment: .topLeading)
            }
            .accessibilityIdentifier("recording-detail-actions-tab")
        }
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

struct RecordingDetailActionItemRow: View {
    let item: ActionItem

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: Spacing.sm) {
            Image(systemName: item.status == .completed ? "checkmark.circle.fill" : "checkmark.circle")
                .font(Typography.bodySmall)
                .foregroundStyle(Palette.accent)

            VStack(alignment: .leading, spacing: Spacing.xs) {
                Text(item.task)
                    .strikethrough(item.status == .completed)
                    .font(Typography.reading)
                    .lineSpacing(6)
                    .foregroundStyle(Palette.textPrimary)
                    .textSelection(.enabled)

                if item.owner != nil || item.priority != nil {
                    HStack(spacing: Spacing.sm) {
                        if let owner = item.owner {
                            Label(owner, systemImage: "person")
                                .font(Typography.caption)
                                .foregroundStyle(Palette.textSecondary)
                        }

                        if let priority = item.priority {
                            PriorityBadge(priority: priority)
                        }
                    }
                }
            }
        }
    }
}

struct PriorityBadge: View {
    let priority: ActionItem.Priority

    var body: some View {
        Text(priority.rawValue.capitalized)
            .font(.caption2)
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(backgroundColor)
            .foregroundStyle(foregroundColor)
            .cornerRadius(4)
    }

    private var backgroundColor: Color {
        switch priority {
        case .high: return .red.opacity(0.2)
        case .medium: return .orange.opacity(0.2)
        case .low: return .gray.opacity(0.2)
        }
    }

    private var foregroundColor: Color {
        switch priority {
        case .high: return .red
        case .medium: return .orange
        case .low: return .gray
        }
    }
}

struct SectionView<Content: View, Trailing: View>: View {
    let title: String
    @ViewBuilder let content: Content
    @ViewBuilder let trailing: Trailing

    init(title: String, @ViewBuilder content: () -> Content, @ViewBuilder trailing: () -> Trailing) {
        self.title = title
        self.content = content()
        self.trailing = trailing()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(title)
                    .font(.headline)
                Spacer()
                trailing
            }
            content
        }
    }
}

extension SectionView where Trailing == EmptyView {
    init(title: String, @ViewBuilder content: () -> Content) {
        self.title = title
        self.content = content()
        self.trailing = EmptyView()
    }
}

struct CopyButton: View {
    let text: String
    let section: String
    @Binding var copiedSection: String?

    var body: some View {
        Button {
            UIPasteboard.general.string = text
            copiedSection = section
            Task {
                try? await Task.sleep(for: .seconds(1.5))
                if copiedSection == section {
                    copiedSection = nil
                }
            }
        } label: {
            Image(systemName: copiedSection == section ? "checkmark" : "doc.on.doc")
                .font(.caption)
                .foregroundStyle(copiedSection == section ? .orange : .secondary)
        }
    }
}

struct FlowLayout: Layout {
    var spacing: CGFloat = 8

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let result = FlowResult(in: proposal.width ?? 0, subviews: subviews, spacing: spacing)
        return result.size
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let result = FlowResult(in: bounds.width, subviews: subviews, spacing: spacing)
        for (index, subview) in subviews.enumerated() {
            subview.place(at: CGPoint(x: bounds.minX + result.positions[index].x, y: bounds.minY + result.positions[index].y), proposal: .unspecified)
        }
    }

    struct FlowResult {
        var size: CGSize = .zero
        var positions: [CGPoint] = []

        init(in maxWidth: CGFloat, subviews: Subviews, spacing: CGFloat) {
            var x: CGFloat = 0
            var y: CGFloat = 0
            var rowHeight: CGFloat = 0

            for subview in subviews {
                let size = subview.sizeThatFits(.unspecified)
                if x + size.width > maxWidth && x > 0 {
                    x = 0
                    y += rowHeight + spacing
                    rowHeight = 0
                }
                positions.append(CGPoint(x: x, y: y))
                x += size.width + spacing
                rowHeight = max(rowHeight, size.height)
            }

            size = CGSize(width: maxWidth, height: y + rowHeight)
        }
    }
}

#Preview {
    NavigationStack {
        RecordingDetailView(recording: Recording(
            id: "test",
            title: "Test Recording",
            type: .meeting,
            createdAt: Date()
        ))
        .environmentObject(AppState())
        .environmentObject(LanguageManager.shared)
    }
}
