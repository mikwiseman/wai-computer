import SwiftUI
import AVFoundation
import WaiSayKit

struct MacSettingsView: View {
    @EnvironmentObject var appState: MacAppState
    @EnvironmentObject var dictationManager: DictationManager
    @Environment(\.scenePhase) private var scenePhase
    @State private var showSignOutConfirmation = false
    @State private var showDeleteAccountConfirmation = false
    @State private var isDeletingAccount = false
    @State private var deleteAccountError: String?
    @State private var hasMicrophonePermission = MacSettingsView.hasMicrophonePermission
    @State private var accessibilityStatus: MacInputPermission.Status = .denied
    @State private var permissionPollTimer: Timer?
    @AppStorage("transcriptionLanguage") private var transcriptionLanguage = "multi"
    @AppStorage(MacPresentationSettings.showDockIconWhenMainWindowClosedKey) private var showDockIconWhenMainWindowClosed = false
    @AppStorage(BetaChannelStore.userDefaultsKey) private var receiveBetaUpdates = false
    @EnvironmentObject var languageStore: DictationLanguageStore
    @State private var summaryLanguage = "auto"
    @State private var summaryStyle = "medium"
    @State private var summaryInstructions = ""
    @State private var settingsLoaded = false
    @State private var settingsError: String?
    @State private var transcriptionOptions: TranscriptionOptions?
    @State private var dictationLiveSTTSelection = "openai:gpt-realtime-whisper"
    @State private var recordingLiveSTTSelection = "elevenlabs:scribe_v2_realtime"
    @State private var fileSTTSelection = "elevenlabs:scribe_v2"
    @State private var dictationPostFilterEnabled = true
    @State private var dictationPostFilterSelection = "anthropic:claude-haiku-4-5"

    private let languageOptions: [(label: String, value: String)] = [
        ("Auto-detect (Multi-language)", "multi"),
        ("English", "en"),
        ("Russian", "ru"),
        ("Spanish", "es"),
        ("German", "de"),
        ("French", "fr"),
        ("Japanese", "ja"),
        ("Chinese", "zh"),
    ]

    private let summaryLanguageOptions: [(label: String, value: String)] = [
        ("Auto (match transcript)", "auto"),
        ("English", "en"),
        ("Russian", "ru"),
        ("Spanish", "es"),
        ("German", "de"),
        ("French", "fr"),
        ("Japanese", "ja"),
        ("Chinese", "zh"),
    ]

    private let summaryStyleOptions: [(label: String, value: String)] = [
        ("Brief", "brief"),
        ("Medium", "medium"),
        ("Detailed", "detailed"),
    ]

    var body: some View {
        Form {
            Section {
                if let user = appState.currentUser {
                    LabeledContent("Email", value: user.email)
                        .font(Typography.body)
                    LabeledContent("Member Since", value: user.createdAt.formatted(date: .long, time: .omitted))
                        .font(Typography.body)
                }
            } header: {
                Text("Account")
                    .waiSectionHeader()
                    .accessibilityIdentifier("settings-account-header")
            }

            Section {
                LanguagePickerView(store: languageStore)
                    .padding(.vertical, 4)
            } header: {
                Text("Dictation languages")
                    .waiSectionHeader()
                    .accessibilityIdentifier("settings-transcription-header")
            } footer: {
                Text("Affects live dictation. Recording transcription auto-detects.")
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textTertiary)
            }

            Section {
                if let transcriptionOptions {
                    transcriptionModelPicker(
                        "Dictation live",
                        selection: $dictationLiveSTTSelection,
                        options: transcriptionOptions.dictationLiveSTT,
                        identifier: "settings-dictation-live-stt-picker",
                        save: { await saveDictationLiveSTT(selection: $0) }
                    )

                    transcriptionModelPicker(
                        "Recording live",
                        selection: $recordingLiveSTTSelection,
                        options: transcriptionOptions.recordingLiveSTT,
                        identifier: "settings-recording-live-stt-picker",
                        save: { await saveRecordingLiveSTT(selection: $0) }
                    )

                    transcriptionModelPicker(
                        "Full session",
                        selection: $fileSTTSelection,
                        options: transcriptionOptions.fileSTT,
                        identifier: "settings-file-stt-picker",
                        save: { await saveFileSTT(selection: $0) }
                    )

                    if let settingsError {
                        Text(settingsError)
                            .font(Typography.caption)
                            .foregroundStyle(.red)
                    }
                } else if let settingsError {
                    Text(settingsError)
                        .font(Typography.caption)
                        .foregroundStyle(.red)
                } else {
                    ProgressView()
                        .controlSize(.small)
                }
            } header: {
                Text("Transcription Models")
                    .waiSectionHeader()
                    .accessibilityIdentifier("settings-transcription-models-header")
            }

            Section {
                Toggle("Show Dock icon after closing main window", isOn: $showDockIconWhenMainWindowClosed)
                    .font(Typography.body)
                    .accessibilityIdentifier("settings-show-dock-icon-when-closed-toggle")
                    .onChange(of: showDockIconWhenMainWindowClosed) { _, _ in
                        MacPresentationCoordinator.shared.updateActivationPolicyForCurrentWindowState()
                    }

                Text("When disabled, WaiSay keeps running from the menu bar after the main window closes.")
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textTertiary)
            } header: {
                Text("App Behavior")
                    .waiSectionHeader()
                    .accessibilityIdentifier("settings-app-behavior-header")
            }

