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
    @EnvironmentObject var appState: MacAppState
    @StateObject private var viewModel: MacRecordingDetailViewModel
    @State private var showDeleteConfirmation = false
    @State private var loadTask: Task<Void, Never>?

    init(
        recordingId: String,
        initialDetail: RecordingDetail? = nil,
        mode: Mode = .active,
        folders: [Folder] = [],
        onDelete: (() -> Void)? = nil,
        onRestore: (() -> Void)? = nil,
        onMoveToFolder: ((String?) -> Void)? = nil
    ) {
        self.recordingId = recordingId
        self.mode = mode
        self.folders = folders
        self.onDelete = onDelete
        self.onRestore = onRestore
        self.onMoveToFolder = onMoveToFolder
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
                        MacTranscriptView(segments: detail.segments)
                    case .summary:
                        summaryTab(detail)
                    case .actions:
                        actionsTab(detail)
                    }
                }
                .accessibilityElement(children: .contain)
                .accessibilityIdentifier("recording-detail-root")
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
    }

    private func detailHeader(_ detail: RecordingDetail) -> some View {
        HStack {
            VStack(alignment: .leading, spacing: Spacing.xs) {
                Text(detail.title ?? "Untitled")
                    .font(Typography.displayMedium)
                    .accessibilityElement(children: .ignore)
                    .accessibilityIdentifier("recording-title")

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

    @ViewBuilder
    private func summaryTab(_ detail: RecordingDetail) -> some View {
        if let summary = detail.summary {
            ScrollView {
                VStack(alignment: .leading, spacing: Spacing.xl) {
                    // Summary text
                    if let text = summary.summary {
                        VStack(alignment: .leading, spacing: Spacing.sm) {
                            Text("Summary")
                                .waiSectionHeader()
                            Text(text)
                                .font(Typography.reading)
                                .lineSpacing(6)
                                .textSelection(.enabled)
                        }
                    }

                    // Key points — em dash prefix
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
                                }
                            }
                        }
                    }

                    // Topics — middle-dot separated inline text
                    if let topics = summary.topics, !topics.isEmpty {
                        VStack(alignment: .leading, spacing: Spacing.sm) {
                            Text("Topics")
                                .waiSectionHeader()
                            Text(topics.joined(separator: " \u{00B7} "))
                                .font(Typography.body)
                                .foregroundStyle(Palette.textSecondary)
                        }
                    }

                    // People mentioned — comma-separated
                    if let people = summary.peopleMentioned, !people.isEmpty {
                        VStack(alignment: .leading, spacing: Spacing.sm) {
                            Text("People")
                                .waiSectionHeader()
                            Text(people.joined(separator: ", "))
                                .font(Typography.body)
                                .foregroundStyle(Palette.textSecondary)
                        }
                    }
                }
                .padding(Spacing.lg)
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
                    Text("Action Items")
                        .waiSectionHeader()

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

    init(initialDetail: RecordingDetail? = nil) {
        recordingDetail = initialDetail
    }

    func load(recordingId: String, apiClient: APIClient, showLoading: Bool = true) async {
        if showLoading {
            isLoading = true
        }
        error = nil

        do {
            recordingDetail = try await apiClient.getRecording(id: recordingId)
        } catch {
            if recordingDetail?.id != recordingId {
                self.error = error.localizedDescription
            }
        }

        if showLoading {
            isLoading = false
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
            self.error = error.localizedDescription
        }

        isGeneratingSummary = false
    }

    func deleteRecording(apiClient: APIClient, permanent: Bool = false) async -> Bool {
        guard let id = recordingDetail?.id else { return false }
        do {
            try await apiClient.deleteRecording(id: id, permanent: permanent)
            return true
        } catch {
            self.error = error.localizedDescription
            return false
        }
    }

    func restoreRecording(apiClient: APIClient) async -> Bool {
        guard let id = recordingDetail?.id else { return false }
        do {
            _ = try await apiClient.restoreRecording(id: id)
            return true
        } catch {
            self.error = error.localizedDescription
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
            self.error = error.localizedDescription
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
            self.error = error.localizedDescription
        }
    }
}
