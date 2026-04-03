import SwiftUI
import WaiComputerKit

struct LibraryView: View {
    @EnvironmentObject var appState: AppState
    @StateObject private var viewModel = LibraryViewModel()
    @State private var errorAutoDismissTask: Task<Void, Never>?

    var body: some View {
        NavigationStack {
            Group {
                if viewModel.isLoading && viewModel.recordings.isEmpty {
                    ProgressView("Loading recordings...")
                } else if viewModel.recordings.isEmpty {
                    ContentUnavailableView(
                        "No Recordings",
                        systemImage: "waveform",
                        description: Text("Start recording to see your notes here")
                    )
                } else {
                    recordingsList
                }
            }
            .navigationTitle("Library")
            .overlay(alignment: .top) {
                if let error = viewModel.error {
                    InlineLibraryBanner(
                        message: error,
                        onDismiss: { viewModel.error = nil }
                    )
                    .padding(.top, 8)
                }
            }
            .toolbar {
                ToolbarItem(placement: .primaryAction) {
                    Menu {
                        ForEach(LibraryViewModel.FilterOption.allCases, id: \.self) { option in
                            Button(action: { viewModel.filterOption = option }) {
                                Label(option.rawValue, systemImage: viewModel.filterOption == option ? "checkmark" : "")
                            }
                        }
                    } label: {
                        Image(systemName: "line.3.horizontal.decrease.circle")
                    }
                }
            }
            .refreshable {
                await viewModel.loadRecordings(apiClient: appState.getAPIClient())
            }
            .task {
                await viewModel.loadRecordings(apiClient: appState.getAPIClient())
            }
            .onReceive(NotificationCenter.default.publisher(for: .pendingRecordingSyncDidFinish)) { _ in
                Task {
                    await viewModel.loadRecordings(apiClient: appState.getAPIClient())
                }
            }
            .onChange(of: viewModel.error) { _, newValue in
                errorAutoDismissTask?.cancel()
                guard newValue != nil else { return }

                errorAutoDismissTask = Task {
                    try? await Task.sleep(for: .seconds(6))
                    guard !Task.isCancelled else { return }
                    await MainActor.run {
                        viewModel.error = nil
                    }
                }
            }
            .onDisappear {
                errorAutoDismissTask?.cancel()
            }
        }
    }

    private var recordingsList: some View {
        List {
            ForEach(viewModel.filteredRecordings) { recording in
                NavigationLink(destination: RecordingDetailView(recording: recording)) {
                    RecordingRow(recording: recording)
                }
            }
            .onDelete { indexSet in
                Task {
                    await viewModel.deleteRecordings(at: indexSet, apiClient: appState.getAPIClient())
                }
            }
        }
    }
}

private struct InlineLibraryBanner: View {
    let message: String
    let onDismiss: () -> Void

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
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .background(Color.orange)
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .shadow(color: .black.opacity(0.15), radius: 10, y: 4)
        .padding(.horizontal)
        .accessibilityIdentifier("library-inline-error-banner")
    }
}

struct RecordingRow: View {
    let recording: Recording

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(recording.title ?? "Untitled")
                    .font(.headline)

                Spacer()

                TypeBadge(type: recording.type)
            }

            if let statusText = recording.statusDisplayText {
                Text(statusText)
                    .font(.caption)
                    .foregroundStyle(statusColor)
                    .lineLimit(1)
            }

            if let failurePreviewText = recording.failurePreviewText,
               recording.isFailedUpload {
                Text(failurePreviewText)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }

            HStack {
                Text(recording.createdAt.formatted(date: .abbreviated, time: .shortened))
                    .font(.caption)
                    .foregroundStyle(.secondary)

                if let duration = recording.durationSeconds {
                    Text("•")
                        .foregroundStyle(.secondary)
                    Text(formatDuration(duration))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .padding(.vertical, 4)
    }

    private func formatDuration(_ seconds: Int) -> String {
        let minutes = seconds / 60
        let remainingSeconds = seconds % 60
        return String(format: "%d:%02d", minutes, remainingSeconds)
    }

    private var statusColor: Color {
        recording.isFailedUpload ? .red : .secondary
    }
}

