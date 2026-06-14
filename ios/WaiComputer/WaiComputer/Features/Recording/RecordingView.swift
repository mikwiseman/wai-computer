import SwiftUI
import WaiComputerKit

struct RecordingView: View {
    @EnvironmentObject var appState: AppState
    @EnvironmentObject var viewModel: RecordingViewModel
    @EnvironmentObject var languageManager: LanguageManager
    @State private var showingDiscardConfirm = false
    /// Folders the new recording can be filed into. `nil` selection = All Recordings.
    @State private var folders: [Folder] = []
    @State private var selectedFolderId: String?
    @State private var foldersError: String?

    private var isScreenshotMode: Bool {
        IOSTestingMode.current.isScreenshot
    }

    private var selectedFolderName: String {
        guard let selectedFolderId,
              let folder = folders.first(where: { $0.id == selectedFolderId }) else {
            return t("All Recordings", "Все записи")
        }
        return folder.name
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 32) {
                Spacer()

                // Recording status
                VStack(spacing: 16) {
                    // Waveform or status indicator
                    ZStack {
                        Circle()
                            .fill(outerIndicatorColor)
                            .frame(width: 200, height: 200)

                        Circle()
                            .fill(innerIndicatorColor)
                            .frame(width: 150, height: 150)
                            .scaleEffect(viewModel.canStopRecording && !viewModel.isPaused ? 1.1 : 1.0)
                            .animation(.easeInOut(duration: 0.5).repeatForever(autoreverses: true), value: viewModel.canStopRecording && !viewModel.isPaused)

                        Image(systemName: indicatorSymbolName)
                            .font(.system(size: 60))
                            .foregroundStyle(indicatorSymbolColor)
                    }

                    // Duration
                    Text(viewModel.formattedDuration)
                        .font(.system(size: 48, weight: .light, design: .monospaced))
                        .foregroundStyle(viewModel.phase == .idle ? .secondary : .primary)
                        .accessibilityLabel(durationAccessibilityLabel)
                        .accessibilityAddTraits(.updatesFrequently)
                }

                // Offline transcription banner
                if viewModel.liveTranscriptionOffline && viewModel.phase == .recording {
                    HStack(spacing: 8) {
                        Image(systemName: "wifi.exclamationmark")
                            .foregroundStyle(.white)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(t("Live transcription unavailable", "Живая расшифровка недоступна"))
                                .font(.subheadline.weight(.medium))
                                .foregroundStyle(.white)
                            Text(t(
                                "Audio is recording locally — transcript will be generated when you stop.",
                                "Аудио записывается локально — расшифровка появится, когда вы остановите запись."
                            ))
                                .font(.caption)
                                .foregroundStyle(.white.opacity(0.85))
                        }
                        Spacer()
                    }
                    .padding()
                    .background(Color.orange)
                    .cornerRadius(12)
                    .padding(.horizontal)
                    .accessibilityLabel(t(
                        "Live transcription unavailable. Audio is recording locally and will be transcribed after you stop.",
                        "Живая расшифровка недоступна. Аудио записывается локально и будет расшифровано после остановки."
                    ))
                    .accessibilityIdentifier("live-transcription-offline-banner")
                }

