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
    @State private var hasInputMonitoringPermission = GlobalHotkeyManager.hasInputMonitoringPermission
    @State private var hasPastePermission = TextInserter.hasEventPostingPermission
    @State private var inputMonitoringNeedsReview = false
    @State private var pasteNeedsReview = false
    @State private var permissionPollTimer: Timer?
    @AppStorage("transcriptionLanguage") private var transcriptionLanguage = "multi"
    @AppStorage(MacPresentationSettings.showDockIconWhenMainWindowClosedKey) private var showDockIconWhenMainWindowClosed = false
    @State private var summaryLanguage = "auto"
    @State private var summaryStyle = "medium"
    @State private var summaryInstructions = ""
    @State private var settingsLoaded = false

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
                Picker("Language", selection: $transcriptionLanguage) {
                    ForEach(languageOptions, id: \.value) { option in
                        Text(option.label).tag(option.value)
                    }
                }
                .font(Typography.body)
            } header: {
                Text("Transcription")
                    .waiSectionHeader()
                    .accessibilityIdentifier("settings-transcription-header")
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
                Toggle("Enable Dictation", isOn: Binding(
                    get: { dictationManager.isFeatureEnabled },
                    set: { enabled in
                        dictationManager.updateEnabled(enabled)
                        refreshPermissions()
                        if enabled, !dictationPermissionsReady {
                            startPermissionPolling()
                        }
                    }
                ))
                .font(Typography.body)

                Picker("Hotkey", selection: Binding(
                    get: { dictationManager.selectedHotkey },
                    set: { dictationManager.updateHotkey($0) }
                )) {
                    ForEach(DictationHotkey.allCases) { hotkey in
                        Text(hotkey.label).tag(hotkey)
                    }
                }
                .font(Typography.body)
                .disabled(!dictationManager.isFeatureEnabled)

                Toggle("AI Text Cleanup", isOn: $dictationManager.aiCleanupEnabled)
                    .font(Typography.body)
                    .disabled(!dictationManager.isFeatureEnabled)
                    .accessibilityIdentifier("settings-ai-text-cleanup-toggle")

                permissionRow(
                    title: "Microphone",
                    isGranted: hasMicrophonePermission,
                    identifierBase: "settings-permission-microphone",
                    grantAction: requestMicrophonePermission
                )

                permissionRow(
                    title: "Input Monitoring",
                    isGranted: hasInputMonitoringPermission,
                    needsReview: inputMonitoringNeedsReview,
                    identifierBase: "settings-permission-input-monitoring",
                    grantAction: requestInputMonitoringPermission,
                    settingsAction: openInputMonitoringSettings
                )

                #if SPARKLE
                permissionRow(
                    title: "Automatic Paste",
                    isGranted: hasPastePermission,
                    needsReview: pasteNeedsReview,
                    identifierBase: "settings-permission-automatic-paste",
                    grantAction: requestPastePermission,
                    settingsAction: openPasteSettings
                )
                #else
                HStack {
                    Text("Paste Method")
                        .font(Typography.body)
                    Spacer()
                    Label("Clipboard", systemImage: "doc.on.clipboard")
                        .font(Typography.bodySmall)
                        .foregroundStyle(Palette.textSecondary)
                }
                #endif

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
        .confirmationDialog("Are you sure you want to sign out?", isPresented: $showSignOutConfirmation) {
            Button("Sign Out", role: .destructive) {
                Task {
                    await appState.logout()
                }
            }
            Button("Cancel", role: .cancel) {}
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
            Text("This will permanently erase your account, recordings, transcripts, and summaries. This action cannot be undone.")
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
        if !hasMicrophonePermission {
            return "Grant Microphone permission to capture your voice."
        }
        if !hasInputMonitoringPermission {
            return "Grant Input Monitoring to use the hotkey outside WaiSay."
        }
        #if SPARKLE
        if !hasPastePermission {
            return "Grant Automatic Paste to insert text automatically. Dictated text is still copied to the clipboard."
        }
        #endif
        return "Hold \(dictationManager.selectedHotkey.shortLabel) to dictate, release to paste. Double-tap to start hands-free, single-tap to stop."
    }

    private var dictationPrivacyText: String {
        return "AI Text Cleanup sends dictated text to WaiSay's backend and Anthropic before insertion."
    }

    private var dictationPermissionsReady: Bool {
        #if SPARKLE
        hasMicrophonePermission && hasInputMonitoringPermission && hasPastePermission
        #else
        hasMicrophonePermission && hasInputMonitoringPermission
        #endif
    }

    private static var hasMicrophonePermission: Bool {
        #if DEBUG
        if MacPermissionTesting.forcesMissingDictationPermissions {
            return false
        }
        #endif
        return AVCaptureDevice.authorizationStatus(for: .audio) == .authorized
    }

    @ViewBuilder
    private func permissionRow(
        title: String,
        isGranted: Bool,
        needsReview: Bool = false,
        identifierBase: String,
        grantAction: @escaping () -> Void,
        settingsAction: (() -> Void)? = nil
    ) -> some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            HStack {
                Text(title)
                    .font(Typography.body)
                Spacer()
                if isGranted {
                    Label("Granted", systemImage: "checkmark.circle.fill")
                        .font(Typography.bodySmall)
                        .foregroundStyle(.green)
                } else {
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
                }
            }

            if !isGranted && needsReview {
                Text(MacPrivacySettings.duplicatePermissionHint)
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)

                HStack(spacing: Spacing.sm) {
                    Button("Recheck") {
                        refreshPermissions()
                    }
                    .font(Typography.bodySmall)
                    .accessibilityIdentifier("\(identifierBase)-recheck")

                    Button("Quit WaiSay") {
                        MacPrivacySettings.quitForPermissionRefresh()
                    }
                    .font(Typography.bodySmall)
                    .accessibilityIdentifier("\(identifierBase)-quit")
                }
            }
        }
    }

    private func refreshPermissions() {
        #if DEBUG
        if MacPermissionTesting.forcesMissingDictationPermissions {
            hasMicrophonePermission = false
            hasInputMonitoringPermission = false
            hasPastePermission = false
            inputMonitoringNeedsReview = false
            pasteNeedsReview = false
            return
        }
        #endif

        hasMicrophonePermission = Self.hasMicrophonePermission
        hasInputMonitoringPermission = GlobalHotkeyManager.hasInputMonitoringPermission
        hasPastePermission = TextInserter.hasEventPostingPermission
        if hasInputMonitoringPermission {
            inputMonitoringNeedsReview = false
        }
        if hasPastePermission {
            pasteNeedsReview = false
        }
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

    private func requestInputMonitoringPermission() {
        startPermissionPolling()
        inputMonitoringNeedsReview = true
        _ = GlobalHotkeyManager.requestInputMonitoringPermission()
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) {
            refreshPermissions()
            if !hasInputMonitoringPermission {
                MacPrivacySettings.openInputMonitoring()
            }
        }
    }

    private func requestPastePermission() {
        startPermissionPolling()
        pasteNeedsReview = true
        _ = TextInserter.requestEventPostingPermission()
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) {
            refreshPermissions()
            if !hasPastePermission {
                TextInserter.openEventPostingSettings()
            }
        }
    }

    private func openInputMonitoringSettings() {
        startPermissionPolling()
        inputMonitoringNeedsReview = true
        _ = GlobalHotkeyManager.requestInputMonitoringPermission()
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) {
            MacPrivacySettings.openInputMonitoring()
        }
    }

    private func openPasteSettings() {
        startPermissionPolling()
        pasteNeedsReview = true
        _ = TextInserter.requestEventPostingPermission()
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) {
            TextInserter.openEventPostingSettings()
        }
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
            let settings = try await appState.getAPIClient().getSettings()
            summaryLanguage = settings.summaryLanguage
            summaryStyle = settings.summaryStyle
            summaryInstructions = settings.summaryInstructions ?? ""
            settingsLoaded = true
        } catch {
            // Settings will use defaults
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
