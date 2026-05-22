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
    let stepsEnglish: String
    let stepsRussian: String
    let snippet: String?
    let externalLink: (englishLabel: String, russianLabel: String, url: URL)?
}

private let mcpEndpointURL = "https://wai.computer/mcp"

private let mcpClientGuides: [McpClient: McpClientGuide] = [
    .claudeAI: McpClientGuide(
        stepsEnglish: "Open Customize -> Connectors and click the + button, paste the URL, then approve the request on wai.computer when prompted.",
        stepsRussian: "Открой Customize -> Connectors, нажми +, вставь URL и подтверди запрос на wai.computer.",
        snippet: nil,
        externalLink: (
            englishLabel: "Open Connectors in Claude.ai",
            russianLabel: "Открыть Connectors в Claude.ai",
            url: URL(string: "https://claude.ai/customize/connectors")!
        )
    ),
    .cursor: McpClientGuide(
        stepsEnglish: "Add this server to .cursor/mcp.json in your project root or to global Cursor MCP settings. Cursor starts the OAuth flow on first use.",
        stepsRussian: "Добавь этот сервер в .cursor/mcp.json в корне проекта или в глобальные MCP-настройки Cursor. OAuth начнётся при первом использовании.",
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
        stepsEnglish: "Open ChatGPT -> Settings -> Connectors. Enable Developer Mode, add an MCP server, and paste the URL.",
        stepsRussian: "Открой ChatGPT -> Settings -> Connectors. Включи Developer Mode, добавь MCP-сервер и вставь URL.",
        snippet: nil,
        externalLink: nil
    ),
    .claudeCode: McpClientGuide(
        stepsEnglish: "Either run the CLI add command, or drop the snippet into a .mcp.json at your project root.",
        stepsRussian: "Запусти CLI-команду или положи сниппет в .mcp.json в корне проекта.",
        snippet: """
        # CLI
        claude mcp add --transport http waicomputer \(mcpEndpointURL)

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
        stepsEnglish: "Add the server, then complete the OAuth login from the browser when prompted.",
        stepsRussian: "Добавь сервер, затем заверши OAuth-вход в браузере, когда Codex попросит.",
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
    @EnvironmentObject var languageManager: LanguageManager
    @Environment(\.scenePhase) private var scenePhase
    @State private var showSignOutConfirmation = false
    @State private var showDeleteAccountConfirmation = false
    @State private var isDeletingAccount = false
    @State private var deleteAccountError: String?
    @State private var hasMicrophonePermission = MacSettingsView.hasMicrophonePermission
    @State private var accessibilityStatus: MacInputPermission.Status = .denied
    @State private var permissionPollTimer: Timer?
    @AppStorage("transcriptionLanguage") private var transcriptionLanguage = "multi"
    @AppStorage(MacThemePreferences.appearanceKey) private var appearanceModeRawValue = MacThemePreferences.defaultAppearance.rawValue
    @AppStorage(MacThemePreferences.accentKey) private var accentChoiceRawValue = MacThemePreferences.defaultAccent.rawValue
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
    @State private var dictationPostFilterEnabled = false
    @State private var telegramStatus: TelegramLinkStatus?
    @State private var telegramPairing: TelegramPairing?
    @State private var telegramLoading = false
    @State private var telegramError: String?
    @State private var billingRefreshID = 0
    @State private var billingReturnRefreshTask: Task<Void, Never>?
    @AppStorage(PaymentModeStore.userDefaultsKey) private var paymentModeEnabled = false
    @AppStorage(BillingCheckoutRefreshStore.pendingKey) private var billingCheckoutRefreshPending = false

    private static let billingReturnRefreshDelaysNanoseconds: [UInt64] = [
        2_000_000_000,
        3_000_000_000,
        5_000_000_000,
        10_000_000_000,
        20_000_000_000,
        30_000_000_000,
    ]

    private var summaryLanguageOptions: [(label: String, value: String)] {
        [
            (t("Auto (match transcript)", "Авто (как в расшифровке)"), "auto"),
            (t("English", "Английский"), "en"),
            (t("Russian", "Русский"), "ru"),
            (t("Spanish", "Испанский"), "es"),
            (t("German", "Немецкий"), "de"),
            (t("French", "Французский"), "fr"),
            (t("Japanese", "Японский"), "ja"),
            (t("Chinese", "Китайский"), "zh"),
        ]
    }

    private var summaryStyleOptions: [(label: String, value: String)] {
        [
            (t("Brief", "Кратко"), "brief"),
            (t("Medium", "Средне"), "medium"),
            (t("Detailed", "Подробно"), "detailed"),
        ]
    }

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
                        Text(MacDateFormatting.string(
                            from: user.createdAt,
                            dateStyle: .long,
                            timeStyle: .none,
                            language: languageManager.current
                        ))
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

            telegramSection

            #if DEBUG
                Section {
                    PaymentModeToggle()
                } header: {
                    Text("settings.payments.title", bundle: .main)
                        .waiSectionHeader()
                        .accessibilityIdentifier("settings-payment-mode-header")
                }

                BillingSection(mode: paymentModeEnabled ? .fullManagement : .statusOnly)
                    .id(billingRefreshID)
            #else
                BillingSection(mode: .fullManagement)
                    .id(billingRefreshID)
            #endif

            Section {
                AppLanguagePicker()
            } header: {
                Text("settings.language.title", bundle: .main)
                    .waiSectionHeader()
                    .accessibilityIdentifier("settings-app-language-header")
            }

            appearanceSection

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

                if let settingsError {
                    Text(settingsError)
                        .font(Typography.caption)
                        .foregroundStyle(.red)
                        .fixedSize(horizontal: false, vertical: true)
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
                        Text(dictationHotkeyLabel(hotkey)).tag(hotkey)
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
                        Text(dictationHotkeyLabel(hotkey)).tag(DictationHotkey?.some(hotkey))
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
                        UserDefaults.standard.removeObject(forKey: MacAppState.onboardingSystemAudioSetupKey)
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
                updateControls
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
            await loadTelegramStatus()
        }
        .onAppear(perform: refreshPermissions)
        .onDisappear {
            stopPermissionPolling()
            stopBillingReturnRefresh()
        }
        .onChange(of: scenePhase) { _, newPhase in
            if newPhase == .active {
                refreshPermissions()
                Task { await loadTelegramStatus() }
                refreshBillingOnReturnIfNeeded()
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

    private var telegramSection: some View {
        Section {
            if telegramLoading && telegramStatus == nil {
                HStack {
                    ProgressView()
                        .controlSize(.small)
                    Text(t("Loading Telegram status...", "Загружаем статус Telegram..."))
                        .font(Typography.body)
                        .foregroundStyle(Palette.textSecondary)
                }
            } else if telegramStatus?.linked == true {
                LabeledContent {
                    Text(telegramDisplayName)
                        .foregroundStyle(.green)
                } label: {
                    Text("Telegram")
                }
                .font(Typography.body)

                Button(role: .destructive) {
                    Task { await unlinkTelegram() }
                } label: {
                    Text(t("Disconnect Telegram", "Отключить Telegram"))
                }
                .disabled(telegramLoading)
                .accessibilityIdentifier("settings-telegram-unlink-button")
            } else {
                Text(t(
                    "Connect @waicomputer_bot to send voice messages, videos, and text questions to Wai.",
                    "Подключи @waicomputer_bot, чтобы отправлять голосовые, видео и вопросы Wai."
                ))
                .font(Typography.caption)
                .foregroundStyle(Palette.textSecondary)
                .fixedSize(horizontal: false, vertical: true)

                HStack {
                    Button {
                        Task { await startTelegramLink() }
                    } label: {
                        Text(t("Connect Telegram", "Привязать Telegram"))
                    }
                    .disabled(telegramLoading)
                    .accessibilityIdentifier("settings-telegram-link-button")

                    if telegramLoading {
                        ProgressView()
                            .controlSize(.small)
                    }
                }

                if let telegramPairing {
                    VStack(alignment: .leading, spacing: Spacing.xs) {
                        Text(t(
                            "Open this link to finish pairing:",
                            "Открой ссылку, чтобы завершить привязку:"
                        ))
                        .font(Typography.caption)
                        .foregroundStyle(Palette.textSecondary)

                        HStack {
                            Text(telegramPairing.webLink)
                                .font(.system(.caption, design: .monospaced))
                                .lineLimit(1)
                                .truncationMode(.middle)
                                .textSelection(.enabled)

                            Button {
                                openTelegramPairing(telegramPairing)
                            } label: {
                                Text(t("Open", "Открыть"))
                            }
                            .accessibilityIdentifier("settings-telegram-open-link-button")

                            Button {
                                NSPasteboard.general.clearContents()
                                NSPasteboard.general.setString(telegramPairing.webLink, forType: .string)
                            } label: {
                                Text(t("Copy", "Копировать"))
                            }
                        }
                    }
                }
            }

            if let telegramError {
                Text(telegramError)
                    .font(Typography.caption)
                    .foregroundStyle(.red)
                    .fixedSize(horizontal: false, vertical: true)
            }
        } header: {
            Text("Telegram")
                .waiSectionHeader()
                .accessibilityIdentifier("settings-telegram-header")
        } footer: {
            Text(t(
                "Media sent to the bot is transcribed, summarized, and saved to your Library. Text messages are handled as Wai questions.",
                "Медиа из бота расшифровываются, суммаризируются и сохраняются в Библиотеку. Текстовые сообщения обрабатываются как вопросы Wai."
            ))
            .font(Typography.caption)
            .foregroundStyle(Palette.textTertiary)
        }
    }

    private var telegramDisplayName: String {
        guard let status = telegramStatus else { return t("Connected", "Подключено") }
        if let username = status.username, !username.isEmpty {
            return "@\(username)"
        }
        let fullName = [status.firstName, status.lastName]
            .compactMap { $0?.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
            .joined(separator: " ")
        return fullName.isEmpty ? t("Connected", "Подключено") : fullName
    }

    @ViewBuilder
    private var updateControls: some View {
        #if DEBUG
        if ProcessInfo.processInfo.environment["WAI_ENABLE_UI_TEST_MODE"] == "1" {
            updateControlsContent
        }
        #else
        updateControlsContent
        #endif
    }

    @ViewBuilder
    private var updateControlsContent: some View {
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
    }

    @ViewBuilder
    private var appearanceSection: some View {
        Section {
            Picker(selection: appearanceModeBinding) {
                ForEach(MacAppearanceMode.allCases) { mode in
                    Text(appearanceTitle(mode)).tag(mode.rawValue)
                }
            } label: {
                Text(t("Theme", "Тема"))
            }
            .pickerStyle(.segmented)
            .accessibilityIdentifier("settings-appearance-mode-picker")

            VStack(alignment: .leading, spacing: Spacing.sm) {
                Text(t("Accent color", "Акцентный цвет"))
                    .font(Typography.label)
                    .foregroundStyle(Palette.textSecondary)

                LazyVGrid(
                    columns: [GridItem(.adaptive(minimum: 132), spacing: Spacing.sm)],
                    alignment: .leading,
                    spacing: Spacing.sm
                ) {
                    ForEach(MacAccentChoice.allCases) { choice in
                        accentChoiceButton(choice)
                    }
                }
            }

            themePreview

            Text(t(
                "Uses macOS adaptive system colors so the accent works in Light, Dark, and increased contrast modes.",
                "Использует адаптивные системные цвета macOS, чтобы акцент работал в светлой, тёмной и контрастной темах."
            ))
            .font(Typography.caption)
            .foregroundStyle(Palette.textTertiary)
        } header: {
            Text(t("Appearance", "Внешний вид"))
                .waiSectionHeader()
                .accessibilityIdentifier("settings-appearance-header")
        }
    }

    private var selectedAccentChoice: MacAccentChoice {
        MacAccentChoice(rawValue: accentChoiceRawValue) ?? MacThemePreferences.defaultAccent
    }

    private var appearanceModeBinding: Binding<String> {
        Binding(
            get: { selectedAppearanceMode.rawValue },
            set: { appearanceModeRawValue = $0 }
        )
    }

    private var themePreview: some View {
        HStack(spacing: Spacing.md) {
            RoundedRectangle(cornerRadius: 8)
                .fill(selectedAccentChoice.previewColor)
                .frame(width: 34, height: 34)
                .overlay(
                    Image(systemName: "paintpalette.fill")
                        .foregroundStyle(.white)
                )
                .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: Spacing.xs) {
                Text(t("Preview", "Предпросмотр"))
                    .font(Typography.headingSmall)
                Text("\(appearanceTitle(selectedAppearanceMode)) · \(accentTitle(selectedAccentChoice))")
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textTertiary)
            }

            Spacer()

            Button(t("Primary", "Основная")) {}
                .buttonStyle(.borderedProminent)
                .tint(selectedAccentChoice.previewColor)
                .disabled(true)
                .accessibilityHidden(true)
        }
        .padding(Spacing.md)
        .background(Palette.surfaceSubtle)
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }

    private var selectedAppearanceMode: MacAppearanceMode {
        MacAppearanceMode(rawValue: appearanceModeRawValue) ?? MacThemePreferences.defaultAppearance
    }

    private func accentChoiceButton(_ choice: MacAccentChoice) -> some View {
        let isSelected = selectedAccentChoice == choice
        return Button {
            accentChoiceRawValue = choice.rawValue
        } label: {
            HStack(spacing: Spacing.sm) {
                Circle()
                    .fill(choice.previewColor)
                    .frame(width: 14, height: 14)
                    .overlay(Circle().strokeBorder(Palette.border, lineWidth: 1))
                    .accessibilityHidden(true)

                Text(accentTitle(choice))
                    .font(Typography.bodySmall)
                    .foregroundStyle(Palette.textPrimary)
                    .lineLimit(1)

                Spacer(minLength: Spacing.xs)

                if isSelected {
                    Image(systemName: "checkmark")
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundStyle(selectedAccentChoice.previewColor)
                        .accessibilityHidden(true)
                }
            }
            .padding(.horizontal, Spacing.sm)
            .padding(.vertical, Spacing.sm)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(isSelected ? selectedAccentChoice.previewColor.opacity(0.12) : Palette.surfaceSubtle)
            .clipShape(RoundedRectangle(cornerRadius: 8))
            .overlay(
                RoundedRectangle(cornerRadius: 8)
                    .strokeBorder(isSelected ? selectedAccentChoice.previewColor : Palette.border, lineWidth: isSelected ? 1.5 : 1)
            )
        }
        .buttonStyle(.plain)
        .accessibilityLabel(accentTitle(choice))
        .accessibilityValue(isSelected ? t("Selected", "Выбрано") : t("Not selected", "Не выбрано"))
        .accessibilityIdentifier("settings-accent-\(choice.rawValue)")
    }

    private func appearanceTitle(_ mode: MacAppearanceMode) -> String {
        switch mode {
        case .system:
            return t("System", "Системная")
        case .light:
            return t("Light", "Светлая")
        case .dark:
            return t("Dark", "Тёмная")
        }
    }

    private func accentTitle(_ choice: MacAccentChoice) -> String {
        switch choice {
        case .system:
            return t("System", "Системный")
        case .amber:
            return t("Amber", "Янтарный")
        case .blue:
            return t("Blue", "Синий")
        case .green:
            return t("Green", "Зелёный")
        case .violet:
            return t("Violet", "Фиолетовый")
        case .rose:
            return t("Rose", "Розовый")
        case .graphite:
            return t("Graphite", "Графит")
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
                Text(t(guide.stepsEnglish, guide.stepsRussian))
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
                    Link(t(link.englishLabel, link.russianLabel), destination: link.url)
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
            return t(
                "Enable Dictation to use a global hold-to-talk hotkey.",
                "Включи диктовку, чтобы использовать глобальную клавишу «зажми и говори»."
            )
        }
        if accessibilityStatus == .staleNeedsRestart {
            return t(
                "Restart WaiComputer so macOS applies Accessibility to this running app.",
                "Перезапусти WaiComputer, чтобы macOS применила разрешение Универсального доступа к запущенному приложению."
            )
        }
        if !hasMicrophonePermission {
            return t(
                "Grant Microphone permission to capture your voice.",
                "Дай доступ к микрофону, чтобы записывать голос."
            )
        }
        if accessibilityStatus != .granted {
            return t(
                "Grant Accessibility for the global hotkey and automatic paste.",
                "Дай доступ к Универсальному доступу для глобальной клавиши и автоматической вставки."
            )
        }
        let hotkey = dictationHotkeyShortLabel(dictationManager.selectedHotkey)
        return t(
            "Hold \(hotkey) to dictate. Release to paste. Double-tap to start hands-free; double-tap again to stop.",
            "Зажми \(hotkey), чтобы диктовать. Отпусти, чтобы вставить. Двойное нажатие включает режим без рук, ещё одно двойное нажатие останавливает."
        )
    }

    private var dictationPrivacyText: String {
        if dictationPostFilterEnabled {
            return t(
                "Dictated text is cleaned up before insertion.",
                "Перед вставкой текст проходит очистку."
            )
        }
        return t(
            "Cleanup is off; dictated text is inserted after dictionary replacements.",
            "Очистка выключена; текст вставляется после замен из словаря."
        )
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
                    Label(t("Granted", "Разрешено"), systemImage: "checkmark.circle.fill")
                        .font(Typography.bodySmall)
                        .foregroundStyle(.green)
                case .denied:
                    Button(t("Grant", "Разрешить")) {
                        grantAction()
                    }
                    .font(Typography.bodySmall)
                    .accessibilityIdentifier("\(identifierBase)-grant")

                    if let settingsAction {
                        Button(t("Settings", "Настройки")) {
                            settingsAction()
                        }
                        .font(Typography.bodySmall)
                        .accessibilityIdentifier("\(identifierBase)-settings")
                    }
                case .staleNeedsRestart:
                    Label(t("Restart Required", "Нужен перезапуск"), systemImage: "arrow.clockwise.circle.fill")
                        .font(Typography.bodySmall)
                        .foregroundStyle(Palette.accent)
                        .accessibilityIdentifier("\(identifierBase)-restart-required")
                }
            }

            if status == .staleNeedsRestart {
                Text(DictationSettingsCopy.stalePermissionHint(language: languageManager.current))
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)

                HStack(spacing: Spacing.sm) {
                    if let settingsAction {
                        Button(t("Settings", "Настройки")) {
                            settingsAction()
                        }
                        .font(Typography.bodySmall)
                        .accessibilityIdentifier("\(identifierBase)-settings")
                    }

                    if let restartAction {
                        Button(t("Restart WaiComputer", "Перезапустить WaiComputer")) {
                            restartAction()
                        }
                        .font(Typography.bodySmall)
                        .accessibilityIdentifier("\(identifierBase)-restart")
                    }
                }
            }
        }
    }

    private func applySettings(_ settings: UserSettings) {
        summaryLanguage = settings.summaryLanguage
        summaryStyle = settings.summaryStyle
        summaryInstructions = settings.summaryInstructions ?? ""
        dictationPostFilterEnabled = settings.dictationPostFilterEnabled
        dictationManager.ingestSettings(settings)
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

    private func refreshBillingOnReturnIfNeeded() {
        guard billingCheckoutRefreshPending else { return }
        billingReturnRefreshTask?.cancel()
        billingRefreshID += 1
        billingReturnRefreshTask = Task { @MainActor in
            for delay in Self.billingReturnRefreshDelaysNanoseconds {
                do {
                    try await Task.sleep(nanoseconds: delay)
                } catch {
                    return
                }
                guard billingCheckoutRefreshPending else {
                    billingReturnRefreshTask = nil
                    return
                }
                billingRefreshID += 1
            }
            billingReturnRefreshTask = nil
        }
    }

    private func stopBillingReturnRefresh() {
        billingReturnRefreshTask?.cancel()
        billingReturnRefreshTask = nil
    }

    private func requestMicrophonePermission() {
        startPermissionPolling()
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized:
            refreshPermissions()
        case .notDetermined:
            Task {
                let granted = await AVCaptureDevice.requestAccess(for: .audio)
                await MainActor.run {
                    refreshPermissions()
                    if !granted {
                        MacInputPermission.revealAppInFinder()
                        MacPrivacySettings.openMicrophone()
                    }
                }
            }
        case .denied, .restricted:
            MacInputPermission.revealAppInFinder()
            MacPrivacySettings.openMicrophone()
            refreshPermissions()
        @unknown default:
            MacInputPermission.revealAppInFinder()
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
            let settings = try await appState.getAPIClient().getSettings()
            applySettings(settings)
            settingsError = nil
            settingsLoaded = true
        } catch {
            settingsError = t(
                "Couldn't load account settings: \(error.localizedDescription)",
                "Не удалось загрузить настройки аккаунта: \(error.localizedDescription)"
            )
            return
        }
    }

    private func loadTelegramStatus() async {
        guard !telegramLoading else { return }
        telegramLoading = true
        do {
            telegramStatus = try await appState.getAPIClient().getTelegramLinkStatus()
            telegramError = nil
        } catch {
            telegramError = t(
                "Couldn't load Telegram status: \(error.localizedDescription)",
                "Не удалось загрузить статус Telegram: \(error.localizedDescription)"
            )
        }
        telegramLoading = false
    }

    private func startTelegramLink() async {
        guard !telegramLoading else { return }
        telegramLoading = true
        do {
            telegramPairing = try await appState.getAPIClient().startTelegramLink()
            telegramError = nil
            if let telegramPairing {
                openTelegramPairing(telegramPairing)
            }
        } catch {
            telegramError = t(
                "Couldn't start Telegram pairing: \(error.localizedDescription)",
                "Не удалось начать привязку Telegram: \(error.localizedDescription)"
            )
        }
        telegramLoading = false
    }

    private func unlinkTelegram() async {
        guard !telegramLoading else { return }
        telegramLoading = true
        do {
            try await appState.getAPIClient().unlinkTelegram()
            telegramPairing = nil
            telegramStatus = try await appState.getAPIClient().getTelegramLinkStatus()
            telegramError = nil
        } catch {
            telegramError = t(
                "Couldn't disconnect Telegram: \(error.localizedDescription)",
                "Не удалось отключить Telegram: \(error.localizedDescription)"
            )
        }
        telegramLoading = false
    }

    private func openTelegramPairing(_ pairing: TelegramPairing) {
        if let deepURL = URL(string: pairing.deepLink),
           NSWorkspace.shared.open(deepURL) {
            return
        }
        if let webURL = URL(string: pairing.webLink) {
            NSWorkspace.shared.open(webURL)
        }
    }

    private func saveDictationPostFilterEnabled(_ enabled: Bool) async {
        let request = UpdateSettingsRequest(dictationPostFilterEnabled: enabled)
        await saveTranscriptionSettings(request)
    }

    private func saveTranscriptionSettings(_ request: UpdateSettingsRequest) async {
        do {
            let settings = try await appState.getAPIClient().updateSettings(request)
            applySettings(settings)
            settingsError = nil
        } catch {
            settingsError = t(
                "Couldn't save account settings: \(error.localizedDescription)",
                "Не удалось сохранить настройки аккаунта: \(error.localizedDescription)"
            )
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

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }

    private func dictationHotkeyLabel(_ hotkey: DictationHotkey) -> String {
        DictationSettingsCopy.hotkeyLabel(rawValue: hotkey.rawValue, language: languageManager.current)
    }

    private func dictationHotkeyShortLabel(_ hotkey: DictationHotkey) -> String {
        DictationSettingsCopy.hotkeyShortLabel(rawValue: hotkey.rawValue, language: languageManager.current)
    }
}