            // MARK: - Summary Settings

            Section {
                Picker("Language", selection: $summaryLanguage) {
                    ForEach(summaryLanguageOptions, id: \.value) { option in
                        Text(option.label).tag(option.value)
                    }
                }
                .font(Typography.body)
                .onChange(of: summaryLanguage) { _, newValue in
                    Task { await saveSummarySettings(language: newValue) }
                }

                Picker("Detail Level", selection: $summaryStyle) {
                    ForEach(summaryStyleOptions, id: \.value) { option in
                        Text(option.label).tag(option.value)
                    }
                }
                .font(Typography.body)
                .onChange(of: summaryStyle) { _, newValue in
                    Task { await saveSummarySettings(style: newValue) }
                }

                VStack(alignment: .leading, spacing: Spacing.xs) {
                    Text("Custom Instructions")
                        .font(Typography.label)
                        .foregroundStyle(Palette.textSecondary)
                    TextEditor(text: $summaryInstructions)
                        .font(Typography.body)
                        .frame(height: 60)
                        .scrollContentBackground(.hidden)
                        .background(Palette.surfaceSubtle)
                        .cornerRadius(6)
                        .onChange(of: summaryInstructions) { _, _ in
                            Task { await saveSummarySettings(instructions: summaryInstructions) }
                        }
                    Text("E.g. \"Focus on action items\" or \"Write formally\"")
                        .font(Typography.caption)
                        .foregroundStyle(Palette.textTertiary)
                }
            } header: {
                Text("AI Summary")
                    .waiSectionHeader()
                    .accessibilityIdentifier("settings-summary-header")
            }

            // MARK: - Dictation Settings

