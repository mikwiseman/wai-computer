import SwiftUI
import WaiComputerKit

struct RecordingDetailView: View {
    @EnvironmentObject var appState: AppState
    @Environment(\.dismiss) private var dismiss
    let recording: Recording
    let isTrash: Bool
    let folders: [Folder]
    var onMoveToFolder: ((String?) -> Void)?
    var onTrash: (() -> Void)?
    var onRestore: (() -> Void)?
    var onPermanentDelete: (() -> Void)?

    @StateObject private var viewModel = RecordingDetailViewModel()
    @State private var selectedTab = 0
    @State private var showDeleteConfirmation = false

    init(
        recording: Recording,
        isTrash: Bool = false,
        folders: [Folder] = [],
        onMoveToFolder: ((String?) -> Void)? = nil,
        onTrash: (() -> Void)? = nil,
        onRestore: (() -> Void)? = nil,
        onPermanentDelete: (() -> Void)? = nil
    ) {
        self.recording = recording
        self.isTrash = isTrash
        self.folders = folders
        self.onMoveToFolder = onMoveToFolder
        self.onTrash = onTrash
        self.onRestore = onRestore
        self.onPermanentDelete = onPermanentDelete
    }

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
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Menu {
                    if isTrash {
                        Button {
                            onRestore?()
                            dismiss()
                        } label: {
                            Label("Restore", systemImage: "arrow.uturn.backward")
                        }

                        Button(role: .destructive) {
                            showDeleteConfirmation = true
                        } label: {
                            Label("Delete Permanently", systemImage: "trash.slash")
                        }
                    } else {
                        if !folders.isEmpty {
                            Menu("Move to Folder") {
                                if recording.folderId != nil {
                                    Button("Unfiled") {
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
                            }
                        }

                        Button(role: .destructive) {
                            showDeleteConfirmation = true
                        } label: {
                            Label("Move to Trash", systemImage: "trash")
                        }
                    }
                } label: {
                    Image(systemName: "ellipsis.circle")
                }
            }
        }
        .confirmationDialog(
            isTrash ? "Delete this recording permanently?" : "Move this recording to trash?",
            isPresented: $showDeleteConfirmation,
            titleVisibility: .visible
        ) {
            Button(isTrash ? "Delete Permanently" : "Move to Trash", role: .destructive) {
                if isTrash {
                    onPermanentDelete?()
                } else {
                    onTrash?()
                }
                dismiss()
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text(
                isTrash
                    ? "This action cannot be undone."
                    : "You can restore it later from Trash."
            )
        }
        .task {
            await viewModel.loadDetail(recordingId: recording.id, apiClient: appState.getAPIClient())
        }
        .task(id: detailRefreshKey) {
            await viewModel.refreshPendingDetailIfNeeded(
                recordingId: recording.id,
                apiClient: appState.getAPIClient()
            )
        }
        .onChange(of: recording.id) {
            selectedTab = 0
        }
        .onReceive(NotificationCenter.default.publisher(for: .pendingRecordingSyncDidFinish)) { notification in
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
        .overlay {
            if viewModel.isLoading {
                ProgressView()
            }
        }
        .alert(
            "Recording Error",
            isPresented: Binding(
                get: { viewModel.error != nil },
                set: { if !$0 { viewModel.error = nil } }
            )
        ) {
            Button("OK") {
                viewModel.error = nil
            }
        } message: {
            Text(viewModel.error ?? "We couldn't load this recording right now.")
        }
    }

    private var detailRefreshKey: String {
        let status = viewModel.detail?.status.rawValue ?? "none"
        return "\(recording.id)-\(status)"
    }
}

struct SummaryTabView: View {
    let summary: Summary?
    let onGenerate: () -> Void
    @State private var copiedSection: String?

    var body: some View {
        ScrollView {
            if let summary = summary {
                VStack(alignment: .leading, spacing: 16) {
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
                        SectionView(title: "Summary") {
                            Text(text)
                                .textSelection(.enabled)
                        } trailing: {
                            CopyButton(text: text, section: "summary-text", copiedSection: $copiedSection)
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
                        } trailing: {
                            CopyButton(
                                text: people.joined(separator: ", "),
                                section: "summary-people",
                                copiedSection: $copiedSection
                            )
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

    private func fullSummaryText(_ summary: Summary) -> String {
        var parts: [String] = []
        if let text = summary.summary { parts.append(text) }
        if let points = summary.keyPoints, !points.isEmpty {
            parts.append("\nKey Points:\n" + points.map { "- \($0)" }.joined(separator: "\n"))
        }
        if let topics = summary.topics, !topics.isEmpty {
            parts.append("\nTopics: " + topics.joined(separator: ", "))
        }
        if let people = summary.peopleMentioned, !people.isEmpty {
            parts.append("\nPeople: " + people.joined(separator: ", "))
        }
        return parts.joined(separator: "\n")
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

@MainActor
class RecordingDetailViewModel: ObservableObject {
    @Published var detail: RecordingDetail?
    @Published var isLoading = false
    @Published var error: String?

    func loadDetail(recordingId: String, apiClient: APIClient, showLoading: Bool = true) async {
        if showLoading {
            isLoading = true
        }
        error = nil

        do {
            detail = try await apiClient.getRecording(id: recordingId)
        } catch {
            self.error = error.userFacingMessage(context: .library)
        }

        if showLoading {
            isLoading = false
        }
    }

    func generateSummary(recordingId: String, apiClient: APIClient) async {
        isLoading = true

        do {
            _ = try await apiClient.generateSummary(recordingId: recordingId)
            // Reload to get updated detail with summary
            detail = try await apiClient.getRecording(id: recordingId)
        } catch {
            self.error = error.userFacingMessage(context: .library)
        }

        isLoading = false
    }

    func refreshPendingDetailIfNeeded(recordingId: String, apiClient: APIClient) async {
        guard shouldAutoRefresh(for: detail?.status) else { return }

        while !Task.isCancelled, shouldAutoRefresh(for: detail?.status) {
            try? await Task.sleep(for: .seconds(detail?.status == .processing ? 4 : 2))
            guard !Task.isCancelled else { return }
            await loadDetail(recordingId: recordingId, apiClient: apiClient, showLoading: false)
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
