import SwiftUI
import WaiComputerKit

struct RecordingView: View {
    @EnvironmentObject var appState: AppState
    @EnvironmentObject var viewModel: RecordingViewModel
    @EnvironmentObject var languageManager: LanguageManager
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass
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
            recordingContent
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

    @ViewBuilder
    private var recordingContent: some View {
        if horizontalSizeClass == .regular {
            regularRecordingLayout
        } else {
            compactRecordingLayout
        }
    }

    private var compactRecordingLayout: some View {
        VStack(spacing: 0) {
            ScrollView {
                VStack(spacing: Spacing.lg) {
                    compactRecordingHero
                    statusBanners

                    if viewModel.shouldShowTranscript {
                        liveTranscriptPreview(maxHeight: 260)
                    } else {
                        compactRecordingStatusCard
                    }
                }
                .padding(.horizontal, Spacing.lg)
                .padding(.top, Spacing.xl)
                .padding(.bottom, Spacing.lg)
                .frame(maxWidth: .infinity)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)

            Divider()

            VStack(spacing: Spacing.md) {
                // Target folder selector — only while idle, so the choice can't
                // change mid-recording. Defaults to All Recordings (nil folderId).
                if viewModel.phase == .idle {
                    folderSelector
                }

                compactControlRow

                Text(viewModel.statusText)
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textSecondary)
                    .lineLimit(2)
                    .multilineTextAlignment(.center)
                    .accessibilityLabel(viewModel.statusText)
            }
            .padding(.horizontal, Spacing.lg)
            .padding(.vertical, Spacing.lg)
            .background(.bar)
        }
        .background(Color(uiColor: .systemGroupedBackground))
        .accessibilityIdentifier("recording-compact-layout")
    }

    private var regularRecordingLayout: some View {
        VStack(spacing: 0) {
            regularRecordingHeader
            Divider()

            ScrollView {
                VStack(spacing: Spacing.xl) {
                    statusBanners
                    regularStatusBody
                }
                .frame(maxWidth: 760)
                .padding(.horizontal, Spacing.xxl)
                .padding(.vertical, Spacing.xxl)
                .frame(maxWidth: .infinity)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)

            Divider()
            regularControlBar
        }
        .background(Color(uiColor: .systemGroupedBackground))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("recording-regular-layout")
    }

    private var compactRecordingHero: some View {
        HStack(alignment: .center, spacing: Spacing.md) {
            headerStatusGlyph

            VStack(alignment: .leading, spacing: Spacing.xxs) {
                Text(headerTitle)
                    .font(Typography.displaySmall)
                    .foregroundStyle(Palette.textPrimary)
                    .lineLimit(1)

                Text(compactSubtitle)
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textSecondary)
                    .lineLimit(2)
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            Text(viewModel.formattedDuration)
                .font(Typography.monoLarge)
                .foregroundStyle(viewModel.phase == .idle ? Palette.textSecondary : Palette.textPrimary)
                .monospacedDigit()
                .accessibilityLabel(durationAccessibilityLabel)
                .accessibilityAddTraits(.updatesFrequently)
        }
        .padding(Spacing.lg)
        .background(Palette.surfaceSubtle)
        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .strokeBorder(Palette.border, lineWidth: 1)
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("recording-compact-hero")
    }

    private var compactRecordingStatusCard: some View {
        VStack(spacing: Spacing.md) {
            ZStack {
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .fill(Palette.surfaceSubtle)
                    .frame(width: 64, height: 64)
                    .overlay(
                        RoundedRectangle(cornerRadius: 14, style: .continuous)
                            .strokeBorder(Palette.border, lineWidth: 1)
                    )

                Image(systemName: indicatorSymbolName)
                    .font(.system(size: 30, weight: .semibold))
                    .foregroundStyle(indicatorSymbolColor)
            }

            Text(viewModel.emptyTranscriptText)
                .font(Typography.reading)
                .foregroundStyle(Palette.textSecondary)
                .multilineTextAlignment(.center)
                .lineSpacing(4)
                .frame(maxWidth: 320)
                .accessibilityIdentifier("recording-final-transcription-status")
        }
        .frame(maxWidth: .infinity, minHeight: 220)
        .padding(Spacing.xl)
        .background(Color(uiColor: .secondarySystemGroupedBackground))
        .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .strokeBorder(Palette.border, lineWidth: 1)
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("recording-compact-status-card")
    }

    private var regularRecordingHeader: some View {
        HStack(spacing: Spacing.md) {
            headerStatusGlyph

            VStack(alignment: .leading, spacing: Spacing.xxs) {
                Text(headerTitle)
                    .font(Typography.displaySmall)
                    .foregroundStyle(Palette.textPrimary)
                    .lineLimit(1)

                Text(viewModel.phase == .idle
                    ? t("Capture a meeting or thought into your Inbox.", "Сохрани встречу или мысль в Инбокс.")
                    : viewModel.emptyTranscriptText)
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textSecondary)
                    .lineLimit(2)
            }

            Spacer()

            Text(viewModel.formattedDuration)
                .font(Typography.monoLarge)
                .foregroundStyle(Palette.textSecondary)
                .accessibilityLabel(durationAccessibilityLabel)
                .accessibilityAddTraits(.updatesFrequently)

            if viewModel.phase == .idle {
                folderSelector
            }
        }
        .padding(.horizontal, Spacing.xxl)
        .padding(.vertical, Spacing.xl)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("recording-regular-header")
    }

    @ViewBuilder
    private var headerStatusGlyph: some View {
        if viewModel.phase == .recording, viewModel.isPaused {
            Image(systemName: "pause.fill")
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(Palette.textSecondary)
                .frame(width: 18, height: 18)
        } else if viewModel.phase == .recording {
            Circle()
                .fill(Palette.recording)
                .frame(width: 12, height: 12)
                .modifier(IOSRecordingPulseModifier())
                .frame(width: 18, height: 18)
        } else if viewModel.phase == .idle {
            Image(systemName: "waveform")
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(Palette.accent)
                .frame(width: 18, height: 18)
        } else {
            ProgressView()
                .controlSize(.small)
                .frame(width: 18, height: 18)
        }
    }

    @ViewBuilder
    private var regularStatusBody: some View {
        if viewModel.shouldShowTranscript {
            liveTranscriptPreview(maxHeight: nil)
        } else {
            VStack(spacing: Spacing.lg) {
                ZStack {
                    RoundedRectangle(cornerRadius: 14, style: .continuous)
                        .fill(Palette.surfaceSubtle)
                        .frame(width: 72, height: 72)
                        .overlay(
                            RoundedRectangle(cornerRadius: 14, style: .continuous)
                                .strokeBorder(Palette.border, lineWidth: 1)
                        )

                    Image(systemName: indicatorSymbolName)
                        .font(.system(size: 34, weight: .semibold))
                        .foregroundStyle(indicatorSymbolColor)
                }

                Text(viewModel.emptyTranscriptText)
                    .font(Typography.reading)
                    .foregroundStyle(Palette.textSecondary)
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: 560)
                    .accessibilityIdentifier("recording-final-transcription-status")
            }
            .frame(maxWidth: .infinity, minHeight: 300)
        }
    }

    private var regularControlBar: some View {
        HStack(spacing: Spacing.md) {
            Spacer()

            if viewModel.phase == .preparing || viewModel.canDiscardRecording {
                Button(role: viewModel.phase == .preparing ? nil : .destructive) {
                    if viewModel.phase == .preparing {
                        Task { await viewModel.discardRecording() }
                    } else {
                        showingDiscardConfirm = true
                    }
                } label: {
                    Label(viewModel.phase == .preparing
                          ? t("Cancel", "Отмена")
                          : t("Discard", "Не сохранять"),
                          systemImage: "trash")
                        .font(Typography.headingSmall)
                }
                .buttonStyle(.bordered)
                .controlSize(.large)
                .accessibilityIdentifier("discard-recording-button")
            }

            if viewModel.phase == .recording {
                Button {
                    Task {
                        if viewModel.canResumeRecording {
                            await viewModel.resumeRecording()
                        } else {
                            await viewModel.pauseRecording()
                        }
                    }
                } label: {
                    Label(
                        viewModel.canResumeRecording ? t("Resume", "Продолжить") : t("Pause", "Пауза"),
                        systemImage: viewModel.canResumeRecording ? "play.fill" : "pause.fill"
                    )
                    .font(Typography.headingSmall)
                    .frame(minWidth: 120)
                }
                .buttonStyle(.bordered)
                .controlSize(.large)
                .disabled(!viewModel.canPauseRecording && !viewModel.canResumeRecording)
                .accessibilityIdentifier(viewModel.canResumeRecording ? "resume-recording-button" : "pause-recording-button")
            }

            Button(action: recordButtonAction) {
                Label(recordButtonTitle, systemImage: recordButtonSystemImage)
                    .font(Typography.headingSmall)
                    .frame(minWidth: 150)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .tint(viewModel.canStopRecording ? Palette.recording : Palette.accent)
            .disabled(viewModel.isBusy)
            .accessibilityLabel(recordButtonAccessibilityLabel)
            .accessibilityHint(recordButtonAccessibilityHint)
            .accessibilityIdentifier("record-button")

            Spacer()
        }
        .padding(.horizontal, Spacing.xxl)
        .padding(.vertical, Spacing.xl)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("recording-regular-controls")
    }

    private var compactControlRow: some View {
        HStack(spacing: Spacing.sm) {
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
                    Label(
                        viewModel.canResumeRecording ? t("Resume", "Продолжить") : t("Pause", "Пауза"),
                        systemImage: viewModel.canResumeRecording ? "play.fill" : "pause.fill"
                    )
                    .labelStyle(.iconOnly)
                    .font(Typography.headingSmall)
                    .frame(width: 46, height: 46)
                }
                .buttonStyle(.bordered)
                .controlSize(.large)
                .disabled(!viewModel.canPauseRecording && !viewModel.canResumeRecording)
                .accessibilityLabel(viewModel.canResumeRecording
                    ? t("Resume Recording", "Продолжить запись")
                    : t("Pause Recording", "Поставить запись на паузу"))
                .accessibilityIdentifier(viewModel.canResumeRecording ? "resume-recording-button" : "pause-recording-button")
            }

            Button(action: recordButtonAction) {
                HStack(spacing: Spacing.xs) {
                    Label(recordButtonTitle, systemImage: recordButtonSystemImage)
                        .font(Typography.headingSmall)

                    if viewModel.isBusy {
                        ProgressView()
                            .controlSize(.small)
                    }
                }
                .frame(maxWidth: .infinity, minHeight: 46)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .tint(buttonColor)
            .disabled(viewModel.isBusy)
            .accessibilityLabel(recordButtonAccessibilityLabel)
            .accessibilityHint(recordButtonAccessibilityHint)
            .accessibilityIdentifier("record-button")

            if viewModel.canDiscardRecording {
                Button(action: { showingDiscardConfirm = true }) {
                    Label(t("Discard", "Не сохранять"), systemImage: "trash")
                        .labelStyle(.iconOnly)
                        .font(Typography.headingSmall)
                        .frame(width: 46, height: 46)
                }
                .buttonStyle(.bordered)
                .controlSize(.large)
                .tint(Palette.recording)
                .accessibilityLabel(t("Discard Recording", "Не сохранять запись"))
                .accessibilityIdentifier("discard-recording-button")
            }
        }
        .frame(maxWidth: .infinity)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("recording-compact-controls")
    }

    @ViewBuilder
    private var statusBanners: some View {
        if viewModel.liveTranscriptionOffline && viewModel.phase == .recording {
            warningBanner(
                title: t("Live transcription unavailable", "Живая расшифровка недоступна"),
                message: t(
                    "Audio is recording locally — transcript will be generated when you stop.",
                    "Аудио записывается локально — расшифровка появится, когда вы остановите запись."
                ),
                systemImage: "wifi.exclamationmark",
                accessibilityLabel: t(
                    "Live transcription unavailable. Audio is recording locally and will be transcribed after you stop.",
                    "Живая расшифровка недоступна. Аудио записывается локально и будет расшифровано после остановки."
                ),
                identifier: "live-transcription-offline-banner"
            )
        }

        if case .reconnecting(let attempt, let maxAttempts) = viewModel.connectionState {
            warningBanner(
                title: t("Reconnecting…", "Переподключение…") + " (\(attempt)/\(maxAttempts))",
                message: t("Audio is being buffered", "Аудио сохраняется локально"),
                systemImage: nil,
                accessibilityLabel: t(
                    "Reconnecting, attempt \(attempt) of \(maxAttempts)",
                    "Переподключение, попытка \(attempt) из \(maxAttempts)"
                ),
                identifier: "reconnection-banner",
                showsProgress: true
            )
        }
    }

    private func warningBanner(
        title: String,
        message: String,
        systemImage: String?,
        accessibilityLabel: String,
        identifier: String,
        showsProgress: Bool = false
    ) -> some View {
        HStack(alignment: .top, spacing: Spacing.md) {
            ZStack {
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .fill(Palette.accentSubtle)
                    .frame(width: 34, height: 34)

                if showsProgress {
                    ProgressView()
                        .tint(Palette.accent)
                        .controlSize(.small)
                } else if let systemImage {
                    Image(systemName: systemImage)
                        .font(Typography.headingSmall)
                        .foregroundStyle(Palette.accent)
                }
            }
            .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: Spacing.xxs) {
                Text(title)
                    .font(Typography.headingSmall)
                    .foregroundStyle(Palette.textPrimary)
                    .lineLimit(2)
                Text(message)
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textSecondary)
                    .lineLimit(3)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(Spacing.md)
        .background(Palette.accentSubtle)
        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .strokeBorder(Palette.border, lineWidth: 1)
        }
        .accessibilityLabel(accessibilityLabel)
        .accessibilityIdentifier(identifier)
    }

    @ViewBuilder
    private func liveTranscriptPreview(maxHeight: CGFloat?) -> some View {
        if viewModel.shouldShowTranscript {
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: Spacing.sm) {
                        if viewModel.currentTranscript.isEmpty {
                            Text(viewModel.emptyTranscriptText)
                                .font(Typography.reading)
                                .foregroundStyle(Palette.textSecondary)
                                .italic()
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .padding()
                        } else {
                            VStack(alignment: .leading, spacing: Spacing.xs) {
                                if !viewModel.committedTranscript.isEmpty {
                                    Text(viewModel.committedTranscript)
                                        .font(Typography.reading)
                                        .lineSpacing(5)
                                        .textSelection(.enabled)
                                        .accessibilityAddTraits(.updatesFrequently)
                                }
                                if !viewModel.interimTranscript.isEmpty {
                                    Text(viewModel.interimTranscript)
                                        .font(Typography.reading.italic())
                                        .lineSpacing(5)
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
                .frame(maxHeight: maxHeight)
                .background(Color(uiColor: .secondarySystemGroupedBackground))
                .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
                .overlay {
                    RoundedRectangle(cornerRadius: 14, style: .continuous)
                        .strokeBorder(Palette.border, lineWidth: 1)
                }
                .onChange(of: viewModel.currentTranscript) { _, _ in
                    withAnimation {
                        proxy.scrollTo("transcript-bottom", anchor: .bottom)
                    }
                }
            }
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("live-transcript")
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
                    .font(Typography.labelSmall)
                    .foregroundStyle(Palette.textTertiary)
            }
            .font(Typography.label)
            .padding(.horizontal, 14)
            .padding(.vertical, 8)
            .background(Palette.surfaceSubtle)
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
            if viewModel.isPaused { return Palette.textSecondary }
            return Palette.recording
        case .preparing, .finalizing:
            return Palette.accent
        case .idle:
            return Palette.accent
        }
    }

    private var headerTitle: String {
        switch viewModel.phase {
        case .idle:
            return t("New Recording", "Новая запись")
        default:
            return viewModel.statusText
        }
    }

    private var compactSubtitle: String {
        switch viewModel.phase {
        case .idle:
            return t("Capture a meeting or thought into your Inbox.", "Сохрани встречу или мысль в Инбокс.")
        default:
            return viewModel.emptyTranscriptText
        }
    }

    private var recordButtonTitle: String {
        switch viewModel.phase {
        case .recording:
            return t("Stop", "Остановить")
        case .preparing:
            return t("Preparing", "Подготовка")
        case .finalizing:
            return t("Saving", "Сохранение")
        case .idle:
            return t("Record", "Записать")
        }
    }

    private var recordButtonSystemImage: String {
        switch viewModel.phase {
        case .recording:
            return "stop.fill"
        case .preparing, .finalizing:
            return "hourglass"
        case .idle:
            return "waveform"
        }
    }

    private func recordButtonAction() {
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
            return Palette.recording
        case .preparing, .finalizing:
            return Palette.textTertiary
        case .idle:
            return Palette.accent
        }
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

private struct IOSRecordingPulseModifier: ViewModifier {
    @State private var isPulsing = false

    func body(content: Content) -> some View {
        content
            .opacity(isPulsing ? 0.4 : 1)
            .animation(.easeInOut(duration: 0.8).repeatForever(autoreverses: true), value: isPulsing)
            .onAppear { isPulsing = true }
    }
}

#Preview {
    RecordingView()
        .environmentObject(AppState())
        .environmentObject(RecordingViewModel())
        .environmentObject(LanguageManager.shared)
}
