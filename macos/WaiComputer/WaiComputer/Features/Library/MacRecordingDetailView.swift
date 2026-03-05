import SwiftUI
import WaiComputerKit

struct MacRecordingDetailView: View {
    let recordingId: String
    var onDelete: (() -> Void)?
    @EnvironmentObject var appState: MacAppState
    @StateObject private var viewModel = MacRecordingDetailViewModel()
    @State private var showDeleteConfirmation = false

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
                            ("Action Items", MacRecordingDetailViewModel.Tab.actions),
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
            } else {
                ContentUnavailableView(
                    "Recording Not Found",
                    systemImage: "doc.questionmark",
                    description: Text("Unable to load this recording.")
                )
            }
        }
        .task {
            await viewModel.load(recordingId: recordingId, apiClient: appState.getAPIClient())
        }
        .onChange(of: recordingId) { _, newId in
            Task {
                await viewModel.load(recordingId: newId, apiClient: appState.getAPIClient())
            }
        }
    }

    private func detailHeader(_ detail: RecordingDetail) -> some View {
        HStack {
            VStack(alignment: .leading, spacing: Spacing.xs) {
                Text(detail.title ?? "Untitled")
                    .font(Typography.displayMedium)

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

            Button {
                showDeleteConfirmation = true
            } label: {
                Image(systemName: "trash")
                    .foregroundStyle(Palette.textSecondary)
            }
            .buttonStyle(.plain)
            .help("Delete Recording")
            .confirmationDialog(
                "Delete this recording?",
                isPresented: $showDeleteConfirmation
            ) {
                Button("Delete", role: .destructive) {
                    Task {
                        await viewModel.deleteRecording(apiClient: appState.getAPIClient())
                        onDelete?()
                    }
                }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("This action cannot be undone.")
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
        } else {
            VStack(spacing: Spacing.lg) {
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
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }

    @ViewBuilder
    private func actionsTab(_ detail: RecordingDetail) -> some View {
        if !detail.actionItems.isEmpty {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: Spacing.sm) {
                    ForEach(detail.actionItems) { item in
                        ActionItemRow(item: item) { newStatus in
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
                .padding(Spacing.lg)
            }
        } else {
            ContentUnavailableView(
                "No Action Items",
                systemImage: "checklist",
                description: Text("Generate a summary first to extract action items.")
            )
        }
    }
}

struct ActionItemRow: View {
    let item: ActionItem
    let onStatusChange: (ActionItem.Status) -> Void

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: Spacing.md) {
            Button {
                let newStatus: ActionItem.Status = item.status == .completed ? .pending : .completed
                onStatusChange(newStatus)
            } label: {
                Image(systemName: item.status == .completed ? "checkmark.circle.fill" : "circle")
                    .foregroundStyle(item.status == .completed ? Palette.accent : Palette.textSecondary)
                    .font(Typography.headingLarge)
            }
            .buttonStyle(.plain)

            VStack(alignment: .leading, spacing: Spacing.xs) {
                Text(item.task)
                    .font(Typography.body)
                    .strikethrough(item.status == .completed)
                    .foregroundStyle(item.status == .completed ? Palette.textSecondary : Palette.textPrimary)

                HStack(spacing: Spacing.sm) {
                    if let owner = item.owner {
                        Text(owner)
                            .font(Typography.label)
                            .foregroundStyle(Palette.textTertiary)
                    }

                    if let priority = item.priority {
                        Text(priority.rawValue.capitalized)
                            .font(Typography.label)
                            .foregroundStyle(priorityColor(priority))
                    }
                }
            }

            Spacer()
        }
        .padding(.vertical, Spacing.sm)
    }

    private func priorityColor(_ priority: ActionItem.Priority) -> Color {
        switch priority {
        case .high: return Palette.priorityHigh
        case .medium: return Palette.priorityMedium
        case .low: return Palette.priorityLow
        }
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

    func load(recordingId: String, apiClient: APIClient) async {
        isLoading = true
        error = nil

        do {
            recordingDetail = try await apiClient.getRecording(id: recordingId)
        } catch {
            self.error = error.localizedDescription
        }

        isLoading = false
    }

    func generateSummary(apiClient: APIClient) async {
        guard let id = recordingDetail?.id else { return }
        isGeneratingSummary = true

        do {
            _ = try await apiClient.generateSummary(recordingId: id)
            recordingDetail = try await apiClient.getRecording(id: id)
            selectedTab = .summary
        } catch {
            self.error = error.localizedDescription
        }

        isGeneratingSummary = false
    }

    func deleteRecording(apiClient: APIClient) async {
        guard let id = recordingDetail?.id else { return }
        do {
            try await apiClient.deleteRecording(id: id)
        } catch {
            self.error = error.localizedDescription
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
