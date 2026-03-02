import SwiftUI
import WaiComputerKit

struct MenuBarView: View {
    @EnvironmentObject var appState: MacAppState
    @State private var recentRecordings: [Recording] = []
    @State private var audioSource: AudioSource = .microphone

    enum AudioSource: String {
        case microphone, system, both

        var description: String {
            switch self {
            case .microphone: return "Microphone"
            case .system: return "System Audio"
            case .both: return "Mic + System"
            }
        }
    }

    var body: some View {
        VStack(spacing: 0) {
            if appState.isAuthenticated {
                authenticatedMenu
            } else {
                unauthenticatedMenu
            }
        }
        .frame(width: 280)
        .task {
            if appState.isAuthenticated {
                await loadRecentRecordings()
            }
        }
    }

    private var authenticatedMenu: some View {
        VStack(spacing: 12) {
            // Recording status
            HStack {
                Circle()
                    .fill(appState.isRecording ? Color.red : Color.gray)
                    .frame(width: 8, height: 8)

                Text(appState.isRecording ? "Recording..." : "Ready")
                    .font(.headline)

                Spacer()

                if appState.isRecording {
                    Text(appState.recordingViewModel.formattedDuration)
                        .font(.system(.body, design: .monospaced))
                }
            }
            .padding()
            .background(Color.gray.opacity(0.1))
            .cornerRadius(8)

            // Quick actions
            VStack(spacing: 8) {
                if appState.isRecording {
                    Button {
                        Task {
                            await appState.stopRecording()
                            await loadRecentRecordings()
                        }
                    } label: {
                        HStack {
                            Image(systemName: "stop.circle.fill")
                                .foregroundStyle(.red)
                            Text("Stop Recording")
                            Spacer()
                            Text("⌘R")
                                .foregroundStyle(.secondary)
                        }
                    }
                    .buttonStyle(.plain)
                    .padding(8)
                    .background(Color.red.opacity(0.1))
                    .cornerRadius(6)
                } else {
                    // Start recording buttons by type
                    Button {
                        Task { await appState.startRecording(type: .meeting) }
                    } label: {
                        HStack {
                            Image(systemName: "person.2.fill")
                            Text("New Meeting")
                            Spacer()
                        }
                    }
                    .buttonStyle(.plain)
                    .padding(8)
                    .background(Color.blue.opacity(0.1))
                    .cornerRadius(6)

                    Button {
                        Task { await appState.startRecording(type: .note) }
                    } label: {
                        HStack {
                            Image(systemName: "note.text")
                            Text("New Note")
                            Spacer()
                        }
                    }
                    .buttonStyle(.plain)
                    .padding(8)
                    .background(Color.green.opacity(0.1))
                    .cornerRadius(6)

                    // Audio source selector
                    Menu {
                        Button("Microphone Only") { audioSource = .microphone }
                        Button("System Audio (BlackHole)") { audioSource = .system }
                        Button("Microphone + System") { audioSource = .both }
                    } label: {
                        HStack {
                            Image(systemName: "speaker.wave.2")
                            Text(audioSource.description)
                            Spacer()
                            Image(systemName: "chevron.down")
                        }
                    }
                    .buttonStyle(.plain)
                    .padding(8)
                    .background(Color.gray.opacity(0.1))
                    .cornerRadius(6)
                }
            }

            Divider()

            // Recent recordings
            VStack(alignment: .leading, spacing: 4) {
                Text("Recent")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 4)

                if recentRecordings.isEmpty {
                    Text("No recordings yet")
                        .font(.caption)
                        .foregroundStyle(.tertiary)
                        .padding(6)
                } else {
                    ForEach(recentRecordings.prefix(3)) { recording in
                        HStack {
                            Text(recording.title ?? "Untitled")
                                .lineLimit(1)
                            Spacer()
                            Text(recording.createdAt.formatted(date: .abbreviated, time: .omitted))
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                        .padding(6)
                        .background(Color.gray.opacity(0.05))
                        .cornerRadius(4)
                    }
                }
            }

            Divider()

            // Bottom actions
            HStack {
                Button("Open App") {
                    NSApp.activate(ignoringOtherApps: true)
                }

                Spacer()

                Button("Quit") {
                    NSApplication.shared.terminate(nil)
                }
            }
            .buttonStyle(.plain)
            .font(.caption)
            .foregroundStyle(.secondary)
        }
        .padding()
    }

    private var unauthenticatedMenu: some View {
        VStack(spacing: 12) {
            Text("Not logged in")
                .font(.headline)

            Button("Open App to Login") {
                NSApp.activate(ignoringOtherApps: true)
            }
            .buttonStyle(.borderedProminent)

            Divider()

            Button("Quit") {
                NSApplication.shared.terminate(nil)
            }
            .buttonStyle(.plain)
            .font(.caption)
            .foregroundStyle(.secondary)
        }
        .padding()
    }

    private func loadRecentRecordings() async {
        do {
            recentRecordings = try await appState.getAPIClient().listRecordings(limit: 3)
        } catch {
            recentRecordings = []
        }
    }
}

#Preview {
    MenuBarView()
        .environmentObject(MacAppState())
}
