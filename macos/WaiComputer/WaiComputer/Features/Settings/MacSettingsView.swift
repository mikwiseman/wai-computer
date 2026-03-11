import SwiftUI
import WaiComputerKit

struct MacSettingsView: View {
    @EnvironmentObject var appState: MacAppState
    @EnvironmentObject var dictationManager: DictationManager
    @Environment(\.scenePhase) private var scenePhase
    @State private var showSignOutConfirmation = false
    @State private var hasAccessibilityPermission = TextInserter.hasAccessibilityPermission
    @AppStorage("transcriptionLanguage") private var transcriptionLanguage = "multi"

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

                // Accessibility permission status
                HStack {
                    Text("Accessibility")
                        .font(Typography.body)
                    Spacer()
                    if hasAccessibilityPermission {
                        Label("Granted", systemImage: "checkmark.circle.fill")
                            .font(Typography.bodySmall)
                            .foregroundStyle(.green)
                    } else {
                        Button("Grant Permission") {
                            TextInserter.requestAccessibilityPermission()
                        }
                        .font(Typography.bodySmall)
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
                    Text("AI Text Cleanup sends dictated text to WaiComputer's backend and Anthropic before insertion.")
                        .font(Typography.caption)
                        .foregroundStyle(Palette.textTertiary)
                }
            } header: {
                Text("Dictation")
                    .waiSectionHeader()
            }

            Section {
                LabeledContent("Version") {
                    Text(Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0.0")
                        .font(Typography.mono)
                }
            } header: {
                Text("About")
                    .waiSectionHeader()
            }

            Section {
                Button("Sign Out") {
                    showSignOutConfirmation = true
                }
                .font(Typography.body)
                .foregroundStyle(Palette.textSecondary)
            }
        }
        .formStyle(.grouped)
        .onAppear(perform: refreshPermissions)
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
        return "Hold \(dictationManager.selectedHotkey.shortLabel) to dictate, release to paste. Double-tap for hands-free mode."
    }

    private func refreshPermissions() {
        hasAccessibilityPermission = TextInserter.hasAccessibilityPermission
    }
}
