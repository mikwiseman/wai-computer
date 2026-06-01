import SwiftUI
import UniformTypeIdentifiers
import WaiComputerKit

struct RecordingDetailView: View {
    @EnvironmentObject var appState: AppState
    @EnvironmentObject private var languageManager: LanguageManager
    @Environment(\.dismiss) private var dismiss
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
    @State private var shareLinkURL: URL?
    @State private var isExporting = false
    @State private var isSharing = false

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
                    generationState: viewModel.detail?.summaryGeneration,
                    isGenerating: isGeneratingSummary,
                    onGenerate: {
                        Task {
                            await viewModel.startSummaryGeneration(
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
        .overlay {
            if viewModel.isLoading {
                ProgressView()
            }
        }
    }

    private var isGeneratingSummary: Bool {
        viewModel.isGeneratingSummary(for: recording.id)
            || viewModel.detail?.summaryGeneration?.isActive == true
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
                    Button {
                        onRestore?()
                        dismiss()
                    } label: {
                        Label(t("Restore", "Восстановить"), systemImage: "arrow.uturn.backward")
                    }

                    Button(role: .destructive) {
                        showDeleteConfirmation = true
                    } label: {
                        Label(t("Delete Permanently", "Удалить навсегда"), systemImage: "trash.slash")
                    }
                } else {
                    Button {
                        renameDraft = viewModel.detail?.title ?? recording.title ?? ""
                        showRenameAlert = true
                    } label: {
                        Label(t("Rename", "Переименовать"), systemImage: "pencil")
                    }

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
                            Task { await runExport(format: "srt") }
                        } label: {
                            Label(t("Subtitles (.srt)", "Субтитры (.srt)"), systemImage: "captions.bubble")
                        }
                    } label: {
                        Label(t("Export", "Экспорт"), systemImage: "square.and.arrow.down")
                    }

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

                    Button(role: .destructive) {
                        showDeleteConfirmation = true
                    } label: {
                        Label(t("Move to Trash", "Переместить в корзину"), systemImage: "trash")
                    }
                }
            } label: {
                Image(systemName: "ellipsis.circle")
            }
        }
    }

    // MARK: - Export / Share

    private func runExport(format: String) async {
        guard !isExporting else { return }
        isExporting = true
        defer { isExporting = false }

        guard let content = await viewModel.exportRecording(
            format: format,
            locale: exportLocale,
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

    private var detailRefreshKey: String {
        let status = viewModel.detail?.status.rawValue ?? "none"
        let summaryStatus = viewModel.detail?.summaryGeneration?.status ?? "none"
        let summaryStage = viewModel.detail?.summaryGeneration?.stage ?? "none"
        return "\(recording.id)-\(status)-\(summaryStatus)-\(summaryStage)"
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
    var generationState: SummaryGenerationState?
    var isGenerating: Bool = false
    let onGenerate: () -> Void
    @EnvironmentObject private var languageManager: LanguageManager
    @State private var copiedSection: String?

    private var generationFailed: Bool {
        generationState?.isFailed == true
    }

    private var isActive: Bool {
        isGenerating || generationState?.isActive == true
    }

    var body: some View {
        ScrollView {
            if let summary = summary {
                VStack(alignment: .leading, spacing: 16) {
                    if isActive {
                        summaryGenerationProgress
                    }

                    // Copy all summary
                    HStack {
                        Spacer()
                        CopyButton(
                            text: fullSummaryText(summary),
                            section: "summary-all",
                            copiedSection: $copiedSection
                        )
                    }

                    // Summary text
                    if let text = summary.summary {
                        SectionView(title: t("Summary", "Сводка")) {
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

                    // Topics
                    if let topics = summary.topics, !topics.isEmpty {
                        SectionView(title: t("Topics", "Темы")) {
                            FlowLayout(spacing: 8) {
                                ForEach(topics, id: \.self) { topic in
                                    Text(topic)
                                        .font(.caption)
                                        .padding(.horizontal, 12)
                                        .padding(.vertical, 6)
                                        .background(Color.blue.opacity(0.1))
                                        .cornerRadius(16)
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
                        SectionView(title: t("People Mentioned", "Упомянутые люди")) {
                            FlowLayout(spacing: 8) {
                                ForEach(people, id: \.self) { person in
                                    HStack {
                                        Image(systemName: "person.circle.fill")
                                        Text(person)
                                    }
                                    .font(.caption)
                                    .padding(.horizontal, 12)
                                    .padding(.vertical, 6)
                                    .background(Color.gray.opacity(0.1))
                                    .cornerRadius(16)
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

    private var summaryButtonTitle: String {
        if isActive {
            return t("Generating Summary", "Генерируем сводку")
        }
        if generationFailed {
            return t("Try Again", "Повторить")
        }
        return t("Generate Summary", "Сгенерировать сводку")
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

    private func fullSummaryText(_ summary: Summary) -> String {
        var parts: [String] = []
        if let text = summary.summary { parts.append(text) }
        if let points = summary.keyPoints, !points.isEmpty {
            parts.append("\n\(t("Key Points", "Ключевые пункты")):\n" + points.map { "- \($0)" }.joined(separator: "\n"))
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

    var body: some View {
        if actionItems.isEmpty {
            ContentUnavailableView(
                t("No Action Items", "Нет задач"),
                systemImage: "checklist",
                description: Text(t(
                    "Action items will appear here after generating a summary",
                    "Задачи появятся здесь после генерации сводки"
                ))
            )
        } else {
            List(actionItems) { item in
                VStack(alignment: .leading, spacing: 4) {
                    HStack {
                        Image(systemName: item.status == .completed ? "checkmark.circle.fill" : "circle")
                            .foregroundStyle(item.status == .completed ? .green : .gray)

                        Text(item.task)
                            .strikethrough(item.status == .completed)
                    }

                    HStack {
                        if let owner = item.owner {
                            Label(owner, systemImage: "person")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }

                        if let priority = item.priority {
                            PriorityBadge(priority: priority)
                        }
                    }
                }
            }
        }
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
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
