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
                ProgressView("Loading...")
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if let error = viewModel.error {
                ContentUnavailableView(
                    "Error",
                    systemImage: "exclamationmark.triangle",
                    description: Text(error)
                )
            } else if let detail = viewModel.recordingDetail {
                VStack(spacing: 0) {
                    detailHeader(detail)

                    WaiDivider()

                    WaiTabBar(
                        tabs: [
                            ("Transcript", MacRecordingDetailViewModel.Tab.transcript),
                            ("Summary", MacRecordingDetailViewModel.Tab.summary),
                            (
                                detail.actionItems.isEmpty
                                    ? "Action Items"
                                    : "Action Items (\(detail.actionItems.count))",
                                MacRecordingDetailViewModel.Tab.actions
                            ),
                        ],
                        selection: $viewModel.selectedTab
                    )

                    WaiDivider()

                    switch viewModel.selectedTab {
                    case .transcript:
                        MacTranscriptView(
                            segments: detail.segments,
                            recordingId: detail.id,
                            onAssigned: { updated in
                                viewModel.recordingDetail = updated
                            }
                        )
                    case .summary:
                        summaryTab(detail)
                    case .actions:
                        actionsTab(detail)
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
                    "Recording Not Found",
                    systemImage: "doc.questionmark",
                    description: Text("Unable to load this recording.")
                )
            }
        }
        .onAppear {
            loadTask?.cancel()
            loadTask = Task {
                await viewModel.load(
                    recordingId: recordingId,
                    apiClient: appState.getAPIClient(),
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
                await viewModel.load(
                    recordingId: newId,
                    apiClient: appState.getAPIClient(),
                    showLoading: viewModel.recordingDetail?.id != newId
                )
            }
        }
        .task(id: detailRefreshKey) {
            await viewModel.refreshPendingDetailIfNeeded(
                recordingId: recordingId,
                apiClient: appState.getAPIClient()
            )
        }
        .onReceive(NotificationCenter.default.publisher(for: .pendingRecordingSyncDidFinish)) { notification in
            guard let syncedRecordingId = notification.userInfo?["recordingId"] as? String,
                  syncedRecordingId == recordingId else {
                return
            }
            loadTask?.cancel()
            loadTask = Task {
                await viewModel.load(
                    recordingId: recordingId,
                    apiClient: appState.getAPIClient(),
                    showLoading: false
                )
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
        .help(copiedSection == section ? "Copied!" : title)
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
        HStack {
            VStack(alignment: .leading, spacing: Spacing.xs) {
                if isEditingTitle && mode == .active {
                    TextField("Title", text: $titleDraft)
                        .textFieldStyle(.plain)
                        .font(Typography.displayMedium)
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
                    Text(detail.title ?? "Untitled")
                        .font(Typography.displayMedium)
                        .accessibilityElement(children: .ignore)
                        .accessibilityIdentifier("recording-title")
                        .contentShape(Rectangle())
                        .onTapGesture(count: 2) {
                            guard mode == .active else { return }
                            startTitleEdit(currentTitle: detail.title)
                        }
                        .help(mode == .active ? "Double-click to rename" : "")
                }

                HStack(spacing: Spacing.sm) {
                    Text(detail.type.rawValue.capitalized)
                        .font(Typography.label)
                        .foregroundStyle(Palette.typeColor(detail.type))

                    Text(detail.createdAt.formatted(date: .long, time: .shortened))
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
            }

            Spacer()

            HStack(spacing: Spacing.md) {
                // Export dropdown
                if mode == .active {
                    Menu {
                        Button("Export Markdown (.md)") {
                            Task { await exportRecording(format: "markdown") }
                        }
                        Button("Export Plain Text (.txt)") {
                            Task { await exportRecording(format: "txt") }
                        }
                        Button("Export Subtitles (.srt)") {
                            Task { await exportRecording(format: "srt") }
                        }
                    } label: {
                        Label("Export", systemImage: "square.and.arrow.down")
                    }
                    .buttonStyle(WaiGhostButtonStyle())
                    .help("Export Recording")
                }

                if mode == .active {
                    Button {
                        Task {
                            await shareRecording(detail)
                        }
                    } label: {
                        Label(
                            copiedSection == "share-link" ? "Copied" : "Share",
                            systemImage: copiedSection == "share-link" ? "checkmark" : "square.and.arrow.up"
                        )
                    }
                    .buttonStyle(WaiGhostButtonStyle())
                    .help("Create a web share link")
                    .disabled(isSharing)
                }

                if mode == .active {
                    Menu {
                        Button("Unfiled") {
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
                        Image(systemName: "folder")
                            .foregroundStyle(Palette.textSecondary)
                    }
                    .buttonStyle(.plain)
                    .help("Move to Folder")
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
                    .help("Restore Recording")
                }

                Button {
                    showDeleteConfirmation = true
                } label: {
                    Image(systemName: mode == .trash ? "trash.slash" : "trash")
                        .foregroundStyle(mode == .trash ? Palette.recording : Palette.textSecondary)
                }
                .buttonStyle(.plain)
                .help(mode == .trash ? "Delete Permanently" : "Move to Trash")
                .confirmationDialog(
                    mode == .trash ? "Delete this recording permanently?" : "Move this recording to trash?",
                    isPresented: $showDeleteConfirmation
                ) {
                    Button(mode == .trash ? "Delete Permanently" : "Move to Trash", role: .destructive) {
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
                    Button("Cancel", role: .cancel) {}
                } message: {
                    Text(
                        mode == .trash
                            ? "This action cannot be undone."
                            : "You can restore it later from Trash."
                    )
                }
            }
        }
        .padding(Spacing.lg)
    }

    private func fullSummaryText(_ summary: Summary) -> String {
        var parts: [String] = []
        if let text = summary.summary { parts.append(text) }
        if let points = summary.keyPoints, !points.isEmpty {
            parts.append("\nKey Points:\n" + points.map { "— \($0)" }.joined(separator: "\n"))
        }
        if let topics = summary.topics, !topics.isEmpty {
            parts.append("\nTopics: " + topics.joined(separator: ", "))
        }
        if let people = summary.peopleMentioned, !people.isEmpty {
            parts.append("\nPeople: " + people.joined(separator: ", "))
        }
        return parts.joined(separator: "\n")
    }

    private func actionItemsText(_ items: [ActionItem]) -> String {
        items.enumerated().map { index, item in
            var lines = ["\(index + 1). \(item.task)"]
            lines.append("Status: \(actionItemStatusLabel(item.status))")

            if let owner = item.owner, !owner.isEmpty {
                lines.append("Owner: \(owner)")
            }
            if let dueDate = item.dueDate, !dueDate.isEmpty {
                lines.append("Due: \(dueDate)")
            }
            if let priority = item.priority {
                lines.append("Priority: \(priority.rawValue.capitalized)")
            }

            return lines.joined(separator: "\n")
        }
        .joined(separator: "\n\n")
    }

    private func actionItemStatusLabel(_ status: ActionItem.Status) -> String {
        switch status {
        case .pending:
            return "Pending"
        case .inProgress:
            return "In Progress"
        case .completed:
            return "Completed"
        case .cancelled:
            return "Cancelled"
        }
    }

    @ViewBuilder
    private func summaryTab(_ detail: RecordingDetail) -> some View {
        if let summary = detail.summary {
            ScrollView {
                VStack(alignment: .leading, spacing: Spacing.xl) {
                    HStack {
                        Text("Summary")
                            .waiSectionHeader()
                        Spacer()
                        copyActionButton(
                            title: "Copy Summary",
                            copiedTitle: "Copied",
                            text: fullSummaryText(summary),
                            section: "summary-all"
                        )
                    }

                    if let text = summary.summary {
                        VStack(alignment: .leading, spacing: Spacing.sm) {
                            Text("Overview")
                                .waiSectionHeader()
                            Text(text)
                                .font(Typography.reading)
                                .lineSpacing(6)
                                .textSelection(.enabled)
                        }
                    }

                    if let points = summary.keyPoints, !points.isEmpty {
                        VStack(alignment: .leading, spacing: Spacing.sm) {
                            Text("Key Points")
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
                            Text("Topics")
                                .waiSectionHeader()
                            Text(topics.joined(separator: " \u{00B7} "))
                                .font(Typography.body)
                                .foregroundStyle(Palette.textSecondary)
                                .textSelection(.enabled)
                        }
                    }

                    if let people = summary.peopleMentioned, !people.isEmpty {
                        VStack(alignment: .leading, spacing: Spacing.sm) {
                            Text("People")
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
                    "No Summary",
                    systemImage: "doc.text",
                    description: Text("Generate a summary to see key points and insights.")
                )

                Button(action: {
                    Task {
                        await viewModel.generateSummary(apiClient: appState.getAPIClient())
                    }
                }) {
                    Text("Generate Summary")
                }
                .buttonStyle(WaiPrimaryButtonStyle(isDisabled: viewModel.isGeneratingSummary))
                .disabled(viewModel.isGeneratingSummary)

                if viewModel.isGeneratingSummary {
                    ProgressView("Generating summary...")
                }
                Spacer()
            }
            .accessibilityIdentifier("summary-empty-state")
        }
    }

    @ViewBuilder
    private func actionsTab(_ detail: RecordingDetail) -> some View {
        if !detail.actionItems.isEmpty {
            ScrollView {
                VStack(alignment: .leading, spacing: Spacing.xl) {
                    HStack {
                        Text("Action Items")
                            .waiSectionHeader()
                        Spacer()
                        copyActionButton(
                            title: "Copy Action Items",
                            copiedTitle: "Copied",
                            text: actionItemsText(detail.actionItems),
                            section: "action-items"
                        )
                    }

                    ForEach(detail.actionItems) { item in
                        ActionItemCard(item: item) { newStatus in
                            Task {
                                await viewModel.updateActionItemStatus(
                                    id: item.id,
                                    status: newStatus,
                                    apiClient: appState.getAPIClient()
                                )
                            }
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(Spacing.lg)
            }
            .accessibilityIdentifier("actions-content")
        } else if detail.summary != nil {
            VStack {
                Spacer().frame(height: Spacing.xxxl)
                ContentUnavailableView(
                    "No Action Items Found",
                    systemImage: "checklist",
                    description: Text("This summary did not include any concrete follow-ups.")
                )
                Spacer()
            }
            .accessibilityIdentifier("actions-empty-state")
        } else {
            VStack(spacing: Spacing.lg) {
                Spacer().frame(height: Spacing.xxxl)
                ContentUnavailableView(
                    "No Action Items",
                    systemImage: "checklist",
                    description: Text("Generate a summary first to extract action items.")
                )

                Button(action: {
                    Task {
                        await viewModel.generateSummary(apiClient: appState.getAPIClient())
                    }
                }) {
                    Text("Generate Summary")
                }
                .buttonStyle(WaiPrimaryButtonStyle(isDisabled: viewModel.isGeneratingSummary))
                .disabled(viewModel.isGeneratingSummary)
                Spacer()
            }
            .accessibilityIdentifier("actions-empty-state")
        }
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

struct ActionItemCard: View {
    let item: ActionItem
    let onStatusChange: (ActionItem.Status) -> Void

    var body: some View {
        HStack(alignment: .top, spacing: Spacing.md) {
            Button {
                let newStatus: ActionItem.Status = item.status == .completed ? .pending : .completed
                onStatusChange(newStatus)
            } label: {
                Image(systemName: item.status == .completed ? "checkmark.circle.fill" : "circle")
                    .foregroundStyle(item.status == .completed ? Palette.accent : Palette.textSecondary)
                    .font(Typography.headingLarge)
                    .padding(.top, Spacing.xxs)
            }
            .buttonStyle(.plain)

            VStack(alignment: .leading, spacing: Spacing.md) {
                Text(item.task)
                    .font(Typography.reading)
                    .lineSpacing(5)
                    .strikethrough(item.status == .completed)
                    .foregroundStyle(item.status == .completed ? Palette.textSecondary : Palette.textPrimary)
                    .textSelection(.enabled)

                HStack(spacing: Spacing.sm) {
                    if let owner = item.owner, !owner.isEmpty {
                        metadataBadge(owner, color: Palette.textSecondary)
                    }

                    if let dueDate = item.dueDate, !dueDate.isEmpty {
                        metadataBadge(dueDate, color: Palette.textSecondary)
                    }

                    if let priority = item.priority {
                        metadataBadge(priority.rawValue.capitalized, color: priorityColor(priority))
                    }

                    metadataBadge(statusLabel, color: statusColor)
                }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .waiCard()
    }

    private func priorityColor(_ priority: ActionItem.Priority) -> Color {
        switch priority {
        case .high: return Palette.priorityHigh
        case .medium: return Palette.priorityMedium
        case .low: return Palette.priorityLow
        }
    }

    private var statusLabel: String {
        switch item.status {
        case .pending:
            return "Pending"
        case .inProgress:
            return "In Progress"
        case .completed:
            return "Completed"
        case .cancelled:
            return "Cancelled"
        }
    }

    private var statusColor: Color {
        switch item.status {
        case .completed:
            return Palette.accent
        case .inProgress:
            return Palette.priorityMedium
        case .cancelled:
            return Palette.textTertiary
        case .pending:
            return Palette.textSecondary
        }
    }

    private func metadataBadge(_ text: String, color: Color) -> some View {
        Text(text)
            .font(Typography.label)
            .foregroundStyle(color)
            .padding(.horizontal, Spacing.sm)
            .padding(.vertical, Spacing.xs)
            .background(Palette.surfaceSubtle)
            .clipShape(Capsule())
    }
}

// MARK: - ViewModel

@MainActor
class MacRecordingDetailViewModel: ObservableObject {
    enum Tab: Hashable {
        case transcript, summary, actions
    }

    @Published var recordingDetail: RecordingDetail?
    @Published var isLoading = false
    @Published var error: String?
    @Published var selectedTab: Tab = .transcript
    @Published var isGeneratingSummary = false

    private var loadGeneration = 0

    init(initialDetail: RecordingDetail? = nil) {
        recordingDetail = initialDetail
    }

    func load(recordingId: String, apiClient: APIClient, showLoading: Bool = true) async {
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
            let detail = try await apiClient.getRecording(id: recordingId)
            guard generation == loadGeneration else { return }
            recordingDetail = detail
        } catch {
            guard generation == loadGeneration else { return }
            if recordingDetail?.id != recordingId {
                self.error = error.userFacingMessage(context: .library)
            }
        }
    }

    func refreshPendingDetailIfNeeded(recordingId: String, apiClient: APIClient) async {
        guard recordingDetail?.id == recordingId else { return }
        guard shouldAutoRefresh(for: recordingDetail?.status) else { return }

        while !Task.isCancelled,
              recordingDetail?.id == recordingId,
              shouldAutoRefresh(for: recordingDetail?.status) {
            try? await Task.sleep(for: .seconds(recordingDetail?.status == .processing ? 4 : 2))
            guard !Task.isCancelled else { return }
            await load(recordingId: recordingId, apiClient: apiClient, showLoading: false)
        }
    }

    func generateSummary(apiClient: APIClient) async {
        guard let id = recordingDetail?.id else { return }
        isGeneratingSummary = true

        do {
            _ = try await apiClient.generateSummary(recordingId: id)
            let detail = try await apiClient.getRecording(id: id)
            recordingDetail = detail
            selectedTab = detail.actionItems.isEmpty ? .summary : .actions
        } catch {
            self.error = error.userFacingMessage(context: .library)
        }

        isGeneratingSummary = false
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

    func updateActionItemStatus(id: String, status: ActionItem.Status, apiClient: APIClient) async {
        do {
            _ = try await apiClient.updateActionItem(id: id, status: status)
            if let recordingId = recordingDetail?.id {
                recordingDetail = try await apiClient.getRecording(id: recordingId)
            }
        } catch {
            self.error = error.userFacingMessage(context: .library)
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
