import SwiftUI
import WaiComputerKit

struct MenuBarView: View {
    @Environment(\.openWindow) private var openWindow
    @EnvironmentObject var appState: MacAppState
    @EnvironmentObject var recordingVM: MacRecordingViewModel
    @EnvironmentObject var dictationManager: DictationManager
    @EnvironmentObject var historyStore: DictationHistoryStore
    @State private var recentRecordings: [Recording] = []
    @State private var lastDictationCopied = false

    private var isRecordingActivityVisible: Bool {
        recordingVM.shouldPresentLiveView || appState.completedRecordingContext != nil
    }

    private var menuStatusText: String {
        if appState.completedRecordingContext != nil {
            return "Saving transcript"
        }

        return recordingVM.shouldPresentLiveView ? recordingVM.statusText : "Ready"
    }

    private var menuDurationText: String? {
        if let completedContext = appState.completedRecordingContext {
            let totalSeconds = Int(completedContext.duration)
            let minutes = totalSeconds / 60
            let seconds = totalSeconds % 60
            return String(format: "%02d:%02d", minutes, seconds)
        }

        return recordingVM.shouldPresentLiveView ? recordingVM.formattedDuration : nil
    }

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
                    .fill(isRecordingActivityVisible ? Palette.recording : Palette.textTertiary)
                    .frame(width: 6, height: 6)

                Text(menuStatusText)
                    .font(Typography.headingSmall)

                Spacer()

                if let durationText = menuDurationText {
                    Text(durationText)
                        .font(Typography.mono)
                        .foregroundStyle(Palette.textSecondary)
                }
            }
            .padding(.horizontal, Spacing.lg)
            .padding(.top, Spacing.lg)

            // Quick actions
            VStack(spacing: Spacing.xs) {
                if recordingVM.shouldPresentLiveView {
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
                } else if appState.completedRecordingContext != nil {
                    HStack {
                        Image(systemName: "hourglass.circle")
                            .foregroundStyle(Palette.textSecondary)
                        Text("Saving Transcript")
                            .font(Typography.body)
                        Spacer()
                    }
                    .padding(.vertical, Spacing.sm)
                    .padding(.horizontal, Spacing.lg)
                } else {
                    Button {
                        Task { await appState.startRecording(type: .note, inputSource: .dual) }
                    } label: {
                        HStack {
                            Image(systemName: "waveform")
                                .foregroundStyle(Palette.textSecondary)
                            Text("Mic + System Audio")
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

                    Button {
                        Task { await appState.startRecording(type: .note, inputSource: .microphone) }
                    } label: {
                        HStack {
                            Image(systemName: "mic")
                                .foregroundStyle(Palette.textSecondary)
                            Text("Mic Only")
                                .font(Typography.body)
                            Spacer()
                            Text("\u{21E7}\u{2318}N")
                                .font(Typography.caption)
                                .foregroundStyle(Palette.textTertiary)
                        }
                        .contentShape(Rectangle())
                        .padding(.vertical, Spacing.sm)
                        .padding(.horizontal, Spacing.lg)
                    }
                    .buttonStyle(.plain)

                    WaiDivider()
                        .padding(.horizontal, Spacing.lg)

                    Button {
                        appState.pendingMainWindowAction = .importAudioFile
                        openMainWindow()
                    } label: {
                        HStack {
                            Image(systemName: "square.and.arrow.down")
                                .foregroundStyle(Palette.textSecondary)
                            Text("Import File")
                                .font(Typography.body)
                            Spacer()
                            Text("\u{2318}I")
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
                            openMainWindow()
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

            // Dictation status
            VStack(alignment: .leading, spacing: Spacing.xs) {
                Text("DICTATION")
                    .waiSectionHeader()
                    .padding(.horizontal, Spacing.lg)

                if let last = historyStore.entries.first {
                    Button {
                        NSPasteboard.general.clearContents()
                        NSPasteboard.general.setString(last.displayText, forType: .string)
                        lastDictationCopied = true
                        DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {
                            lastDictationCopied = false
                        }
                    } label: {
                        HStack(alignment: .top, spacing: Spacing.sm) {
                            Image(systemName: lastDictationCopied ? "checkmark" : "doc.on.doc")
                                .foregroundStyle(lastDictationCopied ? .green : Palette.textSecondary)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(last.displayText)
                                    .font(Typography.bodySmall)
                                    .foregroundStyle(Palette.textPrimary)
                                    .lineLimit(2)
                                    .multilineTextAlignment(.leading)
                                Text(last.timestamp.formatted(date: .abbreviated, time: .shortened))
                                    .font(Typography.caption)
                                    .foregroundStyle(Palette.textTertiary)
                            }
                            Spacer()
                        }
                        .contentShape(Rectangle())
                        .padding(.vertical, Spacing.xs)
                        .padding(.horizontal, Spacing.lg)
                    }
                    .buttonStyle(.plain)
                    .help("Copy last dictation to clipboard")
                }

                HStack {
                    Image(systemName: "mic.badge.plus")
                        .foregroundStyle(Palette.textSecondary)
                    Text(dictationHint)
                        .font(Typography.caption)
                        .foregroundStyle(Palette.textTertiary)
                }
                .padding(.horizontal, Spacing.lg)
                .padding(.vertical, Spacing.xs)
            }

            WaiDivider()
                .padding(.horizontal, Spacing.lg)

            // Bottom actions
            HStack {
                Button("Open App") {
                    openMainWindow()
                }

                Button("Settings") {
                    appState.pendingMainWindowAction = .settings
                    openMainWindow()
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
                openMainWindow()
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

    private func openMainWindow() {
        MacPresentationCoordinator.shared.showMainWindow {
            openWindow(id: MacPresentationCoordinator.mainWindowID)
        }
    }

    private func loadRecentRecordings() async {
        if let uiTestRecordings = appState.uiTestRecordings() {
            recentRecordings = uiTestRecordings
            return
        }

        do {
            recentRecordings = try await appState.getAPIClient().listRecordings(limit: 3)
        } catch {
            recentRecordings = []
        }
    }

    private var dictationHint: String {
        if !dictationManager.isFeatureEnabled {
            return "Dictation is disabled"
        }
        return "Hold \(dictationManager.selectedHotkey.shortLabel) to dictate"
    }
}

#Preview {
    let recordingViewModel = MacRecordingViewModel()
    let dictation = DictationManager()
    let appState = MacAppState(recordingViewModel: recordingViewModel, dictationManager: dictation)
    MenuBarView()
        .environmentObject(appState)
        .environmentObject(recordingViewModel)
        .environmentObject(dictation)
}
