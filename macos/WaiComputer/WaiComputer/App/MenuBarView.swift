import SwiftUI
import WaiComputerKit

struct MenuBarView: View {
    @EnvironmentObject var appState: MacAppState
    @EnvironmentObject var recordingVM: MacRecordingViewModel
    @State private var recentRecordings: [Recording] = []

    var body: some View {
        VStack(spacing: 0) {
            if appState.isAuthenticated {
                authenticatedMenu
            } else {
                unauthenticatedMenu
            }
        }
        .frame(width: 260)
        .task {
            if appState.isAuthenticated {
                await loadRecentRecordings()
            }
        }
    }

    private var authenticatedMenu: some View {
        VStack(spacing: Spacing.md) {
            // Recording status
            HStack(spacing: Spacing.sm) {
                Circle()
                    .fill(appState.isRecordingSessionActive ? Palette.recording : Palette.textTertiary)
                    .frame(width: 6, height: 6)

                Text(appState.isRecordingSessionActive ? recordingVM.statusText : "Ready")
                    .font(Typography.headingSmall)

                Spacer()

                if appState.isRecordingSessionActive {
                    Text(recordingVM.formattedDuration)
                        .font(Typography.mono)
                        .foregroundStyle(Palette.textSecondary)
                }
            }
            .padding(.horizontal, Spacing.lg)
            .padding(.top, Spacing.lg)

            // Quick actions
            VStack(spacing: Spacing.xs) {
                if appState.isRecordingSessionActive {
                    Button {
                        Task {
                            await appState.stopRecording()
                            await loadRecentRecordings()
                        }
                    } label: {
                        HStack {
                            Image(systemName: recordingVM.canStopRecording ? "stop.circle.fill" : "hourglass.circle")
                                .foregroundStyle(recordingVM.canStopRecording ? Palette.recording : Palette.textSecondary)
                            Text(recordingVM.canStopRecording ? "Stop Recording" : recordingVM.statusText)
                                .font(Typography.body)
                            Spacer()
                            Text("\u{2318}R")
                                .font(Typography.caption)
                                .foregroundStyle(Palette.textTertiary)
                        }
                        .contentShape(Rectangle())
                        .padding(.vertical, Spacing.sm)
                        .padding(.horizontal, Spacing.lg)
                    }
                    .buttonStyle(.plain)
                    .disabled(!recordingVM.canStopRecording)
                } else {
                    Button {
                        Task { await appState.startRecording(type: .note) }
                    } label: {
                        HStack {
                            Image(systemName: "plus.circle")
                                .foregroundStyle(Palette.textSecondary)
                            Text("New Recording")
                                .font(Typography.body)
                            Spacer()
                            Text("\u{2318}N")
                                .font(Typography.caption)
                                .foregroundStyle(Palette.textTertiary)
                        }
                        .contentShape(Rectangle())
                        .padding(.vertical, Spacing.sm)
                        .padding(.horizontal, Spacing.lg)
                    }
                    .buttonStyle(.plain)
                }
            }

            WaiDivider()
                .padding(.horizontal, Spacing.lg)

            // Recent recordings
            VStack(alignment: .leading, spacing: Spacing.xs) {
                Text("RECENT")
                    .waiSectionHeader()
                    .padding(.horizontal, Spacing.lg)

                if recentRecordings.isEmpty {
                    Text("No recordings yet")
                        .font(Typography.caption)
                        .foregroundStyle(Palette.textTertiary)
                        .padding(.horizontal, Spacing.lg)
                        .padding(.vertical, Spacing.xs)
                } else {
                    ForEach(recentRecordings.prefix(3)) { recording in
                        Button {
                            appState.selectedRecordingFromMenu = recording.id
                            NSApp.activate(ignoringOtherApps: true)
                        } label: {
                            HStack {
                                Text(recording.title ?? "Untitled")
                                    .font(Typography.bodySmall)
                                    .lineLimit(1)
                                Spacer()
                                Text(recording.createdAt.formatted(date: .abbreviated, time: .omitted))
                                    .font(Typography.caption)
                                    .foregroundStyle(Palette.textTertiary)
                            }
                            .contentShape(Rectangle())
                            .padding(.vertical, Spacing.xs)
                            .padding(.horizontal, Spacing.lg)
                        }
                        .buttonStyle(.plain)
                    }
                }
            }

            WaiDivider()
                .padding(.horizontal, Spacing.lg)

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
            .font(Typography.caption)
            .foregroundStyle(Palette.textSecondary)
            .padding(.horizontal, Spacing.lg)
            .padding(.bottom, Spacing.lg)
        }
    }

    private var unauthenticatedMenu: some View {
        VStack(spacing: Spacing.md) {
            Text("Not signed in")
                .font(Typography.headingSmall)

            Button("Open App") {
                NSApp.activate(ignoringOtherApps: true)
            }
            .buttonStyle(WaiPrimaryButtonStyle(isDisabled: false))

            WaiDivider()

            Button("Quit") {
                NSApplication.shared.terminate(nil)
            }
            .buttonStyle(.plain)
            .font(Typography.caption)
            .foregroundStyle(Palette.textSecondary)
        }
        .padding(Spacing.lg)
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
    let appState = MacAppState()
    MenuBarView()
        .environmentObject(appState)
        .environmentObject(appState.recordingViewModel)
}
