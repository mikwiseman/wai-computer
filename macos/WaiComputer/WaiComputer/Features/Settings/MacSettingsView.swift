import AppKit
import AVFoundation
import SwiftUI
import WaiComputerKit

private enum McpClient: String, CaseIterable, Identifiable {
    case claudeAI = "Claude.ai"
    case cursor = "Cursor"
    case chatGPT = "ChatGPT"
    case claudeCode = "Claude Code"
    case codex = "Codex CLI"

    var id: String { rawValue }
}

private struct McpClientGuide {
    let steps: String
    let snippet: String?
    let externalLink: (label: String, url: URL)?
}

private let mcpEndpointURL = "https://wai.computer/mcp"

private let mcpClientGuides: [McpClient: McpClientGuide] = [
    .claudeAI: McpClientGuide(
        steps: "Open Customize → Connectors and click the “+” button, paste the URL, then approve the request on wai.computer when prompted.",
        snippet: nil,
        externalLink: (
            label: "Open Connectors in Claude.ai",
            url: URL(string: "https://claude.ai/customize/connectors")!
        )
    ),
    .cursor: McpClientGuide(
        steps: "Add this server to .cursor/mcp.json in your project root (or to your global Cursor MCP settings). Cursor starts the OAuth flow on first use.",
        snippet: """
        {
          "mcpServers": {
            "waicomputer": {
              "url": "\(mcpEndpointURL)"
            }
          }
        }
        """,
        externalLink: nil
    ),
    .chatGPT: McpClientGuide(
        steps: "Open ChatGPT → Settings → Connectors. Enable Developer Mode, add an MCP server, and paste the URL.",
        snippet: nil,
        externalLink: nil
    ),
    .claudeCode: McpClientGuide(
        steps: "Either run the CLI add command, or drop the snippet into a .mcp.json at your project root.",
        snippet: """
        # CLI
        claude mcp add waicomputer \(mcpEndpointURL)

        # Or .mcp.json:
        {
          "mcpServers": {
            "waicomputer": {
              "type": "http",
              "url": "\(mcpEndpointURL)"
            }
          }
        }
        """,
        externalLink: nil
    ),
    .codex: McpClientGuide(
        steps: "Add the server, then complete the OAuth login from the browser when prompted.",
        snippet: """
        codex mcp add waicomputer --url \(mcpEndpointURL)
        codex mcp login waicomputer
        """,
        externalLink: nil
    ),
]

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
    @State private var mcpClient: McpClient = .claudeAI
    @State private var mcpCopiedField: String?
    @State private var settingsLoaded = false
    @State private var settingsError: String?
    @State private var transcriptionOptions: TranscriptionOptions?
    @State private var dictationLiveSTTSelection = ""
    @State private var recordingLiveSTTSelection = ""
    @State private var fileSTTSelection = ""
    @State private var dictationPostFilterEnabled = true
    @State private var dictationPostFilterSelection = ""
    @AppStorage(PaymentModeStore.userDefaultsKey) private var paymentModeEnabled = false

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
                    LabeledContent {
                        Text(user.email)
                    } label: {
                        Text("settings.account.email", bundle: .main)
                    }
                    .font(Typography.body)
                    LabeledContent {
                        Text(user.createdAt.formatted(date: .long, time: .omitted))
                    } label: {
                        Text("settings.account.memberSince", bundle: .main)
                    }
                    .font(Typography.body)
                }
            } header: {
                Text("settings.account.title", bundle: .main)
                    .waiSectionHeader()
                    .accessibilityIdentifier("settings-account-header")
            }

            Section {
                PaymentModeToggle()
            } header: {
                Text("settings.payments.title", bundle: .main)
                    .waiSectionHeader()
                    .accessibilityIdentifier("settings-payment-mode-header")
            }

            if paymentModeEnabled {
                BillingSection()
            }

            Section {
                AppLanguagePicker()
            } header: {
                Text("settings.language.title", bundle: .main)
                    .waiSectionHeader()
                    .accessibilityIdentifier("settings-app-language-header")
            }

            Section {
                LanguagePickerView(store: languageStore)
                    .padding(.vertical, 4)
            } header: {
                Text("settings.dictationLanguages.title", bundle: .main)
                    .waiSectionHeader()
                    .accessibilityIdentifier("settings-transcription-header")
            } footer: {
                Text("settings.dictationLanguages.footer", bundle: .main)
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textTertiary)
            }

            Section {
                if let transcriptionOptions {
                    transcriptionModelPicker(
                        String(localized: "settings.transcription.dictationLive", bundle: .main),
                        selection: $dictationLiveSTTSelection,
                        options: transcriptionOptions.dictationLiveSTT,
                        identifier: "settings-dictation-live-stt-picker",
                        save: { await saveDictationLiveSTT(selection: $0) }
                    )

                    transcriptionModelPicker(
                        String(localized: "settings.transcription.recordingLive", bundle: .main),
                        selection: $recordingLiveSTTSelection,
                        options: transcriptionOptions.recordingLiveSTT,
                        identifier: "settings-recording-live-stt-picker",
                        save: { await saveRecordingLiveSTT(selection: $0) }
                    )

                    transcriptionModelPicker(
                        String(localized: "settings.transcription.fullSession", bundle: .main),
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
                Text("settings.transcription.title", bundle: .main)
                    .waiSectionHeader()
                    .accessibilityIdentifier("settings-transcription-models-header")
            }

            Section {
                Toggle(isOn: $showDockIconWhenMainWindowClosed) {
                    Text("settings.appBehavior.showDockIcon", bundle: .main)
                }
                    .font(Typography.body)
                    .accessibilityIdentifier("settings-show-dock-icon-when-closed-toggle")
                    .onChange(of: showDockIconWhenMainWindowClosed) { _, _ in
                        MacPresentationCoordinator.shared.updateActivationPolicyForCurrentWindowState()
                    }

                Text("settings.appBehavior.dockHint", bundle: .main)
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textTertiary)
            } header: {
                Text("settings.appBehavior.title", bundle: .main)
                    .waiSectionHeader()
                    .accessibilityIdentifier("settings-app-behavior-header")
            }

            // MARK: - Summary Settings

            Section {
                Picker(selection: $summaryLanguage) {
                    ForEach(summaryLanguageOptions, id: \.value) { option in
                        Text(option.label).tag(option.value)
                    }
                } label: {
                    Text("settings.summary.language", bundle: .main)
                }
                .font(Typography.body)
                .onChange(of: summaryLanguage) { _, newValue in
                    Task { await saveSummarySettings(language: newValue) }
                }

                Picker(selection: $summaryStyle) {
                    ForEach(summaryStyleOptions, id: \.value) { option in
                        Text(option.label).tag(option.value)
                    }
                } label: {
                    Text("settings.summary.detailLevel", bundle: .main)
                }
                .font(Typography.body)
                .onChange(of: summaryStyle) { _, newValue in
                    Task { await saveSummarySettings(style: newValue) }
                }

                VStack(alignment: .leading, spacing: Spacing.xs) {
                    Text("settings.summary.customInstructions", bundle: .main)
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
                    Text("settings.summary.customExample", bundle: .main)
                        .font(Typography.caption)
                        .foregroundStyle(Palette.textTertiary)
                }
            } header: {
                Text("settings.summary.title", bundle: .main)
                    .waiSectionHeader()
                    .accessibilityIdentifier("settings-summary-header")
            }

            // MARK: - Dictation Settings

            Section {
                Toggle(isOn: $dictationManager.isFeatureEnabled) {
                    Text("settings.dictation.enable", bundle: .main)
                }
                    .font(Typography.body)
                    .onChange(of: dictationManager.isFeatureEnabled) { _, enabled in
                        refreshPermissions()
                        if enabled, !dictationPermissionsReady {
                            startPermissionPolling()
                        }
                    }

                Picker(selection: Binding(
                    get: { dictationManager.selectedHotkey },
                    set: { dictationManager.updateHotkey($0) }
                )) {
                    ForEach(DictationHotkey.allCases) { hotkey in
                        Text(hotkey.label).tag(hotkey)
                    }
                } label: {
                    Text("settings.dictation.pushToTalk", bundle: .main)
                }
                .font(Typography.body)
                .disabled(!dictationManager.isFeatureEnabled)
                .accessibilityIdentifier("settings-push-to-talk-picker")

                Picker(selection: Binding<DictationHotkey?>(
                    get: { dictationManager.selectedHandsFreeHotkey },
                    set: { dictationManager.updateHandsFreeHotkey($0) }
                )) {
                    Text("settings.dictation.handsFreeDoubleTap", bundle: .main).tag(DictationHotkey?.none)
                    ForEach(DictationHotkey.allCases) { hotkey in
                        Text(hotkey.label).tag(DictationHotkey?.some(hotkey))
                    }
                } label: {
                    Text("settings.dictation.handsFree", bundle: .main)
                }
                .font(Typography.body)
                .disabled(!dictationManager.isFeatureEnabled)
                .accessibilityIdentifier("settings-hands-free-picker")

                Toggle(isOn: $dictationPostFilterEnabled) {
                    Text("settings.dictation.postFilter", bundle: .main)
                }
                    .font(Typography.body)
                    .disabled(!dictationManager.isFeatureEnabled)
                    .accessibilityIdentifier("settings-dictation-post-filter-toggle")
                    .onChange(of: dictationPostFilterEnabled) { _, enabled in
                        guard settingsLoaded else { return }
                        Task { await saveDictationPostFilterEnabled(enabled) }
                    }

                if let transcriptionOptions, dictationPostFilterEnabled {
                    transcriptionModelPicker(
                        String(localized: "settings.transcription.postFilterModel", bundle: .main),
                        selection: $dictationPostFilterSelection,
                        options: transcriptionOptions.dictationPostFilter,
                        identifier: "settings-dictation-post-filter-model-picker",
                        save: { await saveDictationPostFilter(selection: $0) }
                    )
                    .disabled(!dictationManager.isFeatureEnabled)
                }

                permissionRow(
                    title: String(localized: "settings.dictation.permission.microphone", bundle: .main),
                    status: hasMicrophonePermission ? .granted : .denied,
                    identifierBase: "settings-permission-microphone",
                    grantAction: requestMicrophonePermission,
                    settingsAction: nil,
                    restartAction: nil
                )

                permissionRow(
                    title: String(localized: "settings.dictation.permission.accessibility", bundle: .main),
                    status: accessibilityStatus,
                    identifierBase: "settings-permission-accessibility",
                    grantAction: openAccessibilitySettings,
                    settingsAction: { MacPrivacySettings.openAccessibility() },
                    restartAction: MacPrivacySettings.restartForPermissionRefresh
                )

                // Usage hint
                VStack(alignment: .leading, spacing: Spacing.xs) {
                    Text("settings.dictation.howToUse", bundle: .main)
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
                    Button {
                        UserDefaults.standard.set(false, forKey: MacAppState.onboardingCompletedKey)
                        UserDefaults.standard.removeObject(forKey: MacAppState.onboardingCurrentPageKey)
                        appState.hasCompletedOnboarding = false
                    } label: {
                        Text("settings.dictation.rerunSetup", bundle: .main)
                    }
                    .font(Typography.bodySmall)
                    .accessibilityIdentifier("settings-rerun-setup-button")

                    Button {
                        MacInputPermission.revealAppInFinder()
                    } label: {
                        Text("settings.dictation.revealInFinder", bundle: .main)
                    }
                    .font(Typography.bodySmall)
                    .accessibilityIdentifier("settings-reveal-app-button")

                    Button {
                        MacInputPermission.resetTCCEntries()
                        MacPrivacySettings.restartForPermissionRefresh()
                    } label: {
                        Text("settings.dictation.resetPermissions", bundle: .main)
                    }
                    .font(Typography.bodySmall)
                    .accessibilityIdentifier("settings-reset-permissions-button")
                }
            } header: {
                Text("settings.dictation.title", bundle: .main)
                    .waiSectionHeader()
            }

            mcpConnectSection

            Section {
                LabeledContent {
                    let version = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0.0"
                    let build = Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "1"
                    Text("\(version) (\(build))")
                        .font(Typography.mono)
                } label: {
                    Text("settings.about.version", bundle: .main)
                }
                #if !DEBUG
                Toggle(isOn: $receiveBetaUpdates) {
                    Text("settings.about.receiveBeta", bundle: .main)
                }
                    .font(Typography.body)
                    .accessibilityIdentifier("settings-receive-beta-updates-toggle")
                Text("settings.about.betaHint", bundle: .main)
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textTertiary)
                Button {
                    NotificationCenter.default.post(name: .waicomputerCheckForUpdates, object: nil)
                } label: {
                    Text("settings.about.checkUpdates", bundle: .main)
                }
                .font(Typography.body)
                .accessibilityIdentifier("settings-check-for-updates-button")
                #endif
            } header: {
                Text("settings.about.title", bundle: .main)
                    .waiSectionHeader()
                    .accessibilityIdentifier("settings-about-header")
            }

            Section {
                Button {
                    showSignOutConfirmation = true
                } label: {
                    Text("settings.signOut", bundle: .main)
                }
                .font(Typography.body)
                .foregroundStyle(Palette.textSecondary)
                .accessibilityIdentifier("settings-sign-out-button")
            }

            // Required by App Store guideline 5.1.1(v): apps that support
            // account creation must also offer in-app account deletion.
            Section {
                HStack {
                    Button {
                        showDeleteAccountConfirmation = true
                    } label: {
                        Text("settings.dangerZone.deleteAccount", bundle: .main)
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
                Text("settings.dangerZone.deleteHint", bundle: .main)
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textSecondary)
            } header: {
                Text("settings.dangerZone.title", bundle: .main)
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
        .confirmationDialog(
            Text("settings.signOutConfirm.title", bundle: .main),
            isPresented: $showSignOutConfirmation
        ) {
            Button(role: .destructive) {
                Task {
                    await appState.logout()
                }
            } label: {
                Text("settings.signOutConfirm.confirm", bundle: .main)
            }
            .accessibilityIdentifier("settings-sign-out-confirm-button")
            Button(role: .cancel) { } label: {
                Text("settings.cancel", bundle: .main)
            }
        } message: {
            Text("settings.signOutConfirm.body", bundle: .main)
        }
        .alert(
            Text("settings.deleteAccount.confirmTitle", bundle: .main),
            isPresented: $showDeleteAccountConfirmation
        ) {
            Button(role: .cancel) { } label: {
                Text("settings.cancel", bundle: .main)
            }
            Button(role: .destructive) {
                Task {
                    isDeletingAccount = true
                    deleteAccountError = await appState.deleteAccount()
                    isDeletingAccount = false
                }
            } label: {
                Text("settings.delete", bundle: .main)
            }
        } message: {
            Text("settings.deleteAccount.confirmBody", bundle: .main)
        }
        .alert(
            Text("settings.deleteAccount.errorTitle", bundle: .main),
            isPresented: Binding(
                get: { deleteAccountError != nil },
                set: { if !$0 { deleteAccountError = nil } }
            )
        ) {
            Button(role: .cancel) { deleteAccountError = nil } label: {
                Text("settings.ok", bundle: .main)
            }
        } message: {
            Text(deleteAccountError ?? "")
        }
    }

    @ViewBuilder
    private var mcpConnectSection: some View {
        Section {
            HStack {
                Text(mcpEndpointURL)
                    .font(Typography.mono)
                    .textSelection(.enabled)
                    .lineLimit(1)
                    .truncationMode(.middle)
                Spacer()
                Button {
                    copyMcpValue(mcpEndpointURL, field: "endpoint")
                } label: {
                    Text(
                        mcpCopiedField == "endpoint" ? "settings.mcp.copied" : "settings.mcp.copy",
                        bundle: .main
                    )
                }
                .font(Typography.body)
                .accessibilityIdentifier("settings-mcp-copy-endpoint")
            }

            Text("settings.mcp.hint", bundle: .main)
                .font(Typography.caption)
                .foregroundStyle(Palette.textTertiary)

            Picker(selection: $mcpClient) {
                ForEach(McpClient.allCases) { client in
                    Text(client.rawValue).tag(client)
                }
            } label: {
                Text("settings.mcp.client", bundle: .main)
            }
            .pickerStyle(.segmented)
            .accessibilityIdentifier("settings-mcp-client-picker")

            if let guide = mcpClientGuides[mcpClient] {
                Text(guide.steps)
                    .font(Typography.body)
                    .fixedSize(horizontal: false, vertical: true)

                if let snippet = guide.snippet {
                    VStack(alignment: .leading, spacing: 6) {
                        ScrollView(.horizontal, showsIndicators: false) {
                            Text(snippet)
                                .font(Typography.mono)
                                .textSelection(.enabled)
                                .padding(.vertical, 2)
                        }
                        Button {
                            copyMcpValue(snippet, field: "snippet")
                        } label: {
                            Text(
                                mcpCopiedField == "snippet" ? "settings.mcp.copied" : "settings.mcp.copySnippet",
                                bundle: .main
                            )
                        }
                        .font(Typography.body)
                        .accessibilityIdentifier("settings-mcp-copy-snippet")
                    }
                }

                if let link = guide.externalLink {
                    Link(link.label, destination: link.url)
                        .font(Typography.body)
                }
            }
        } header: {
            Text("settings.mcp.title", bundle: .main)
                .waiSectionHeader()
                .accessibilityIdentifier("settings-mcp-header")
        }
    }

    private func copyMcpValue(_ value: String, field: String) {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(value, forType: .string)
        mcpCopiedField = field
        Task {
            try? await Task.sleep(for: .seconds(1.5))
            if mcpCopiedField == field {
                mcpCopiedField = nil
            }
        }
    }

    private var dictationUsageText: String {
        if !dictationManager.isFeatureEnabled {
            return "Enable Dictation to use a global hold-to-talk hotkey."
        }
        if accessibilityStatus == .staleNeedsRestart {
            return "Restart WaiComputer so macOS applies Accessibility to this running app."
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
                        Button("Restart WaiComputer") {
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
        transcriptionOptions = nil
        do {
            let settings = try await appState.getAPIClient().getSettings()
            applySettings(settings)
            settingsError = nil
            settingsLoaded = true
        } catch {
            settingsError = "Couldn't load account settings: \(error.localizedDescription)"
            return
        }

        await loadTranscriptionOptions()
    }

    private func loadTranscriptionOptions() async {
        do {
            transcriptionOptions = try await appState.getAPIClient().getTranscriptionOptions()
            settingsError = nil
        } catch {
            settingsError = "Couldn't load transcription model options: \(error.localizedDescription)"
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
