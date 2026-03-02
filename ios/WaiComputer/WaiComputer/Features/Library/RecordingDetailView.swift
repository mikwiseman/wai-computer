import SwiftUI
import WaiComputerKit

struct RecordingDetailView: View {
    @EnvironmentObject var appState: AppState
    let recording: Recording

    @StateObject private var viewModel = RecordingDetailViewModel()
    @State private var selectedTab = 0

    var body: some View {
        VStack(spacing: 0) {
            // Tab picker
            Picker("View", selection: $selectedTab) {
                Text("Transcript").tag(0)
                Text("Summary").tag(1)
                Text("Actions").tag(2)
            }
            .pickerStyle(.segmented)
            .padding()

            // Content
            TabView(selection: $selectedTab) {
                TranscriptView(segments: viewModel.detail?.segments ?? [])
                    .tag(0)

                SummaryTabView(summary: viewModel.detail?.summary, onGenerate: {
                    Task {
                        await viewModel.generateSummary(
                            recordingId: recording.id,
                            apiClient: appState.getAPIClient()
                        )
                    }
                })
                .tag(1)

                ActionItemsTabView(actionItems: viewModel.detail?.actionItems ?? [])
                    .tag(2)
            }
            .tabViewStyle(.page(indexDisplayMode: .never))
        }
        .navigationTitle(recording.title ?? "Recording")
        .navigationBarTitleDisplayMode(.inline)
        .task {
            await viewModel.loadDetail(recordingId: recording.id, apiClient: appState.getAPIClient())
        }
        .overlay {
            if viewModel.isLoading {
                ProgressView()
            }
        }
    }
}

struct SummaryTabView: View {
    let summary: Summary?
    let onGenerate: () -> Void

    var body: some View {
        ScrollView {
            if let summary = summary {
                VStack(alignment: .leading, spacing: 16) {
                    // Summary text
                    if let text = summary.summary {
                        SectionView(title: "Summary") {
                            Text(text)
                        }
                    }

                    // Key points
                    if let keyPoints = summary.keyPoints, !keyPoints.isEmpty {
                        SectionView(title: "Key Points") {
                            ForEach(keyPoints, id: \.self) { point in
                                HStack(alignment: .top) {
                                    Image(systemName: "circle.fill")
                                        .font(.system(size: 6))
                                        .padding(.top, 6)
                                    Text(point)
                                }
                            }
                        }
                    }

                    // Topics
                    if let topics = summary.topics, !topics.isEmpty {
                        SectionView(title: "Topics") {
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
                        }
                    }

                    // People
                    if let people = summary.peopleMentioned, !people.isEmpty {
                        SectionView(title: "People Mentioned") {
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
                        }
                    }
                }
                .padding()
            } else {
                ContentUnavailableView(
                    "No Summary",
                    systemImage: "text.alignleft",
                    description: Text("Generate a summary to see key points and action items")
                )
                .overlay(alignment: .bottom) {
                    Button("Generate Summary", action: onGenerate)
                        .buttonStyle(.borderedProminent)
                        .padding(.bottom, 32)
                }
            }
        }
    }
}

struct ActionItemsTabView: View {
    let actionItems: [ActionItem]

    var body: some View {
        if actionItems.isEmpty {
            ContentUnavailableView(
                "No Action Items",
                systemImage: "checklist",
                description: Text("Action items will appear here after generating a summary")
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

struct SectionView<Content: View>: View {
    let title: String
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.headline)
            content
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

@MainActor
class RecordingDetailViewModel: ObservableObject {
    @Published var detail: RecordingDetail?
    @Published var isLoading = false
    @Published var error: String?

    func loadDetail(recordingId: String, apiClient: APIClient) async {
        isLoading = true

        do {
            detail = try await apiClient.getRecording(id: recordingId)
        } catch {
            self.error = error.localizedDescription
        }

        isLoading = false
    }

    func generateSummary(recordingId: String, apiClient: APIClient) async {
        isLoading = true

        do {
            _ = try await apiClient.generateSummary(recordingId: recordingId)
            // Reload to get updated detail with summary
            detail = try await apiClient.getRecording(id: recordingId)
        } catch {
            self.error = error.localizedDescription
        }

        isLoading = false
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
    }
}