            Section {
                Toggle("Enable Dictation", isOn: $dictationManager.isFeatureEnabled)
                    .font(Typography.body)
                    .onChange(of: dictationManager.isFeatureEnabled) { _, enabled in
                        refreshPermissions()
                        if enabled, !dictationPermissionsReady {
                            startPermissionPolling()
                        }
                    }

                Picker("Push to talk", selection: Binding(
                    get: { dictationManager.selectedHotkey },
                    set: { dictationManager.updateHotkey($0) }
                )) {
                    ForEach(DictationHotkey.allCases) { hotkey in
                        Text(hotkey.label).tag(hotkey)
                    }
                }
                .font(Typography.body)
                .disabled(!dictationManager.isFeatureEnabled)
                .accessibilityIdentifier("settings-push-to-talk-picker")

                Picker("Hands-free toggle", selection: Binding<DictationHotkey?>(
                    get: { dictationManager.selectedHandsFreeHotkey },
                    set: { dictationManager.updateHandsFreeHotkey($0) }
                )) {
                    Text("Double-tap of push-to-talk").tag(DictationHotkey?.none)
                    ForEach(DictationHotkey.allCases) { hotkey in
                        Text(hotkey.label).tag(DictationHotkey?.some(hotkey))
                    }
                }
                .font(Typography.body)
                .disabled(!dictationManager.isFeatureEnabled)
                .accessibilityIdentifier("settings-hands-free-picker")

                Toggle("Post-filter dictated text", isOn: $dictationPostFilterEnabled)
                    .font(Typography.body)
                    .disabled(!dictationManager.isFeatureEnabled)
                    .accessibilityIdentifier("settings-dictation-post-filter-toggle")
                    .onChange(of: dictationPostFilterEnabled) { _, enabled in
                        guard settingsLoaded else { return }
                        Task { await saveDictationPostFilterEnabled(enabled) }
                    }

                if let transcriptionOptions, dictationPostFilterEnabled {
                    transcriptionModelPicker(
                        "Post-filter model",
                        selection: $dictationPostFilterSelection,
                        options: transcriptionOptions.dictationPostFilter,
                        identifier: "settings-dictation-post-filter-model-picker",
                        save: { await saveDictationPostFilter(selection: $0) }
                    )
                    .disabled(!dictationManager.isFeatureEnabled)
                }

                permissionRow(
                    title: "Microphone",
                    status: hasMicrophonePermission ? .granted : .denied,
                    identifierBase: "settings-permission-microphone",
                    grantAction: requestMicrophonePermission,
                    settingsAction: nil,
                    restartAction: nil
                )

                permissionRow(
                    title: "Accessibility",
                    status: accessibilityStatus,
                    identifierBase: "settings-permission-accessibility",
                    grantAction: openAccessibilitySettings,
                    settingsAction: { MacPrivacySettings.openAccessibility() },
                    restartAction: MacPrivacySettings.restartForPermissionRefresh
                )

                // Usage hint
                VStack(alignment: .leading, spacing: Spacing.xs) {
                    Text("How to use")
                        .font(Typography.label)
                        .foregroundStyle(Palette.textSecondary)
                    Text(dictationUsageText)
                        .font(Typography.caption)
                        .foregroundStyle(Palette.textTertiary)
                    Text(dictationPrivacyText)
                        .font(Typography.caption)
                        .foregroundStyle(Palette.textTertiary)
                }

                // Recovery actions for permission state drift after updates
                HStack(spacing: Spacing.sm) {
                    Button("Re-run Setup") {
                        UserDefaults.standard.set(false, forKey: MacAppState.onboardingCompletedKey)
                        UserDefaults.standard.removeObject(forKey: MacAppState.onboardingCurrentPageKey)
                        appState.hasCompletedOnboarding = false
                    }
                    .font(Typography.bodySmall)
                    .accessibilityIdentifier("settings-rerun-setup-button")

                    Button("Reveal in Finder") {
                        MacInputPermission.revealAppInFinder()
                    }
                    .font(Typography.bodySmall)
                    .accessibilityIdentifier("settings-reveal-app-button")

                    Button("Reset Permissions") {
                        MacInputPermission.resetTCCEntries()
                        MacPrivacySettings.restartForPermissionRefresh()
                    }
                    .font(Typography.bodySmall)
                    .accessibilityIdentifier("settings-reset-permissions-button")
                }
            } header: {
                Text("Dictation")
                    .waiSectionHeader()
            }