                // Reconnection banner
                if case .reconnecting(let attempt, let maxAttempts) = viewModel.connectionState {
                    HStack(spacing: 8) {
                        ProgressView()
                            .tint(.white)
                            .controlSize(.small)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(t("Reconnecting…", "Переподключение…") + " (\(attempt)/\(maxAttempts))")
                                .font(.subheadline.weight(.medium))
                                .foregroundStyle(.white)
                            Text(t("Audio is being buffered", "Аудио сохраняется локально"))
                                .font(.caption)
                                .foregroundStyle(.white.opacity(0.7))
                        }
                        Spacer()
                    }
                    .padding()
                    .background(Color.orange)
                    .cornerRadius(12)
                    .padding(.horizontal)
                    .accessibilityLabel(t("Reconnecting, attempt \(attempt) of \(maxAttempts)", "Переподключение, попытка \(attempt) из \(maxAttempts)"))
                    .accessibilityIdentifier("reconnection-banner")
                }

                // Live transcript preview — committed text renders sharp; the
                // rolling interim guess is faded so users don't fixate on words
                // the model is still revising ahead of their speech.
                if viewModel.shouldShowTranscript {
                    ScrollViewReader { proxy in
                        ScrollView {
                            LazyVStack(alignment: .leading, spacing: Spacing.sm) {
                                if viewModel.currentTranscript.isEmpty {
                                    Text(viewModel.emptyTranscriptText)
                                        .foregroundStyle(.secondary)
                                        .italic()
                                        .frame(maxWidth: .infinity, alignment: .leading)
                                        .padding()
                                } else {
                                    VStack(alignment: .leading, spacing: Spacing.xs) {
                                        if !viewModel.committedTranscript.isEmpty {
                                            Text(viewModel.committedTranscript)
                                                .font(.body)
                                                .lineSpacing(4)
                                                .textSelection(.enabled)
                                                .accessibilityAddTraits(.updatesFrequently)
                                        }
                                        if !viewModel.interimTranscript.isEmpty {
                                            Text(viewModel.interimTranscript)
                                                .font(.body.italic())
                                                .lineSpacing(4)
                                                .foregroundStyle(Palette.textTertiary)
                                                .textSelection(.enabled)
                                                .accessibilityHidden(true)
                                        }
                                    }
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                    .padding()
                                    .id("transcript-bottom")
                                }
                            }
                        }
                        .frame(maxHeight: 220)
                        .background(Color.gray.opacity(0.1))
                        .cornerRadius(12)
                        .padding(.horizontal)
                        .onChange(of: viewModel.currentTranscript) { _, _ in
                            withAnimation {
                                proxy.scrollTo("transcript-bottom", anchor: .bottom)
                            }
                        }
                    }
                    .accessibilityElement(children: .contain)
                    .accessibilityIdentifier("live-transcript")
                }

                Spacer()

                // Target folder selector — only while idle, so the choice can't
                // change mid-recording. Defaults to All Recordings (nil folderId).
                if viewModel.phase == .idle {
                    folderSelector
                }

                // Record controls
                HStack(spacing: 24) {
                    if viewModel.phase == .recording {
                        Button(action: {
                            Task {
                                if viewModel.canResumeRecording {
                                    await viewModel.resumeRecording()
                                } else {
                                    await viewModel.pauseRecording()
                                }
                            }
                        }) {
                            ZStack {
                                Circle()
                                    .fill(Color.secondary.opacity(0.16))
                                    .frame(width: 64, height: 64)

                                Image(systemName: viewModel.canResumeRecording ? "play.fill" : "pause.fill")
                                    .font(.system(size: 24, weight: .semibold))
                                    .foregroundStyle(.primary)
                            }
                        }
                        .accessibilityLabel(viewModel.canResumeRecording
                            ? t("Resume Recording", "Продолжить запись")
                            : t("Pause Recording", "Поставить запись на паузу"))
                        .accessibilityIdentifier(viewModel.canResumeRecording ? "resume-recording-button" : "pause-recording-button")
                    }

                    Button(action: {
                        Task {
                            if viewModel.canStopRecording {
                                await viewModel.stopRecording()
                            } else if viewModel.canStartRecording {
                                await viewModel.startRecording(
                                    apiClient: appState.getAPIClient(),
                                    folderId: selectedFolderId
                                )
                            }
                        }
                    }) {
                        ZStack {
                            Circle()
                                .fill(buttonColor)
                                .frame(width: 80, height: 80)

                            if viewModel.canStopRecording {
                                RoundedRectangle(cornerRadius: 8)
                                    .fill(.white)
                                    .frame(width: 30, height: 30)
                            } else if viewModel.isBusy {
                                ProgressView()
                                    .tint(.white)
                            } else {
                                Circle()
                                    .fill(.white)
                                    .frame(width: 30, height: 30)
                            }
                        }
                    }
                    .disabled(viewModel.isBusy)
                    .accessibilityLabel(recordButtonAccessibilityLabel)
                    .accessibilityHint(recordButtonAccessibilityHint)
                    .accessibilityIdentifier("record-button")

                    if viewModel.canDiscardRecording {
                        Button(action: { showingDiscardConfirm = true }) {
                            ZStack {
                                Circle()
                                    .fill(Color.secondary.opacity(0.16))
                                    .frame(width: 64, height: 64)

                                Image(systemName: "trash")
                                    .font(.system(size: 22, weight: .semibold))
                                    .foregroundStyle(.red)
                            }
                        }
                        .accessibilityLabel(t("Discard Recording", "Не сохранять запись"))
                        .accessibilityIdentifier("discard-recording-button")
                    }
                }

                // Status text
                Text(viewModel.statusText)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .padding(.bottom)
                    .accessibilityLabel(viewModel.statusText)
            }
            .navigationTitle(t("Record", "Запись"))
            .accessibilityIdentifier("recording-view")
            .alert(t("Error", "Ошибка"), isPresented: .constant(viewModel.error != nil)) {
                Button(t("OK", "ОК")) { viewModel.error = nil }
            } message: {
                Text(viewModel.error ?? "")
            }
            .confirmationDialog(
                t("Discard this recording?", "Удалить эту запись?"),
                isPresented: $showingDiscardConfirm,
                titleVisibility: .visible
            ) {
                Button(role: .destructive) {
                    Task { await viewModel.discardRecording() }
                } label: {
                    Text(t("Discard", "Не сохранять"))
                }
                .accessibilityIdentifier("discard-recording-confirm")
                Button(role: .cancel) { } label: {
                    Text(t("Cancel", "Отмена"))
                }
            } message: {
                Text(t("This action cannot be undone. Your audio and transcript will be deleted.",
                       "Это действие нельзя отменить. Ваше аудио и расшифровка будут удалены."))
            }
            .onChange(of: viewModel.isServerComplete) { _, completed in
                if completed {
                    viewModel.resetState()
                }
            }
            .alert(t("Couldn't load folders", "Не удалось загрузить папки"), isPresented: Binding(
                get: { foldersError != nil },
                set: { if !$0 { foldersError = nil } }
            )) {
                Button(t("Retry", "Повторить")) {
                    Task { await loadFolders() }
                }
                Button(t("OK", "ОК"), role: .cancel) { foldersError = nil }
            } message: {
                Text(foldersError ?? "")
            }
            .task {
                await loadFolders()
            }
        }
    }

    // MARK: - Folder Selector

    private var folderSelector: some View {
        Menu {
            Picker(selection: $selectedFolderId) {
                Text(t("All Recordings", "Все записи")).tag(String?.none)
                ForEach(folders) { folder in
                    Text(folder.name).tag(String?.some(folder.id))
                }
            } label: {
                EmptyView()
            }
        } label: {
            HStack(spacing: 6) {
                Image(systemName: "folder")
                Text(selectedFolderName)
                    .lineLimit(1)
                Image(systemName: "chevron.up.chevron.down")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
            .font(.subheadline)
            .padding(.horizontal, 14)
            .padding(.vertical, 8)
            .background(Color.secondary.opacity(0.12))
            .clipShape(Capsule())
        }
        .accessibilityLabel(t("Save to folder", "Сохранить в папку") + ": " + selectedFolderName)
        .accessibilityIdentifier("recording-folder-picker")
    }

    private func loadFolders() async {
        guard !isScreenshotMode else { return }
        do {
            let fetched = try await appState.getAPIClient().listFolders()
            folders = fetched
            // Drop a stale selection if the chosen folder no longer exists.
            if let selectedFolderId, !fetched.contains(where: { $0.id == selectedFolderId }) {
                self.selectedFolderId = nil
            }
        } catch {
            foldersError = error.userFacingMessage(context: .library)
        }
    }

    private var isReconnecting: Bool {
        if case .reconnecting = viewModel.connectionState { return true }
        return false
    }

    private var outerIndicatorColor: Color {
        switch viewModel.phase {
        case .recording:
            if viewModel.isPaused { return Color.gray.opacity(0.14) }
            return isReconnecting ? Color.orange.opacity(0.2) : Color.red.opacity(0.2)
        case .preparing, .finalizing:
            return Color.orange.opacity(0.18)
        case .idle:
            return Color.gray.opacity(0.1)
        }
    }

    private var innerIndicatorColor: Color {
        switch viewModel.phase {
        case .recording:
            if viewModel.isPaused { return Color.gray.opacity(0.25) }
            return isReconnecting ? Color.orange.opacity(0.4) : Color.red.opacity(0.4)
        case .preparing, .finalizing:
            return Color.orange.opacity(0.28)
        case .idle:
            return Color.gray.opacity(0.2)
        }
    }

    private var indicatorSymbolName: String {
        switch viewModel.phase {
        case .recording:
            if viewModel.isPaused { return "pause.fill" }
            return "waveform"
        case .preparing, .finalizing:
            return "hourglass"
        case .idle:
            return "mic.fill"
        }
    }

    private var indicatorSymbolColor: Color {
        switch viewModel.phase {
        case .recording:
            if viewModel.isPaused { return .gray }
            return .red
        case .preparing, .finalizing:
            return .orange
        case .idle:
            return .gray
        }
    }

    private var recordButtonAccessibilityLabel: String {
        switch viewModel.phase {
        case .recording:
            return t("Stop Recording", "Остановить запись")
        case .preparing:
            return t("Preparing", "Подготовка")
        case .finalizing:
            return t("Saving", "Сохранение")
        case .idle:
            return t("Start Recording", "Начать запись")
        }
    }

    private var recordButtonAccessibilityHint: String {
        switch viewModel.phase {
        case .recording:
            return t("Double tap to stop recording", "Дважды нажмите, чтобы остановить запись")
        case .preparing, .finalizing:
            return t("Please wait", "Пожалуйста, подождите")
        case .idle:
            return t("Double tap to start recording", "Дважды нажмите, чтобы начать запись")
        }
    }

    private var durationAccessibilityLabel: String {
        let minutes = Int(viewModel.duration) / 60
        let seconds = Int(viewModel.duration) % 60
        let prefix = t("Recording duration:", "Длительность записи:")
        if minutes > 0 {
            let minuteWord = minuteWord(minutes)
            let secondWord = secondWord(seconds)
            return "\(prefix) \(minutes) \(minuteWord) \(seconds) \(secondWord)"
        } else {
            let secondWord = secondWord(seconds)
            return "\(prefix) \(seconds) \(secondWord)"
        }
    }

    private func minuteWord(_ value: Int) -> String {
        languageManager.current == .russian
            ? russianPlural(value, one: "минута", few: "минуты", many: "минут")
            : (value == 1 ? "minute" : "minutes")
    }

    private func secondWord(_ value: Int) -> String {
        languageManager.current == .russian
            ? russianPlural(value, one: "секунда", few: "секунды", many: "секунд")
            : (value == 1 ? "second" : "seconds")
    }

    private func russianPlural(_ value: Int, one: String, few: String, many: String) -> String {
        let mod100 = value % 100
        if mod100 >= 11 && mod100 <= 14 { return many }
        switch value % 10 {
        case 1: return one
        case 2, 3, 4: return few
        default: return many
        }
    }

    private var buttonColor: Color {
        switch viewModel.phase {
        case .recording:
            return .red
        case .preparing, .finalizing:
            return .gray
        case .idle:
            return .blue
        }
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

#Preview {
    RecordingView()
        .environmentObject(AppState())
        .environmentObject(RecordingViewModel())
        .environmentObject(LanguageManager.shared)
}
