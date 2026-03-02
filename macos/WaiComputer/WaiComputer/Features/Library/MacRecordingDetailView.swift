import SwiftUI
import WaiComputerKit

struct MacRecordingDetailView: View {
    let recordingId: String
    @EnvironmentObject var appState: MacAppState
    @StateObject private var viewModel = MacRecordingDetailViewModel()

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
                    // Header
                    detailHeader(detail)

                    Divider()

                    // Tabbed content
                    Picker("", selection: $viewModel.selectedTab) {
                        Text("Transcript").tag(MacRecordingDetailViewModel.Tab.transcript)
                        Text("Summary").tag(MacRecordingDetailViewModel.Tab.summary)
                        Text("Action Items").tag(MacRecordingDetailViewModel.Tab.actions)
                    }
                    .pickerStyle(.segmented)
                    .padding()

                    // Tab content
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
            VStack(alignment: .leading, spacing: 4) {
                Text(detail.title ?? "Untitled")
                    .font(.title2)
                    .fontWeight(.semibold)

                HStack(spacing: 8) {
                    TypeBadge(type: detail.type)

                    Text(detail.createdAt.formatted(date: .long, time: .shortened))
                        .font(.caption)
                        .foregroundStyle(.secondary)

                    if let duration = detail.durationSeconds, duration > 0 {
                        let mins = Int(duration) / 60
                        let secs = Int(duration) % 60
                        Text(String(format: "%d:%02d", mins, secs))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }

            Spacer()
        }
        .padding()
    }

    @ViewBuilder
    private func summaryTab(_ detail: RecordingDetail) -> some View {
        if let summary = detail.summary {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    // Summary text
                    if let text = summary.summary {
                        VStack(alignment: .leading, spacing: 6) {
                            Text("Summary")
                                .font(.headline)
                            Text(text)
                                .font(.body)
                        }
                    }

                    // Key points
                    if let points = summary.keyPoints, !points.isEmpty {
                        VStack(alignment: .leading, spacing: 6) {
                            Text("Key Points")
                                .font(.headline)
                            ForEach(points, id: \.self) { point in
                                HStack(alignment: .top, spacing: 8) {
                                    Circle()
                                        .fill(.blue)
                                        .frame(width: 6, height: 6)
                                        .padding(.top, 6)
                                    Text(point)
                                        .font(.body)
                                }
                            }
                        }
                    }

                    // Topics
                    if let topics = summary.topics, !topics.isEmpty {
                        VStack(alignment: .leading, spacing: 6) {
                            Text("Topics")
                                .font(.headline)
                            FlowLayout(spacing: 6) {
                                ForEach(topics, id: \.self) { topic in
                                    Text(topic)
                                        .font(.caption)
                                        .padding(.horizontal, 10)
                                        .padding(.vertical, 4)
                                        .background(Color.blue.opacity(0.1))
                                        .clipShape(Capsule())
                                }
                            }
                        }
                    }

                    // People mentioned
                    if let people = summary.peopleMentioned, !people.isEmpty {
                        VStack(alignment: .leading, spacing: 6) {
                            Text("People Mentioned")
                                .font(.headline)
                            FlowLayout(spacing: 6) {
                                ForEach(people, id: \.self) { person in
                                    HStack(spacing: 4) {
                                        Image(systemName: "person.fill")
                                            .font(.caption2)
                                        Text(person)
                                            .font(.caption)
                                    }
                                    .padding(.horizontal, 10)
                                    .padding(.vertical, 4)
                                    .background(Color.gray.opacity(0.1))
                                    .clipShape(Capsule())
                                }
                            }
                        }
                    }
                }
                .padding()
            }
        } else {
            VStack(spacing: 16) {
                ContentUnavailableView(
                    "No Summary",
                    systemImage: "doc.text",
                    description: Text("Generate a summary to see key points and insights.")
                )

                Button("Generate Summary") {
                    Task {
                        await viewModel.generateSummary(apiClient: appState.getAPIClient())
                    }
                }
                .buttonStyle(.borderedProminent)
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
                LazyVStack(alignment: .leading, spacing: 8) {
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
                .padding()
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
        HStack(alignment: .top, spacing: 10) {
            Button {
                let newStatus: ActionItem.Status = item.status == .completed ? .pending : .completed
                onStatusChange(newStatus)
            } label: {
                Image(systemName: item.status == .completed ? "checkmark.circle.fill" : "circle")
                    .foregroundStyle(item.status == .completed ? .green : .secondary)
                    .font(.title3)
            }
            .buttonStyle(.plain)

            VStack(alignment: .leading, spacing: 4) {
                Text(item.task)
                    .font(.body)
                    .strikethrough(item.status == .completed)
                    .foregroundStyle(item.status == .completed ? .secondary : .primary)

                HStack(spacing: 8) {
                    if let owner = item.owner {
                        HStack(spacing: 2) {
                            Image(systemName: "person.fill")
                                .font(.caption2)
                            Text(owner)
                                .font(.caption)
                        }
                        .foregroundStyle(.secondary)
                    }

                    if let priority = item.priority {
                        PriorityBadge(priority: priority)
                    }
                }
            }

            Spacer()
        }
        .padding(10)
        .background(Color.gray.opacity(0.04))
        .cornerRadius(8)
    }
}

struct PriorityBadge: View {
    let priority: ActionItem.Priority

    var body: some View {
        Text(priority.rawValue.capitalized)
            .font(.caption2)
            .fontWeight(.medium)
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(color.opacity(0.15))
            .foregroundStyle(color)
            .clipShape(Capsule())
    }

    private var color: Color {
        switch priority {
        case .high: return .red
        case .medium: return .orange
        case .low: return .gray
        }
    }
}

/// Simple flow layout for tags
struct FlowLayout: Layout {
    var spacing: CGFloat = 6

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let result = arrange(proposal: proposal, subviews: subviews)
        return result.size
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let result = arrange(proposal: proposal, subviews: subviews)
        for (index, position) in result.positions.enumerated() {
            subviews[index].place(at: CGPoint(x: bounds.minX + position.x, y: bounds.minY + position.y), proposal: .unspecified)
        }
    }

    private func arrange(proposal: ProposedViewSize, subviews: Subviews) -> (size: CGSize, positions: [CGPoint]) {
        let maxWidth = proposal.width ?? .infinity
        var positions: [CGPoint] = []
        var x: CGFloat = 0
        var y: CGFloat = 0
        var rowHeight: CGFloat = 0
        var totalHeight: CGFloat = 0

        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x + size.width > maxWidth && x > 0 {
                x = 0
                y += rowHeight + spacing
                rowHeight = 0
            }
            positions.append(CGPoint(x: x, y: y))
            rowHeight = max(rowHeight, size.height)
            x += size.width + spacing
            totalHeight = y + rowHeight
        }

        return (CGSize(width: maxWidth, height: totalHeight), positions)
    }
}

// MARK: - ViewModel

@MainActor
class MacRecordingDetailViewModel: ObservableObject {
    enum Tab {
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
            // Reload to get updated detail with summary and action items
            recordingDetail = try await apiClient.getRecording(id: id)
            selectedTab = .summary
        } catch {
            self.error = error.localizedDescription
        }

        isGeneratingSummary = false
    }

    func updateActionItemStatus(id: String, status: ActionItem.Status, apiClient: APIClient) async {
        do {
            _ = try await apiClient.updateActionItem(id: id, status: status)
            // Reload to reflect changes
            if let recordingId = recordingDetail?.id {
                recordingDetail = try await apiClient.getRecording(id: recordingId)
            }
        } catch {
            self.error = error.localizedDescription
        }
    }
}