            Section {
                LabeledContent("Version") {
                    let version = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0.0"
                    let build = Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "1"
                    Text("\(version) (\(build))")
                        .font(Typography.mono)
                }
                Toggle("Receive beta updates", isOn: $receiveBetaUpdates)
                    .font(Typography.body)
                    .accessibilityIdentifier("settings-receive-beta-updates-toggle")
                Text("Get new features and fixes earlier. Beta builds are signed and notarized but may contain bugs. Turn off to return to stable updates only.")
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textTertiary)
                Button("Check for Updates…") {
                    NotificationCenter.default.post(name: .waisayCheckForUpdates, object: nil)
                }
                .font(Typography.body)
                .accessibilityIdentifier("settings-check-for-updates-button")
            } header: {
                Text("About")
                    .waiSectionHeader()
                    .accessibilityIdentifier("settings-about-header")
            }

            Section {
                Button("Sign Out") {
                    showSignOutConfirmation = true
                }
                .font(Typography.body)
                .foregroundStyle(Palette.textSecondary)
                .accessibilityIdentifier("settings-sign-out-button")
            }

            // Required by App Store guideline 5.1.1(v): apps that support
            // account creation must also offer in-app account deletion.
            Section {
                HStack {
                    Button("Delete Account…") {
                        showDeleteAccountConfirmation = true
                    }
                    .font(Typography.body)
                    .foregroundStyle(.red)
                    .disabled(isDeletingAccount)
                    .accessibilityIdentifier("settings-delete-account-button")

                    if isDeletingAccount {
                        ProgressView()
                            .controlSize(.small)
                    }
                }
                Text("Permanently erases your account, recordings, transcripts, and summaries from WaiSay. This cannot be undone.")
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textSecondary)
            } header: {
                Text("Danger zone")
                    .waiSectionHeader()
                    .accessibilityIdentifier("settings-danger-zone-header")
            }
        }
        .formStyle(.grouped)
        .task {
            await loadSummarySettings()
        }
        .onAppear(perform: refreshPermissions)
        .onDisappear(perform: stopPermissionPolling)
        .onChange(of: scenePhase) { _, newPhase in
            if newPhase == .active {
                refreshPermissions()
            }
        }
        .confirmationDialog("Sign out and reset WaiSay on this Mac?", isPresented: $showSignOutConfirmation) {
            Button("Sign Out and Reset", role: .destructive) {
                Task {
                    await appState.logout()
                }
            }
            .accessibilityIdentifier("settings-sign-out-confirm-button")
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Clears your session, preferences, dictation history, and onboarding state on this device. Server-side recordings and summaries stay intact. WaiSay will restart so the next launch is a clean install.")
        }
        .alert("Delete account?", isPresented: $showDeleteAccountConfirmation) {
            Button("Cancel", role: .cancel) {}
            Button("Delete", role: .destructive) {
                Task {
                    isDeletingAccount = true
                    deleteAccountError = await appState.deleteAccount()
                    isDeletingAccount = false
                }
            }
        } message: {
            Text("This will permanently erase your account, recordings, transcripts, and summaries. WaiSay will restart afterwards. This action cannot be undone.")
        }
        .alert(
            "Couldn't delete account",
            isPresented: Binding(
                get: { deleteAccountError != nil },
                set: { if !$0 { deleteAccountError = nil } }
            )
        ) {
            Button("OK", role: .cancel) { deleteAccountError = nil }
        } message: {
            Text(deleteAccountError ?? "")
        }
    }

    private var dictationUsageText: String {
        if !dictationManager.isFeatureEnabled {
            return "Enable Dictation to use a global hold-to-talk hotkey."
        }
        if accessibilityStatus == .staleNeedsRestart {
            return "Restart WaiSay so macOS applies Accessibility to this running app."
        }
        if !hasMicrophonePermission {
            return "Grant Microphone permission to capture your voice."
        }
        if accessibilityStatus != .granted {
            return "Grant Accessibility for the global hotkey and automatic paste."
        }
        return "Hold \(dictationManager.selectedHotkey.shortLabel) to dictate (release to paste). Double-tap to start hands-free; double-tap again to stop."
    }

    private var dictationPrivacyText: String {
        if dictationPostFilterEnabled {
            return "Post-filtering sends dictated text through the selected cleanup model before insertion."
        }
        return "Post-filtering is off; dictated text is inserted after dictionary replacements."
    }

    private var dictationPermissionsReady: Bool {
        hasMicrophonePermission && accessibilityStatus == .granted
    }

    private static var hasMicrophonePermission: Bool {
        #if DEBUG
        if let snapshot = MacPermissionTesting.dictationPermissionSnapshot {
            return snapshot.hasMicrophonePermission
        }
        #endif
        return AVCaptureDevice.authorizationStatus(for: .audio) == .authorized
    }

    @ViewBuilder
    private func permissionRow(
        title: String,
        status: MacInputPermission.Status,
        identifierBase: String,
        grantAction: @escaping () -> Void,
        settingsAction: (() -> Void)?,
        restartAction: (() -> Void)?
    ) -> some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            HStack {
                Text(title)
                    .font(Typography.body)
                Spacer()

                switch status {
                case .granted:
                    Label("Granted", systemImage: "checkmark.circle.fill")
                        .font(Typography.bodySmall)
                        .foregroundStyle(.green)
                case .denied:
                    Button("Grant") {
                        grantAction()
                    }
                    .font(Typography.bodySmall)
                    .accessibilityIdentifier("\(identifierBase)-grant")

                    if let settingsAction {
                        Button("Settings") {
                            settingsAction()
                        }
                        .font(Typography.bodySmall)
                        .accessibilityIdentifier("\(identifierBase)-settings")
                    }
                case .staleNeedsRestart:
                    Label("Restart Required", systemImage: "arrow.clockwise.circle.fill")
                        .font(Typography.bodySmall)
                        .foregroundStyle(Palette.accent)
                        .accessibilityIdentifier("\(identifierBase)-restart-required")
                }
            }

            if status == .staleNeedsRestart {
                Text(MacPrivacySettings.permissionRestartHint + " " + MacPrivacySettings.duplicatePermissionHint)
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)

                HStack(spacing: Spacing.sm) {
                    if let settingsAction {
                        Button("Settings") {
                            settingsAction()
                        }
                        .font(Typography.bodySmall)
                        .accessibilityIdentifier("\(identifierBase)-settings")
                    }

                    if let restartAction {
                        Button("Restart WaiSay") {
                            restartAction()
                        }
                        .font(Typography.bodySmall)
                        .accessibilityIdentifier("\(identifierBase)-restart")
                    }
                }
            }
        }
    }

    @ViewBuilder
    private func transcriptionModelPicker(
        _ title: String,
        selection: Binding<String>,
        options: [TranscriptionModelOption],
        identifier: String,
        save: @escaping (String) async -> Void
    ) -> some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            Picker(title, selection: selection) {
                ForEach(options) { option in
                    Text(option.label).tag(option.id)
                }
            }
            .font(Typography.body)
            .disabled(options.isEmpty)
            .accessibilityIdentifier(identifier)
            .onChange(of: selection.wrappedValue) { _, newValue in
                guard settingsLoaded else { return }
                Task { await save(newValue) }
            }

            if let description = selectedOptionDescription(selection.wrappedValue, in: options) {
                Text(description)
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private func selectedOptionDescription(_ selection: String, in options: [TranscriptionModelOption]) -> String? {
        options.first { $0.id == selection }?.description
    }

    private func splitSelection(_ selection: String) -> (provider: String, model: String)? {
        let parts = selection.split(separator: ":", maxSplits: 1, omittingEmptySubsequences: false)
        guard parts.count == 2, !parts[0].isEmpty, !parts[1].isEmpty else { return nil }
        return (String(parts[0]), String(parts[1]))
    }

    private func applySettings(_ settings: UserSettings) {
        summaryLanguage = settings.summaryLanguage
        summaryStyle = settings.summaryStyle
        summaryInstructions = settings.summaryInstructions ?? ""
        dictationLiveSTTSelection = "\(settings.dictationLiveSTTProvider):\(settings.dictationLiveSTTModel)"
        recordingLiveSTTSelection = "\(settings.recordingLiveSTTProvider):\(settings.recordingLiveSTTModel)"
        fileSTTSelection = "\(settings.fileSTTProvider):\(settings.fileSTTModel)"
        dictationPostFilterEnabled = settings.dictationPostFilterEnabled
        dictationPostFilterSelection = "\(settings.dictationPostFilterProvider):\(settings.dictationPostFilterModel)"
    }

    private func refreshPermissions() {
        #if DEBUG
        if let snapshot = MacPermissionTesting.dictationPermissionSnapshot {
            hasMicrophonePermission = snapshot.hasMicrophonePermission
            accessibilityStatus = snapshot.accessibilityStatus
            return
        }
        #endif

        hasMicrophonePermission = Self.hasMicrophonePermission
        accessibilityStatus = MacInputPermission.accessibilityStatus()
        dictationManager.refreshPermissionState()
        if dictationPermissionsReady {
            stopPermissionPolling()
        }
    }

    private func requestMicrophonePermission() {
        startPermissionPolling()
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized:
            refreshPermissions()
        case .notDetermined:
            Task {
                _ = await AVAudioApplication.requestRecordPermission()
                await MainActor.run {
                    refreshPermissions()
                    if !hasMicrophonePermission {
                        MacPrivacySettings.openMicrophone()
                    }
                }
            }
        case .denied, .restricted:
            MacPrivacySettings.openMicrophone()
            refreshPermissions()
        @unknown default:
            MacPrivacySettings.openMicrophone()
            refreshPermissions()
        }
    }

    /// Unified Accessibility grant flow. Triggers the canonical
    /// `AXIsProcessTrustedWithOptions(prompt: true)` system dialog and also
    /// opens Settings + reveals the app in Finder so the user can drag onto
    /// the "+" if Settings shows an empty Accessibility list.
    private func openAccessibilitySettings() {
        startPermissionPolling()
        #if DEBUG
        if MacPermissionTesting.forcesMissingDictationPermissions {
            return
        }
        #endif
        _ = GlobalHotkeyManager.requestAccessibilityPermission()
        MacInputPermission.revealAppInFinder()
        MacPrivacySettings.openAccessibility()
    }

    private func startPermissionPolling() {
        stopPermissionPolling()
        permissionPollTimer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { _ in
            DispatchQueue.main.async {
                refreshPermissions()
            }
        }
    }

    private func stopPermissionPolling() {
        permissionPollTimer?.invalidate()
        permissionPollTimer = nil
    }

    private func loadSummarySettings() async {
        guard !settingsLoaded else { return }
        do {
            async let settingsRequest = appState.getAPIClient().getSettings()
            async let optionsRequest = appState.getAPIClient().getTranscriptionOptions()
            let (settings, options) = try await (settingsRequest, optionsRequest)
            applySettings(settings)
            transcriptionOptions = options
            settingsError = nil
            settingsLoaded = true
        } catch {
            settingsError = "Couldn't load account settings: \(error.localizedDescription)"
        }
    }

    private func saveDictationLiveSTT(selection: String) async {
        guard let pair = splitSelection(selection) else { return }
        let request = UpdateSettingsRequest(
            dictationLiveSTTProvider: pair.provider,
            dictationLiveSTTModel: pair.model
        )
        await saveTranscriptionSettings(request)
    }

    private func saveRecordingLiveSTT(selection: String) async {
        guard let pair = splitSelection(selection) else { return }
        let request = UpdateSettingsRequest(
            recordingLiveSTTProvider: pair.provider,
            recordingLiveSTTModel: pair.model
        )
        await saveTranscriptionSettings(request)
    }

    private func saveFileSTT(selection: String) async {
        guard let pair = splitSelection(selection) else { return }
        let request = UpdateSettingsRequest(
            fileSTTProvider: pair.provider,
            fileSTTModel: pair.model
        )
        await saveTranscriptionSettings(request)
    }

    private func saveDictationPostFilterEnabled(_ enabled: Bool) async {
        let request = UpdateSettingsRequest(dictationPostFilterEnabled: enabled)
        await saveTranscriptionSettings(request)
    }

    private func saveDictationPostFilter(selection: String) async {
        guard let pair = splitSelection(selection) else { return }
        let request = UpdateSettingsRequest(
            dictationPostFilterProvider: pair.provider,
            dictationPostFilterModel: pair.model
        )
        await saveTranscriptionSettings(request)
    }

    private func saveTranscriptionSettings(_ request: UpdateSettingsRequest) async {
        do {
            let settings = try await appState.getAPIClient().updateSettings(request)
            applySettings(settings)
            settingsError = nil
        } catch {
            settingsError = "Couldn't save account settings: \(error.localizedDescription)"
        }
    }

    private func saveSummarySettings(
        language: String? = nil,
        style: String? = nil,
        instructions: String? = nil
    ) async {
        let request = UpdateSettingsRequest(
            summaryLanguage: language,
            summaryStyle: style,
            summaryInstructions: instructions
        )
        _ = try? await appState.getAPIClient().updateSettings(request)
    }
}