struct TypeBadge: View {
    let type: RecordingType

    var body: some View {
        Text(type.rawValue.capitalized)
            .font(.caption2)
            .fontWeight(.medium)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(backgroundColor)
            .foregroundStyle(foregroundColor)
            .cornerRadius(4)
    }

    private var backgroundColor: Color {
        switch type {
        case .meeting: return .blue.opacity(0.2)
        case .note: return .green.opacity(0.2)
        case .reflection: return .purple.opacity(0.2)
        }
    }

    private var foregroundColor: Color {
        switch type {
        case .meeting: return .blue
        case .note: return .green
        case .reflection: return .purple
        }
    }
}

@MainActor
class LibraryViewModel: ObservableObject {
    @Published var recordings: [Recording] = []
    @Published var isLoading = false
    @Published var error: String?
    @Published var filterOption: FilterOption = .all

    private var loadGeneration = 0
    private var processingRefreshTask: Task<Void, Never>?

    deinit {
        processingRefreshTask?.cancel()
    }

    enum FilterOption: String, CaseIterable {
        case all = "All"
        case meetings = "Meetings"
        case notes = "Notes"
        case reflections = "Reflections"
    }

    var filteredRecordings: [Recording] {
        switch filterOption {
        case .all:
            return recordings
        case .meetings:
            return recordings.filter { $0.type == .meeting }
        case .notes:
            return recordings.filter { $0.type == .note }
        case .reflections:
            return recordings.filter { $0.type == .reflection }
        }
    }

    func loadRecordings(apiClient: APIClient) async {
        let hasExistingContent = !recordings.isEmpty
        loadGeneration += 1
        let generation = loadGeneration
        isLoading = true
        error = nil

        defer {
            if generation == loadGeneration {
                isLoading = false
            }
        }

        do {
            let fetchedRecordings = try await apiClient.listRecordings()
            guard generation == loadGeneration else { return }

            recordings = fetchedRecordings
            processingRefreshTask?.cancel()

            if fetchedRecordings.contains(where: { $0.status == .pendingUpload || $0.status == .uploading }) {
                await PendingRecordingSyncCoordinator.shared.scheduleSync(using: apiClient)
            }
            if fetchedRecordings.contains(where: shouldBackgroundRefresh) {
                processingRefreshTask = Task { [weak self] in
                    try? await Task.sleep(for: .seconds(4))
                    guard !Task.isCancelled else { return }
                    await self?.loadRecordings(apiClient: apiClient)
                }
            }
        } catch {
            guard generation == loadGeneration else { return }
            if hasExistingContent {
                print("Library refresh failed: \(error.localizedDescription)")
                if recordings.contains(where: shouldBackgroundRefresh) {
                    self.error = error.userFacingMessage(context: .library)
                    processingRefreshTask?.cancel()
                    processingRefreshTask = Task { [weak self] in
                        try? await Task.sleep(for: .seconds(6))
                        guard !Task.isCancelled else { return }
                        await self?.loadRecordings(apiClient: apiClient)
                    }
                }
            } else {
                self.error = error.userFacingMessage(context: .library)
            }
        }
    }

    func deleteRecordings(at indexSet: IndexSet, apiClient: APIClient) async {
        // Map indices to recording IDs first to avoid index invalidation
        // during iteration (filteredRecordings is a computed property).
        let idsToDelete = indexSet.compactMap { index -> String? in
            guard index < filteredRecordings.count else { return nil }
            return filteredRecordings[index].id
        }
        for id in idsToDelete {
            do {
                try await apiClient.deleteRecording(id: id)
                recordings.removeAll { $0.id == id }
            } catch {
                self.error = error.userFacingMessage(context: .library)
            }
        }
    }

    private func shouldBackgroundRefresh(for recording: Recording) -> Bool {
        switch recording.status {
        case .pendingUpload, .uploading, .processing:
            return true
        case .ready, .failed:
            return false
        }
    }
}

#Preview {
    LibraryView()
        .environmentObject(AppState())
}
