import SwiftUI
import WaiSayKit

struct MacSettingsView: View {
    @EnvironmentObject var appState: MacAppState
    @EnvironmentObject var dictationManager: DictationManager
    @Environment(\.scenePhase) private var scenePhase
    @State private var showSignOutConfirmation = false
    @State private var hasInputMonitoringPermission = GlobalHotkeyManager.hasInputMonitoringPermission
    @State private var permissionPollTimer: Timer?
    @AppStorage("transcriptionLanguage") private var transcriptionLanguage = "multi"
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
                    set: { dictationManager.updateEnabled($0) }
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

                // Input Monitoring permission (for hotkey)
                HStack {
                    Text("Input Monitoring")
                        .font(Typography.body)
                    Spacer()
                    if hasInputMonitoringPermission {
                        Label("Granted", systemImage: "checkmark.circle.fill")
                            .font(Typography.bodySmall)
                            .foregroundStyle(.green)
                    } else {
                        Button("Grant") {
                            GlobalHotkeyManager.requestInputMonitoringPermission()
                            startPermissionPolling()
                        }
                        .font(Typography.bodySmall)
                    }
                }

                // Accessibility permission (for auto-paste)
                HStack {
                    Text("Accessibility")
                        .font(Typography.body)
                    Spacer()
                    if TextInserter.hasAccessibilityPermission {
                        Label("Granted", systemImage: "checkmark.circle.fill")
                            .font(Typography.bodySmall)
                            .foregroundStyle(.green)
                    } else {
                        Button("Add Manually") {
                            TextInserter.requestAccessibilityPermission()
                        }
                        .font(Typography.bodySmall)
                    }
                }

                if !hasInputMonitoringPermission || !TextInserter.hasAccessibilityPermission {
                    VStack(alignment: .leading, spacing: 2) {
                        if !hasInputMonitoringPermission {
                            Text("Input Monitoring: click Grant — system will prompt you.")
                                .font(Typography.caption)
                                .foregroundStyle(Palette.textTertiary)
                        }
                        if !TextInserter.hasAccessibilityPermission {
                            Text("Accessibility: click Add Manually, then click \"+\", select WaiSay from /Applications.")
                                .font(Typography.caption)
                                .foregroundStyle(Palette.textTertiary)
                        }
                    }
                }

                // Usage hint
                VStack(alignment: .leading, spacing: Spacing.xs) {
                    Text("How to use")
                        .font(Typography.label)
                        .foregroundStyle(Palette.textSecondary)
                    Text(dictationUsageText)
                        .font(Typography.caption)
                        .foregroundStyle(Palette.textTertiary)
                    Text("AI Text Cleanup sends dictated text to WaiSay's backend and Anthropic before insertion.")
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
    }

    private var dictationUsageText: String {
        if !dictationManager.isFeatureEnabled {
            return "Enable Dictation to use a global hold-to-talk hotkey."
        }
        return "Hold \(dictationManager.selectedHotkey.shortLabel) to dictate, release to paste. Double-tap to start hands-free, single-tap to stop."
    }

    private func refreshPermissions() {
        hasInputMonitoringPermission = GlobalHotkeyManager.hasInputMonitoringPermission
        if hasInputMonitoringPermission {
            stopPermissionPolling()
        }
    }

    private func startPermissionPolling() {
        stopPermissionPolling()
        permissionPollTimer = Timer.scheduledTimer(withTimeInterval: 2.0, repeats: true) { _ in
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
