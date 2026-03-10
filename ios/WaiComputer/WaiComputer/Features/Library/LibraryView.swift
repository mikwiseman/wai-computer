import SwiftUI
import WaiComputerKit

struct LibraryView: View {
    @EnvironmentObject var appState: AppState
    @StateObject private var viewModel = LibraryViewModel()

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
        isLoading = true

        do {
            recordings = try await apiClient.listRecordings()
        } catch {
            self.error = error.localizedDescription
        }

        isLoading = false
    }

    func deleteRecordings(at indexSet: IndexSet, apiClient: APIClient) async {
        for index in indexSet {
            let recording = filteredRecordings[index]
            do {
                try await apiClient.deleteRecording(id: recording.id)
                recordings.removeAll { $0.id == recording.id }
            } catch {
                self.error = error.localizedDescription
            }
        }
    }
}

#Preview {
    LibraryView()
        .environmentObject(AppState())
}
