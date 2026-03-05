import SwiftUI
import WaiComputerKit

struct MenuBarView: View {
    @EnvironmentObject var appState: MacAppState
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
                    .fill(appState.isRecording ? Palette.recording : Palette.textTertiary)
                    .frame(width: 6, height: 6)

                Text(appState.isRecording ? "Recording" : "Ready")
                    .font(Typography.headingSmall)

                Spacer()

                if appState.isRecording {
                    Text(appState.recordingViewModel.formattedDuration)
                        .font(Typography.mono)
                        .foregroundStyle(Palette.textSecondary)
                }
            }
            .padding(.horizontal, Spacing.lg)
            .padding(.top, Spacing.lg)

            // Quick actions
            VStack(spacing: Spacing.xs) {
                if appState.isRecording {
                    Button {
                        Task {
                            await appState.stopRecording()
                            await loadRecentRecordings()
                        }
                    } label: {
                        HStack {
                            Image(systemName: "stop.circle.fill")
                                .foregroundStyle(Palette.recording)
                            Text("Stop Recording")
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
                } else {
                    Button {
                        Task { await appState.startRecording(type: .meeting) }
                    } label: {
                        HStack {
                            Image(systemName: "person.2")
                                .foregroundStyle(Palette.textSecondary)
                            Text("New Meeting")
                                .font(Typography.body)
                            Spacer()
                        }
                        .contentShape(Rectangle())
                        .padding(.vertical, Spacing.sm)
                        .padding(.horizontal, Spacing.lg)
                    }
                    .buttonStyle(.plain)

                    Button {
                        Task { await appState.startRecording(type: .note) }
                    } label: {
                        HStack {
                            Image(systemName: "note.text")
                                .foregroundStyle(Palette.textSecondary)
                            Text("New Note")
                                .font(Typography.body)
                            Spacer()
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
                        HStack {
                            Text(recording.title ?? "Untitled")
                                .font(Typography.bodySmall)
                                .lineLimit(1)
                            Spacer()
                            Text(recording.createdAt.formatted(date: .abbreviated, time: .omitted))
                                .font(Typography.caption)
                                .foregroundStyle(Palette.textTertiary)
                        }
                        .padding(.vertical, Spacing.xs)
                        .padding(.horizontal, Spacing.lg)
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
    MenuBarView()
        .environmentObject(MacAppState())
}
