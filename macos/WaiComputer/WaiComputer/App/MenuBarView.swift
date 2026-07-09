import SwiftUI
import WaiComputerKit

struct MenuBarView: View {
    @Environment(\.openWindow) private var openWindow
    @EnvironmentObject var appState: MacAppState
    @EnvironmentObject var recordingVM: MacRecordingViewModel
    @EnvironmentObject var dictationManager: DictationManager
    @EnvironmentObject var historyStore: DictationHistoryStore
    @EnvironmentObject private var languageManager: LanguageManager
    @State private var recentRecordings: [Recording] = []
    @State private var lastDictationCopied = false

    private var isRecordingActivityVisible: Bool {
        recordingVM.shouldPresentLiveView || appState.completedRecordingContext != nil
    }

    private var menuStatusText: String {
        if appState.completedRecordingContext != nil {
            return t("Saving transcript", "Сохраняем расшифровку")
        }

        return recordingVM.shouldPresentLiveView ? recordingVM.statusText : t("Ready", "Готово")
    }

    /// Static duration for the finalizing state; the live ticking duration
    /// renders via `TimelineView` so the menu bar view isn't invalidated at
    /// 1 Hz for the whole length of a recording.
    private var completedDurationText: String? {
        guard let completedContext = appState.completedRecordingContext else { return nil }
        return RecordingDurationClock.formatted(completedContext.duration)
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
        // Keyed to auth so signing in after first open populates the list,
        // and signing out doesn't keep showing another account's recordings.
        .task(id: appState.isAuthenticated) {
            if appState.isAuthenticated {
                await loadRecentRecordings()
            } else {
                recentRecordings = []
            }
        }
        .onChangeCompat(of: isRecordingActivityVisible) {
            if !isRecordingActivityVisible, appState.isAuthenticated {
                Task { await loadRecentRecordings() }
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: .pendingRecordingSyncDidFinish)) { _ in
            if appState.isAuthenticated {
                Task { await loadRecentRecordings() }
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

                if let durationText = completedDurationText {
                    Text(durationText)
                        .font(Typography.mono)
                        .foregroundStyle(Palette.textSecondary)
                } else if recordingVM.shouldPresentLiveView {
                    TimelineView(.periodic(from: .now, by: 1)) { timeline in
                        Text(RecordingDurationClock.formatted(
                            recordingVM.durationClock.elapsed(at: timeline.date)
                        ))
                        .font(Typography.mono)
                        .foregroundStyle(Palette.textSecondary)
                    }
                }
            }
            .padding(.horizontal, Spacing.lg)
            .padding(.top, Spacing.lg)

            // Quick actions
            VStack(spacing: Spacing.xs) {
                if recordingVM.shouldPresentLiveView {
                    Button {
                        Task {
                            if recordingVM.canResumeRecording {
                                await appState.resumeRecording()
                            } else {
                                await appState.pauseRecording()
                            }
                        }
                    } label: {
                        HStack {
                            Image(systemName: recordingVM.canResumeRecording ? "play.circle.fill" : "pause.circle")
                                .foregroundStyle(Palette.textSecondary)
                            Text(recordingVM.canResumeRecording ? t("Resume Recording", "Продолжить запись") : t("Pause Recording", "Приостановить запись"))
                                .font(Typography.body)
                            Spacer()
                            Text("\u{21E7}\u{2318}P")
                                .font(Typography.caption)
                                .foregroundStyle(Palette.textTertiary)
                        }
                        .contentShape(Rectangle())
                        .padding(.vertical, Spacing.sm)
                        .padding(.horizontal, Spacing.lg)
                    }
                    .buttonStyle(.plain)
                    .disabled(!recordingVM.canPauseRecording && !recordingVM.canResumeRecording)

                    Button {
                        Task {
                            await appState.stopRecording()
                            await loadRecentRecordings()
                        }
                    } label: {
                        HStack {
                            Image(systemName: recordingVM.canStopRecording ? "stop.circle.fill" : "hourglass.circle")
                                .foregroundStyle(recordingVM.canStopRecording ? Palette.recording : Palette.textSecondary)
                            Text(recordingVM.canStopRecording ? t("Stop Recording", "Остановить запись") : recordingVM.statusText)
                                .font(Typography.body)
                            Spacer()
                            Text("\u{2318}.")
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
                        Text(t("Saving transcript", "Сохраняем расшифровку"))
                            .font(Typography.body)
                        Spacer()
                    }
                    .padding(.vertical, Spacing.sm)
                    .padding(.horizontal, Spacing.lg)
                } else {
                    Button {
                        appState.pendingMainWindowAction = .inboxCommand(.contextualNew)
                        openMainWindow()
                    } label: {
                        HStack {
                            Image(systemName: "tray.full")
                                .foregroundStyle(Palette.textSecondary)
                            Text(t("New Inbox Item", "Новый объект в Инбоксе"))
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
                        Task { await appState.startRecording(type: .meeting, inputSource: .dual) }
                    } label: {
                        HStack {
                            Image(systemName: "waveform")
                                .foregroundStyle(Palette.textSecondary)
                            Text(t("Record", "Записать"))
                                .font(Typography.body)
                            Spacer()
                            Text("\u{21E7}\u{2318}R")
                                .font(Typography.caption)
                                .foregroundStyle(Palette.textTertiary)
                        }
                        .contentShape(Rectangle())
                        .padding(.vertical, Spacing.sm)
                        .padding(.horizontal, Spacing.lg)
                    }
                    .buttonStyle(.plain)

                    Button {
                        appState.pendingMainWindowAction = .inboxCommand(.uploadFile)
                        openMainWindow()
                    } label: {
                        HStack {
                            Image(systemName: "square.and.arrow.down")
                                .foregroundStyle(Palette.textSecondary)
                            Text(t("Upload File", "Загрузить файл"))
                                .font(Typography.body)
                            Spacer()
                            Text("\u{2325}\u{2318}U")
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
                Text(t("RECENT", "НЕДАВНИЕ"))
                    .waiSectionHeader()
                    .padding(.horizontal, Spacing.lg)

                if recentRecordings.isEmpty {
                    Text(t("No recordings yet", "Записей пока нет"))
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
                                Text(recording.title ?? t("Untitled", "Без названия"))
                                    .font(Typography.bodySmall)
                                    .lineLimit(1)
                                Spacer()
                                Text(MacDateFormatting.string(
                                    from: recording.createdAt,
                                    dateStyle: .medium,
                                    timeStyle: .none,
                                    language: languageManager.current
                                ))
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
                Text(t("DICTATION", "ДИКТОВКА"))
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
                                .foregroundStyle(lastDictationCopied ? Palette.success : Palette.textSecondary)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(last.displayText)
                                    .font(Typography.bodySmall)
                                    .foregroundStyle(Palette.textPrimary)
                                    .lineLimit(2)
                                    .multilineTextAlignment(.leading)
                                Text(MacDateFormatting.string(
                                    from: last.timestamp,
                                    dateStyle: .medium,
                                    timeStyle: .short,
                                    language: languageManager.current
                                ))
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
                    .help(t("Copy last dictation to clipboard", "Скопировать последнюю диктовку"))
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
                Button(t("Open App", "Открыть приложение")) {
                    openMainWindow()
                }

                Button(t("Settings", "Настройки")) {
                    appState.pendingMainWindowAction = .settings
                    openMainWindow()
                }

                Spacer()

                Button(t("Quit", "Выйти")) {
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
            Text(t("Not signed in", "Вход не выполнен"))
                .font(Typography.headingSmall)

            Button(t("Open App", "Открыть приложение")) {
                openMainWindow()
            }
            .buttonStyle(WaiPrimaryButtonStyle(isDisabled: false))

            WaiDivider()

            Button(t("Quit", "Выйти")) {
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
            return t("Dictation is disabled", "Диктовка выключена")
        }
        let hotkey = DictationSettingsCopy.hotkeyShortLabel(
            rawValue: dictationManager.selectedHotkey.rawValue,
            language: languageManager.current
        )
        return t(
            "Hold \(hotkey) to dictate",
            "Зажми \(hotkey), чтобы диктовать"
        )
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
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
        .environmentObject(LanguageManager.shared)
}
