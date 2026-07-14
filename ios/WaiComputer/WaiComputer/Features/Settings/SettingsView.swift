import AVFoundation
import SwiftUI
import UIKit
import WaiComputerKit

struct SettingsView: View {
    @EnvironmentObject var appState: AppState
    @EnvironmentObject var languageManager: LanguageManager
    @EnvironmentObject private var dictationLanguageStore: DictationLanguageStore
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass
    @Environment(\.scenePhase) private var scenePhase
    @State private var showingLogoutConfirmation = false
    @State private var showingDeleteAccountConfirmation = false
    @State private var isDeletingAccount = false
    @State private var deleteAccountError: String?
    @State private var micPermission = AVAudioApplication.shared.recordPermission
    @AppStorage(IOSDictationLearningSettings.enabledDefaultsKey) private var dictationLearnFromEditsEnabled = true

    private var isScreenshotMode: Bool {
        IOSTestingMode.current.isScreenshot
    }

    private static let privacyPolicyURL = URL(string: "https://wai.computer/privacy")!
    private static let termsOfServiceURL = URL(string: "https://wai.computer/terms")!

    private var appVersionDisplay: String {
        let version = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String
        let build = Bundle.main.infoDictionary?["CFBundleVersion"] as? String

        switch (version?.isEmpty == false ? version : nil, build?.isEmpty == false ? build : nil) {
        case let (.some(version), .some(build)):
            return "\(version) (\(build))"
        case let (.some(version), nil):
            return version
        case let (nil, .some(build)):
            return build
        case (nil, nil):
            return "Unknown"
        }
    }

    private var updateChannelDescription: String {
        t("App Store or TestFlight", "App Store или TestFlight")
    }

    private var updateManagementDescription: String {
        t(
            "Automatic beta updates are managed in TestFlight. App Store builds follow iOS App Store update settings.",
            "Автообновления beta-сборок управляются в TestFlight. Сборки App Store следуют настройкам обновлений App Store в iOS."
        )
    }

    var body: some View {
        NavigationStack {
            settingsContent
            .navigationTitle(horizontalSizeClass == .regular ? "" : t("Settings", "Настройки"))
            .onChange(of: scenePhase) { _, newPhase in
                // Re-read mic permission when returning from Settings.app.
                if newPhase == .active {
                    micPermission = AVAudioApplication.shared.recordPermission
                }
            }
            .confirmationDialog(t("Log Out", "Выйти"), isPresented: $showingLogoutConfirmation) {
                Button(t("Log Out", "Выйти"), role: .destructive) {
                    Task {
                        await appState.logout()
                    }
                }
                Button(t("Cancel", "Отмена"), role: .cancel) {}
            } message: {
                Text(t("Are you sure you want to log out?", "Точно выйти из аккаунта?"))
            }
            .alert(t("Delete account?", "Удалить аккаунт?"), isPresented: $showingDeleteAccountConfirmation) {
                Button(t("Cancel", "Отмена"), role: .cancel) {}
                Button(t("Delete", "Удалить"), role: .destructive) {
                    Task {
                        isDeletingAccount = true
                        deleteAccountError = await appState.deleteAccount()
                        isDeletingAccount = false
                    }
                }
            } message: {
                Text(t(
                    "This will permanently erase your account, recordings, transcripts, and summaries. This action cannot be undone.",
                    "Это безвозвратно удалит твой аккаунт, записи, расшифровки и резюме. Действие нельзя отменить."
                ))
            }
            .alert(
                t("Couldn't delete account", "Не удалось удалить аккаунт"),
                isPresented: Binding(
                    get: { deleteAccountError != nil },
                    set: { if !$0 { deleteAccountError = nil } }
                )
            ) {
                Button(t("OK", "ОК"), role: .cancel) { deleteAccountError = nil }
            } message: {
                Text(deleteAccountError ?? "")
            }
        }
    }

    @ViewBuilder
    private var settingsContent: some View {
        if horizontalSizeClass == .regular {
            regularSettingsLayout
        } else {
            compactSettingsList
        }
    }

    private var compactSettingsList: some View {
        List {
            settingsListSections
        }
        .accessibilityIdentifier("settings-compact-list")
    }

    @ViewBuilder
    private var settingsListSections: some View {
        Section(t("Account", "Аккаунт")) {
            if let user = appState.currentUser {
                compactAccountHeader(user)
            }
        }

        // Read-only subscription status (plan, usage, renewal, cancel).
        // No in-app upgrade button — iOS billing is read-only. Screenshot
        // mode uses deterministic DEBUG fixtures instead of live billing.
        BillingStatusSection()

        Section(t("Appearance", "Внешний вид")) {
            NavigationLink(destination: AppearanceSettingsView()) {
                Label(t("Appearance", "Внешний вид"), systemImage: "paintpalette")
            }
            AppLanguagePicker()
        }

        Section(t("Recording", "Запись")) {
            NavigationLink(destination: RecordingPipelineView()) {
                Label(t("Recording Pipeline", "Пайплайн записи"), systemImage: "waveform.badge.mic")
            }

            NavigationLink(destination: dictationLanguageScreen) {
                Label(t("Transcription Language", "Язык расшифровки"), systemImage: "text.bubble")
            }

            NavigationLink(destination: SummarySettingsView()) {
                Label(t("AI Summary", "AI-резюме"), systemImage: "sparkles")
            }

            NavigationLink(destination: IdentityAndVoiceSettingsView()) {
                Label(t("Identity & Voice", "Личность и голос"), systemImage: "person.wave.2")
            }
        }

        // Dictation data (history + dictionary). Server-synced; the
        // screens have meaning even before an iOS dictation pipeline.
        Section(t("Dictation", "Диктовка")) {
            NavigationLink(destination: historyScreen) {
                Label(t("History", "История"), systemImage: "clock.arrow.circlepath")
            }
            NavigationLink(destination: dictionaryScreen) {
                Label(t("Dictionary", "Словарь"), systemImage: "book")
            }
            dictationLearningToggle
        }

        Section(t("Permissions", "Разрешения")) {
            microphonePermissionRow
        }

        Section(t("Data", "Данные")) {
            NavigationLink(destination: ServerDataView()) {
                Label(t("Server & Data", "Сервер и данные"), systemImage: "server.rack")
            }

            NavigationLink(destination: ExportReadinessView()) {
                Label(t("Export Readiness", "Готовность экспорта"), systemImage: "shippingbox")
            }
        }

        Section(t("Integrations", "Интеграции")) {
            NavigationLink(destination: TelegramSettingsView()) {
                Label("Telegram", systemImage: "paperplane")
            }

            NavigationLink(destination: McpConnectView()) {
                Label("MCP", systemImage: "link.circle")
            }
        }

        if !isScreenshotMode {
            Section(t("About", "О приложении")) {
                HStack {
                    Text(t("Version", "Версия"))
                    Spacer()
                    Text(appVersionDisplay)
                        .foregroundStyle(.secondary)
                }

                HStack {
                    Text(t("Updates", "Обновления"))
                    Spacer()
                    Text(updateChannelDescription)
                        .foregroundStyle(.secondary)
                }

                Text(updateManagementDescription)
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textTertiary)

                Link(destination: Self.privacyPolicyURL) {
                    Label(t("Privacy Policy", "Политика конфиденциальности"), systemImage: "lock.shield")
                }

                Link(destination: Self.termsOfServiceURL) {
                    Label(t("Terms of Service", "Условия использования"), systemImage: "doc.text")
                }
            }

            Section {
                Button(role: .destructive) {
                    showingLogoutConfirmation = true
                } label: {
                    Label(t("Log Out", "Выйти"), systemImage: "rectangle.portrait.and.arrow.right")
                }
            }

            // Required by App Store guideline 5.1.1(v): apps that support
            // account creation must also offer in-app account deletion.
            Section {
                Button(role: .destructive) {
                    showingDeleteAccountConfirmation = true
                } label: {
                    HStack {
                        Label(t("Delete Account", "Удалить аккаунт"), systemImage: "trash")
                        if isDeletingAccount {
                            Spacer()
                            ProgressView()
                        }
                    }
                }
                .disabled(isDeletingAccount)
                .accessibilityIdentifier("delete-account-button")
            } header: {
                Text(t("Danger zone", "Опасная зона"))
            } footer: {
                Text(t(
                    "Permanently removes your account, recordings, transcripts, and summaries from WaiComputer. This cannot be undone.",
                    "Безвозвратно удаляет твой аккаунт, записи, расшифровки и резюме из WaiComputer. Это нельзя отменить."
                ))
            }
        }
    }

    private func compactAccountHeader(_ user: User) -> some View {
        HStack(alignment: .center, spacing: Spacing.md) {
            WaiTriangleIcon(size: 28)
                .frame(width: 42, height: 42)
                .background(Palette.surfaceSubtle)
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                .overlay {
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .strokeBorder(Palette.border, lineWidth: 1)
                }
                .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: Spacing.xxs) {
                Text(user.email)
                    .font(Typography.headingMedium)
                    .foregroundStyle(Palette.textPrimary)
                    .lineLimit(1)
                    .minimumScaleFactor(0.82)
                    .truncationMode(.middle)

                HStack(spacing: Spacing.xs) {
                    Text(memberSinceText(user.createdAt))
                        .font(Typography.caption)
                        .foregroundStyle(Palette.textSecondary)
                        .lineLimit(1)

                    Text(t("Signed in", "Вход выполнен"))
                        .font(Typography.labelSmall)
                        .foregroundStyle(Palette.accent)
                        .padding(.horizontal, Spacing.sm)
                        .padding(.vertical, Spacing.xxs)
                        .background(Palette.accentSubtle)
                        .clipShape(Capsule())
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.vertical, Spacing.xs)
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("settings-compact-account-header")
    }

    private var regularSettingsLayout: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Spacing.xl) {
                regularSettingsHeader

                LazyVGrid(
                    columns: [GridItem(.adaptive(minimum: 320), spacing: Spacing.lg, alignment: .top)],
                    alignment: .leading,
                    spacing: Spacing.lg
                ) {
                    regularAccountPanel
                    regularPersonalizationPanel
                    regularRecordingPanel
                    regularDictationPanel
                    regularDataPanel
                    regularIntegrationsPanel
                    regularAboutPanel
                }
            }
            .padding(.horizontal, Spacing.xxl)
            .padding(.vertical, Spacing.xxl)
            .frame(maxWidth: 1040, alignment: .topLeading)
            .frame(maxWidth: .infinity, alignment: .top)
        }
        .background(Color(uiColor: .systemGroupedBackground))
        .accessibilityIdentifier("settings-regular-layout")
    }

    private var regularSettingsHeader: some View {
        HStack(alignment: .center, spacing: Spacing.md) {
            WaiTriangleIcon(size: 34)
                .frame(width: 42, height: 42)
                .background(Color(uiColor: .secondarySystemGroupedBackground))
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .strokeBorder(Palette.border, lineWidth: 1)
                )
                .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: Spacing.xs) {
                Text(t("Settings", "Настройки"))
                    .font(Typography.displayMedium)
                    .foregroundStyle(Palette.textPrimary)
                Text(t(
                    "Account, capture, memory, and agent connections.",
                    "Аккаунт, запись, память и подключения агентов."
                ))
                .font(Typography.bodySmall)
                .foregroundStyle(Palette.textSecondary)
            }

            Spacer()

            Text(appVersionDisplay)
                .font(Typography.mono)
                .foregroundStyle(Palette.textTertiary)
        }
        .accessibilityIdentifier("settings-regular-header")
    }

    private var regularAccountPanel: some View {
        regularSettingsPanel(
            title: t("Account", "Аккаунт"),
            subtitle: appState.currentUser.map { memberSinceText($0.createdAt) },
            systemImage: "person.circle",
            identifier: "settings-regular-account-panel"
        ) {
            if let user = appState.currentUser {
                regularValueRow(
                    title: user.email,
                    subtitle: t("Signed in", "Вход выполнен"),
                    systemImage: "person.crop.circle.fill",
                    identifier: "settings-regular-account-user"
                )
            }

            // Read-only subscription status (plan, usage, renewal, cancel).
            // No in-app upgrade button — iOS billing is read-only. Screenshot
            // mode uses deterministic DEBUG fixtures instead of live billing.
            regularDivider
            BillingStatusPanel()

            if !isScreenshotMode {
                regularDivider
                regularLinkRow(
                    title: t("Privacy Policy", "Политика конфиденциальности"),
                    systemImage: "lock.shield",
                    destination: Self.privacyPolicyURL,
                    identifier: "settings-regular-privacy-row"
                )
                regularDivider
                regularLinkRow(
                    title: t("Terms of Service", "Условия использования"),
                    systemImage: "doc.text",
                    destination: Self.termsOfServiceURL,
                    identifier: "settings-regular-terms-row"
                )
                regularDivider
                regularActionRow(
                    title: t("Log Out", "Выйти"),
                    systemImage: "rectangle.portrait.and.arrow.right",
                    role: .destructive,
                    identifier: "settings-regular-logout-row"
                ) {
                    showingLogoutConfirmation = true
                }
                regularDivider
                regularActionRow(
                    title: t("Delete Account", "Удалить аккаунт"),
                    subtitle: t("Permanent deletion.", "Безвозвратное удаление."),
                    systemImage: "trash",
                    role: .destructive,
                    identifier: "delete-account-button"
                ) {
                    showingDeleteAccountConfirmation = true
                }
                .disabled(isDeletingAccount)
            }
        }
    }

    private var regularPersonalizationPanel: some View {
        regularSettingsPanel(
            title: t("Appearance", "Внешний вид"),
            subtitle: t("Theme, accent, and app language.", "Тема, акцент и язык приложения."),
            systemImage: "paintpalette",
            identifier: "settings-regular-appearance-panel"
        ) {
            regularNavigationRow(
                title: t("Appearance", "Внешний вид"),
                subtitle: t("Theme and accent color.", "Тема и акцентный цвет."),
                systemImage: "paintpalette",
                identifier: "settings-regular-appearance-row"
            ) {
                AppearanceSettingsView()
            }

            regularDivider
            AppLanguagePicker()
                .font(Typography.body)
                .accessibilityIdentifier("settings-regular-language-row")
        }
    }

    private var regularRecordingPanel: some View {
        regularSettingsPanel(
            title: t("Recording", "Запись"),
            subtitle: t("Audio, transcription, summaries, and voice identity.", "Аудио, расшифровка, резюме и голос."),
            systemImage: "waveform",
            identifier: "settings-regular-recording-panel"
        ) {
            regularNavigationRow(
                title: t("Recording Pipeline", "Пайплайн записи"),
                subtitle: t("Capture format and server transcription models.", "Формат записи и модели расшифровки."),
                systemImage: "waveform.badge.mic",
                identifier: "settings-regular-recording-pipeline-row"
            ) {
                RecordingPipelineView()
            }
            regularDivider
            regularNavigationRow(
                title: t("Transcription Language", "Язык расшифровки"),
                systemImage: "text.bubble",
                identifier: "settings-regular-transcription-row"
            ) {
                dictationLanguageScreen
            }
            regularDivider
            regularNavigationRow(
                title: t("AI Summary", "AI-резюме"),
                systemImage: "sparkles",
                identifier: "settings-regular-summary-row"
            ) {
                SummarySettingsView()
            }
            regularDivider
            regularNavigationRow(
                title: t("Identity & Voice", "Личность и голос"),
                systemImage: "person.wave.2",
                identifier: "settings-regular-identity-row"
            ) {
                IdentityAndVoiceSettingsView()
            }
            regularDivider
            microphonePermissionRow
                .font(Typography.body)
                .padding(.vertical, Spacing.sm)
                .accessibilityIdentifier("settings-regular-microphone-row")
        }
    }

    private var regularDictationPanel: some View {
        regularSettingsPanel(
            title: t("Dictation", "Диктовка"),
            subtitle: t("Personal history and dictionary terms.", "Личная история и словарь терминов."),
            systemImage: "quote.bubble",
            identifier: "settings-regular-dictation-panel"
        ) {
            regularNavigationRow(
                title: t("History", "История"),
                subtitle: t("Review past dictations.", "Просмотр прошлых диктовок."),
                systemImage: "clock.arrow.circlepath",
                identifier: "settings-regular-history-row"
            ) {
                historyScreen
            }
            regularDivider
            regularNavigationRow(
                title: t("Dictionary", "Словарь"),
                subtitle: t("Teach Wai names and terms.", "Научи Wai именам и терминам."),
                systemImage: "book",
                identifier: "settings-regular-dictionary-row"
            ) {
                dictionaryScreen
            }
            regularDivider
            dictationLearningToggle
                .font(Typography.body)
                .padding(.vertical, Spacing.sm)
        }
    }

    private var dictationLearningToggle: some View {
        Toggle(isOn: $dictationLearnFromEditsEnabled) {
            VStack(alignment: .leading, spacing: Spacing.xxs) {
                Text(t("Suggest words from my edits", "Подсказывать слова из моих правок"))
                    .foregroundStyle(Palette.textPrimary)
                Text(t(
                    "Corrections you make in Dictation History can become local Dictionary suggestions.",
                    "Исправления в истории диктовки могут стать локальными подсказками словаря."
                ))
                .font(Typography.caption)
                .foregroundStyle(Palette.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            }
        }
        .toggleStyle(.switch)
        .accessibilityIdentifier("settings-dictation-learn-from-edits-toggle")
    }

    private var regularDataPanel: some View {
        regularSettingsPanel(
            title: t("Data", "Данные"),
            subtitle: t("Storage and export.", "Хранилище и экспорт."),
            systemImage: "internaldrive",
            identifier: "settings-regular-data-panel"
        ) {
            regularNavigationRow(
                title: t("Server & Data", "Сервер и данные"),
                subtitle: t("Current server and ownership map.", "Текущий сервер и карта данных."),
                systemImage: "server.rack",
                identifier: "settings-regular-server-data-row"
            ) {
                ServerDataView()
            }
            regularDivider
            regularNavigationRow(
                title: t("Export Readiness", "Готовность экспорта"),
                subtitle: t("What moves cleanly and what reconnects.", "Что переносится сразу, а что переподключается."),
                systemImage: "shippingbox",
                identifier: "settings-regular-export-readiness-row"
            ) {
                ExportReadinessView()
            }
        }
    }

    private var regularIntegrationsPanel: some View {
        regularSettingsPanel(
            title: t("Integrations", "Интеграции"),
            subtitle: t("Connect Wai to messengers and agents.", "Подключи Wai к мессенджерам и агентам."),
            systemImage: "link",
            identifier: "settings-regular-integrations-panel"
        ) {
            regularNavigationRow(
                title: "Telegram",
                subtitle: t("Send captures from Telegram.", "Отправляй материалы из Telegram."),
                systemImage: "paperplane",
                identifier: "settings-regular-telegram-row"
            ) {
                TelegramSettingsView()
            }
            regularDivider
            regularNavigationRow(
                title: "MCP",
                subtitle: t("Let agents search and ask your brain.", "Дай агентам поиск и вопросы к твоей памяти."),
                systemImage: "link.circle",
                identifier: "settings-regular-mcp-row"
            ) {
                McpConnectView()
            }
        }
    }

    private var regularAboutPanel: some View {
        regularSettingsPanel(
            title: t("App & Updates", "Приложение и обновления"),
            subtitle: t("Version and iOS update channel.", "Версия и канал обновлений iOS."),
            systemImage: "info.circle",
            identifier: "settings-regular-about-panel"
        ) {
            regularValueRow(
                title: t("Version", "Версия"),
                subtitle: appVersionDisplay,
                systemImage: "number",
                identifier: "settings-regular-version-row"
            )
            regularDivider
            regularValueRow(
                title: t("Updates", "Обновления"),
                subtitle: updateChannelDescription,
                systemImage: "arrow.triangle.2.circlepath",
                identifier: "settings-regular-update-channel-row"
            )
            Text(updateManagementDescription)
                .font(Typography.caption)
                .foregroundStyle(Palette.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.leading, 34)
                .accessibilityIdentifier("settings-regular-update-channel-note")
        }
    }

    private func regularSettingsPanel<Content: View>(
        title: String,
        subtitle: String?,
        systemImage: String,
        identifier: String,
        @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            HStack(alignment: .top, spacing: Spacing.md) {
                Image(systemName: systemImage)
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(Palette.accent)
                    .frame(width: 30, height: 30)
                    .background(Palette.accentSubtle)
                    .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                    .accessibilityHidden(true)

                VStack(alignment: .leading, spacing: Spacing.xs) {
                    Text(title)
                        .font(Typography.headingLarge)
                        .foregroundStyle(Palette.textPrimary)
                    if let subtitle {
                        Text(subtitle)
                            .font(Typography.caption)
                            .foregroundStyle(Palette.textSecondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }

            Divider()
            content()
        }
        .padding(Spacing.lg)
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .background(Color(uiColor: .secondarySystemGroupedBackground))
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .strokeBorder(Palette.border, lineWidth: 1)
        )
        .accessibilityIdentifier(identifier)
    }

    private var regularDivider: some View {
        Divider()
            .padding(.leading, 34)
    }

    private func regularNavigationRow<Destination: View>(
        title: String,
        subtitle: String? = nil,
        systemImage: String,
        identifier: String,
        @ViewBuilder destination: () -> Destination
    ) -> some View {
        NavigationLink(destination: destination()) {
            regularRowLabel(
                title: title,
                subtitle: subtitle,
                systemImage: systemImage,
                accessorySystemImage: "chevron.right"
            )
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier(identifier)
    }

    private func regularActionRow(
        title: String,
        subtitle: String? = nil,
        systemImage: String,
        role: ButtonRole? = nil,
        identifier: String,
        action: @escaping () -> Void
    ) -> some View {
        Button(role: role, action: action) {
            regularRowLabel(
                title: title,
                subtitle: subtitle,
                systemImage: systemImage,
                titleColor: role == .destructive ? .red : Palette.textPrimary,
                accessorySystemImage: nil
            )
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier(identifier)
    }

    private func regularLinkRow(
        title: String,
        systemImage: String,
        destination: URL,
        identifier: String
    ) -> some View {
        Link(destination: destination) {
            regularRowLabel(
                title: title,
                subtitle: nil,
                systemImage: systemImage,
                accessorySystemImage: "arrow.up.right"
            )
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier(identifier)
    }

    private func regularValueRow(
        title: String,
        subtitle: String?,
        systemImage: String,
        identifier: String
    ) -> some View {
        regularRowLabel(
            title: title,
            subtitle: subtitle,
            systemImage: systemImage,
            accessorySystemImage: nil
        )
        .accessibilityIdentifier(identifier)
    }

    private func regularRowLabel(
        title: String,
        subtitle: String?,
        systemImage: String,
        titleColor: Color = Palette.textPrimary,
        accessorySystemImage: String?
    ) -> some View {
        HStack(spacing: Spacing.sm) {
            Image(systemName: systemImage)
                .font(.system(size: 14, weight: .medium))
                .foregroundStyle(Palette.textSecondary)
                .frame(width: 24, height: 24)
                .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: Spacing.xxs) {
                Text(title)
                    .font(Typography.body)
                    .foregroundStyle(titleColor)
                    .lineLimit(1)
                    .minimumScaleFactor(0.82)

                if let subtitle {
                    Text(subtitle)
                        .font(Typography.caption)
                        .foregroundStyle(Palette.textTertiary)
                        .lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }

            Spacer(minLength: Spacing.md)

            if let accessorySystemImage {
                Image(systemName: accessorySystemImage)
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(Palette.textTertiary)
                    .accessibilityHidden(true)
            }
        }
        .contentShape(Rectangle())
        .padding(.vertical, Spacing.sm)
    }

    // MARK: - Dictation sub-screens

    /// Single-language transcription picker, shared with Recording via the
    /// legacy `transcriptionLanguage` UserDefaults mirror.
    private var dictationLanguageScreen: some View {
        Group {
            if horizontalSizeClass == .regular {
                dictationLanguageRegularLayout
            } else {
                dictationLanguageCompactForm
            }
        }
        .navigationTitle(t("Transcription Language", "Язык расшифровки"))
        .navigationBarTitleDisplayMode(horizontalSizeClass == .regular ? .inline : .large)
    }

    private var dictationLanguageCompactForm: some View {
        Form {
            Section {
                LanguagePickerView(store: dictationLanguageStore)
            } footer: {
                Text(t(
                    "Pick one language for the fastest start, or auto-detect when you switch often.",
                    "Выбери один язык для самого быстрого старта или автоопределение, если часто переключаешься."
                ))
            }
        }
    }

    private var dictationLanguageRegularLayout: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Spacing.xl) {
                dictationLanguageRegularHeader

                LazyVGrid(
                    columns: [GridItem(.adaptive(minimum: 320), spacing: Spacing.lg, alignment: .top)],
                    alignment: .leading,
                    spacing: Spacing.lg
                ) {
                    regularSettingsPanel(
                        title: t("Language Mode", "Режим языка"),
                        subtitle: t(
                            "Pick one language for the fastest start, or auto-detect when you switch often.",
                            "Выбери один язык для самого быстрого старта или автоопределение, если часто переключаешься."
                        ),
                        systemImage: "text.bubble",
                        identifier: "settings-transcription-language-picker-panel"
                    ) {
                        LanguagePickerView(store: dictationLanguageStore)
                    }

                    regularSettingsPanel(
                        title: t("Current Behavior", "Текущее поведение"),
                        subtitle: t(
                            "This affects live dictation and the iOS recording language hint.",
                            "Это влияет на живую диктовку и языковую подсказку записи на iOS."
                        ),
                        systemImage: "speedometer",
                        identifier: "settings-transcription-language-summary-panel"
                    ) {
                        VStack(alignment: .leading, spacing: Spacing.md) {
                            regularValueRow(
                                title: t("Mode", "Режим"),
                                subtitle: dictationLanguageModeLabel,
                                systemImage: dictationLanguageStore.isAutoDetect ? "sparkles" : "bolt",
                                identifier: "settings-transcription-language-mode-row"
                            )
                            regularValueRow(
                                title: t("Provider tag", "Тег провайдера"),
                                subtitle: dictationLanguageProviderTag,
                                systemImage: "curlybraces",
                                identifier: "settings-transcription-language-provider-row"
                            )
                            Text(t(
                                "Recording transcription still uses the server pipeline; this preference keeps the local iOS live path aligned with Mac dictation semantics.",
                                "Расшифровка записей всё равно идёт через серверный пайплайн; эта настройка выравнивает локальный live-путь iOS с семантикой диктовки на Mac."
                            ))
                            .font(Typography.caption)
                            .foregroundStyle(Palette.textSecondary)
                            .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
            }
            .padding(.horizontal, Spacing.xxl)
            .padding(.vertical, Spacing.xxl)
            .frame(maxWidth: 980, alignment: .topLeading)
            .frame(maxWidth: .infinity, alignment: .top)
        }
        .background(Color(uiColor: .systemGroupedBackground))
        .accessibilityIdentifier("settings-transcription-language-regular-layout")
    }

    private var dictationLanguageRegularHeader: some View {
        HStack(alignment: .center, spacing: Spacing.md) {
            Image(systemName: "text.bubble")
                .font(.system(size: 18, weight: .semibold))
                .foregroundStyle(Palette.accent)
                .frame(width: 42, height: 42)
                .background(Color(uiColor: .secondarySystemGroupedBackground))
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .strokeBorder(Palette.border, lineWidth: 1)
                )
                .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: Spacing.xs) {
                Text(t("Transcription Language", "Язык расшифровки"))
                    .font(Typography.displayMedium)
                    .foregroundStyle(Palette.textPrimary)
                Text(t(
                    "Control the live language hint used by iOS and shared dictation settings.",
                    "Управляйте live-языковой подсказкой iOS и общими настройками диктовки."
                ))
                .font(Typography.bodySmall)
                .foregroundStyle(Palette.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            }
        }
        .accessibilityIdentifier("settings-transcription-language-regular-header")
    }

    private var dictationLanguageModeLabel: String {
        if dictationLanguageStore.isAutoDetect {
            return t("Auto-detect", "Автоопределение")
        }
        guard let only = dictationLanguageStore.selectedLanguages.first,
              let entry = DictationLanguageCatalog.entry(for: only) else {
            return t("Auto-detect", "Автоопределение")
        }
        if languageManager.current == .russian {
            return entry.nativeName
        }
        return entry.englishName
    }

    private var dictationLanguageProviderTag: String {
        dictationLanguageStore.wireLanguageTag.isEmpty
            ? t("multilingual", "мультиязычно")
            : dictationLanguageStore.wireLanguageTag
    }

    private var historyScreen: some View {
        DictationHistoryView()
    }

    private var dictionaryScreen: some View {
        DictationDictionaryView()
    }

    // MARK: - Microphone permission

    @ViewBuilder
    private var microphonePermissionRow: some View {
        HStack {
            Label(t("Microphone", "Микрофон"), systemImage: "mic")
            Spacer()
            switch micPermission {
            case .granted:
                Label(t("Granted", "Разрешено"), systemImage: "checkmark.circle.fill")
                    .labelStyle(.titleAndIcon)
                    .font(Typography.bodySmall)
                    .foregroundStyle(.green)
            case .denied:
                Button(t("Open Settings", "Открыть настройки")) {
                    openAppSettings()
                }
                .font(Typography.bodySmall)
                .accessibilityIdentifier("settings-permission-microphone-settings")
            case .undetermined:
                Button(t("Grant", "Разрешить")) {
                    Task {
                        _ = await AVAudioApplication.requestRecordPermission()
                        micPermission = AVAudioApplication.shared.recordPermission
                    }
                }
                .font(Typography.bodySmall)
                .accessibilityIdentifier("settings-permission-microphone-grant")
            @unknown default:
                Button(t("Open Settings", "Открыть настройки")) {
                    openAppSettings()
                }
                .font(Typography.bodySmall)
            }
        }
    }

    private func openAppSettings() {
        guard let url = URL(string: UIApplication.openSettingsURLString) else { return }
        UIApplication.shared.open(url)
    }

    // MARK: - Helpers

    private func memberSinceText(_ date: Date) -> String {
        let formatted = IOSDateFormatting.string(
            from: date,
            dateStyle: .medium,
            timeStyle: .none,
            language: languageManager.current
        )
        return t("Member since \(formatted)", "С нами с \(formatted)")
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

struct RecordingPipelineView: View {
    @EnvironmentObject var appState: AppState
    @EnvironmentObject var languageManager: LanguageManager
    @Environment(\.horizontalSizeClass) private var pipelineHorizontalSizeClass
    @State private var snapshot: RecordingPipelineSnapshot?
    @State private var isLoading = false
    @State private var loadError: String?

    private var captureSampleRateLabel: String {
        "\(Int(AudioCaptureConfig.default.sampleRate / 1_000)) kHz"
    }

    var body: some View {
        Group {
            if pipelineHorizontalSizeClass == .regular {
                recordingPipelineRegularLayout
            } else {
                recordingPipelineCompactList
            }
        }
        .navigationTitle(t("Recording Pipeline", "Пайплайн записи"))
        .navigationBarTitleDisplayMode(pipelineHorizontalSizeClass == .regular ? .inline : .large)
        .task {
            await loadSnapshot()
        }
    }

    private var recordingPipelineCompactList: some View {
        List {
            if isLoading && snapshot == nil {
                Section {
                    HStack {
                        ProgressView()
                        Text(t("Loading recording pipeline…", "Загружаем пайплайн записи…"))
                            .foregroundStyle(.secondary)
                    }
                }
            }

            if let snapshot {
                Section(t("Capture", "Запись")) {
                    pipelineRow(
                        title: t("Microphone input", "Вход микрофона"),
                        value: t("iOS microphone", "Микрофон iOS"),
                        detail: t("Uses the system input route selected by iOS.", "Использует системный вход, выбранный iOS."),
                        systemImage: "mic"
                    )
                    pipelineRow(
                        title: t("Capture format", "Формат записи"),
                        value: t("\(captureSampleRateLabel) mono PCM", "\(captureSampleRateLabel) моно PCM"),
                        detail: t("Captured once, then reused for live captions and the upload.", "Пишется один раз, затем используется для живых титров и загрузки."),
                        systemImage: "waveform"
                    )
                    pipelineRow(
                        title: t("Local backup", "Локальная копия"),
                        value: t("Saved before upload", "Сохраняется до загрузки"),
                        detail: t("The app writes audio locally before sending it to the server.", "Приложение записывает аудио локально перед отправкой на сервер."),
                        systemImage: "internaldrive"
                    )
                }

                Section {
                    modelRow(
                        title: t("Live recording", "Живая запись"),
                        provider: snapshot.settings.recordingLiveSTTProvider,
                        model: snapshot.settings.recordingLiveSTTModel,
                        options: snapshot.options.recordingLiveSTT,
                        context: .recordingLiveSTT
                    )
                    modelRow(
                        title: t("Final transcript", "Финальная расшифровка"),
                        provider: snapshot.settings.fileSTTProvider,
                        model: snapshot.settings.fileSTTModel,
                        options: snapshot.options.fileSTT,
                        context: .fileSTT
                    )
                } header: {
                    Text(t("Server transcription", "Серверная расшифровка"))
                } footer: {
                    Text(t(
                        "These values come from the server account settings. iOS does not expose fake local sample-rate or noise-suppression switches.",
                        "Эти значения приходят из серверных настроек аккаунта. iOS не показывает фиктивные локальные переключатели частоты или шумоподавления."
                    ))
                }

                Section(t("Dictation model", "Модель диктовки")) {
                    modelRow(
                        title: t("Live dictation", "Живая диктовка"),
                        provider: snapshot.settings.dictationLiveSTTProvider,
                        model: snapshot.settings.dictationLiveSTTModel,
                        options: snapshot.options.dictationLiveSTT,
                        context: .dictationLiveSTT
                    )
                }
            }

            if let loadError {
                Section {
                    Text(loadError)
                        .font(Typography.caption)
                        .foregroundStyle(.red)
                        .fixedSize(horizontal: false, vertical: true)
                    Button(t("Retry", "Повторить")) {
                        Task { await loadSnapshot(force: true) }
                    }
                }
            }
        }
        .accessibilityIdentifier("settings-recording-pipeline-view")
    }

    private var recordingPipelineRegularLayout: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Spacing.xl) {
                recordingPipelineRegularHeader

                if let snapshot {
                    LazyVGrid(
                        columns: [GridItem(.adaptive(minimum: 320), spacing: Spacing.lg, alignment: .top)],
                        alignment: .leading,
                        spacing: Spacing.lg
                    ) {
                        recordingPipelineRegularCapturePanel
                        recordingPipelineRegularServerPanel(snapshot)
                        recordingPipelineRegularDictationPanel(snapshot)
                    }
                } else if loadError == nil {
                    recordingPipelineRegularLoadingPanel
                }

                if let loadError {
                    dataRegularPanel(
                        title: t("Could not load pipeline", "Не удалось загрузить пайплайн"),
                        subtitle: loadError,
                        systemImage: "exclamationmark.triangle",
                        identifier: "settings-recording-pipeline-error-panel"
                    ) {
                        Button(t("Retry", "Повторить")) {
                            Task { await loadSnapshot(force: true) }
                        }
                        .buttonStyle(.borderedProminent)
                    }
                }
            }
            .padding(.horizontal, Spacing.xxl)
            .padding(.vertical, Spacing.xxl)
            .frame(maxWidth: 980, alignment: .topLeading)
            .frame(maxWidth: .infinity, alignment: .top)
        }
        .background(Color(uiColor: .systemGroupedBackground))
        .accessibilityIdentifier("settings-recording-pipeline-regular-layout")
    }

    private var recordingPipelineRegularHeader: some View {
        HStack(alignment: .center, spacing: Spacing.md) {
            Image(systemName: "waveform.badge.mic")
                .font(.system(size: 18, weight: .semibold))
                .foregroundStyle(Palette.accent)
                .frame(width: 42, height: 42)
                .background(Color(uiColor: .secondarySystemGroupedBackground))
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .strokeBorder(Palette.border, lineWidth: 1)
                )
                .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: Spacing.xs) {
                Text(t("Recording Pipeline", "Пайплайн записи"))
                    .font(Typography.displayMedium)
                    .foregroundStyle(Palette.textPrimary)
                Text(t(
                    "How iOS captures audio and which server models transcribe it.",
                    "Как iOS записывает аудио и какие серверные модели его расшифровывают."
                ))
                .font(Typography.bodySmall)
                .foregroundStyle(Palette.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            }
        }
        .accessibilityIdentifier("settings-recording-pipeline-regular-header")
    }

    private var recordingPipelineRegularLoadingPanel: some View {
        dataRegularPanel(
            title: t("Loading recording pipeline", "Загружаем пайплайн записи"),
            subtitle: nil,
            systemImage: "arrow.triangle.2.circlepath",
            identifier: "settings-recording-pipeline-loading-panel"
        ) {
            HStack(spacing: Spacing.sm) {
                ProgressView()
                    .controlSize(.small)
                Text(t("Reading capture and server model settings…", "Читаем настройки записи и серверных моделей…"))
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textTertiary)
            }
        }
    }

    private var recordingPipelineRegularCapturePanel: some View {
        dataRegularPanel(
            title: t("Capture", "Запись"),
            subtitle: t(
                "The iOS capture path is fixed and explicit; there are no fake local audio switches.",
                "Путь записи на iOS фиксированный и явный; фиктивных локальных аудио-переключателей нет."
            ),
            systemImage: "mic",
            identifier: "settings-recording-pipeline-regular-capture-panel"
        ) {
            VStack(alignment: .leading, spacing: Spacing.sm) {
                pipelineRow(
                    title: t("Microphone input", "Вход микрофона"),
                    value: t("iOS microphone", "Микрофон iOS"),
                    detail: t("Uses the system input route selected by iOS.", "Использует системный вход, выбранный iOS."),
                    systemImage: "mic"
                )
                Divider()
                pipelineRow(
                    title: t("Capture format", "Формат записи"),
                    value: t("\(captureSampleRateLabel) mono PCM", "\(captureSampleRateLabel) моно PCM"),
                    detail: t("Captured once, then reused for live captions and the upload.", "Пишется один раз, затем используется для живых титров и загрузки."),
                    systemImage: "waveform"
                )
                Divider()
                pipelineRow(
                    title: t("Local backup", "Локальная копия"),
                    value: t("Saved before upload", "Сохраняется до загрузки"),
                    detail: t("The app writes audio locally before sending it to the server.", "Приложение записывает аудио локально перед отправкой на сервер."),
                    systemImage: "internaldrive"
                )
            }
        }
    }

    private func recordingPipelineRegularServerPanel(_ snapshot: RecordingPipelineSnapshot) -> some View {
        dataRegularPanel(
            title: t("Server Transcription", "Серверная расшифровка"),
            subtitle: t(
                "These values come from account settings and are shared with the Mac app.",
                "Эти значения приходят из настроек аккаунта и совпадают с Mac-приложением."
            ),
            systemImage: "cpu",
            identifier: "settings-recording-pipeline-regular-server-panel"
        ) {
            VStack(alignment: .leading, spacing: Spacing.sm) {
                modelRow(
                    title: t("Live recording", "Живая запись"),
                    provider: snapshot.settings.recordingLiveSTTProvider,
                    model: snapshot.settings.recordingLiveSTTModel,
                    options: snapshot.options.recordingLiveSTT,
                    context: .recordingLiveSTT
                )
                Divider()
                modelRow(
                    title: t("Final transcript", "Финальная расшифровка"),
                    provider: snapshot.settings.fileSTTProvider,
                    model: snapshot.settings.fileSTTModel,
                    options: snapshot.options.fileSTT,
                    context: .fileSTT
                )
            }
        }
    }

    private func recordingPipelineRegularDictationPanel(_ snapshot: RecordingPipelineSnapshot) -> some View {
        dataRegularPanel(
            title: t("Dictation Model", "Модель диктовки"),
            subtitle: t(
                "The live dictation model used when you speak directly to Wai.",
                "Модель живой диктовки, когда вы говорите прямо с Wai."
            ),
            systemImage: "text.bubble",
            identifier: "settings-recording-pipeline-regular-dictation-panel"
        ) {
            modelRow(
                title: t("Live dictation", "Живая диктовка"),
                provider: snapshot.settings.dictationLiveSTTProvider,
                model: snapshot.settings.dictationLiveSTTModel,
                options: snapshot.options.dictationLiveSTT,
                context: .dictationLiveSTT
            )
        }
    }

    private func pipelineRow(
        title: String,
        value: String,
        detail: String,
        systemImage: String
    ) -> some View {
        HStack(alignment: .top, spacing: Spacing.sm) {
            Image(systemName: systemImage)
                .font(.system(size: 16, weight: .medium))
                .foregroundStyle(Palette.accent)
                .frame(width: 24)
                .padding(.top, 2)
                .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: Spacing.xs) {
                Text(title)
                    .font(Typography.body)
                Text(value)
                    .font(Typography.label)
                    .foregroundStyle(Palette.textPrimary)
                Text(detail)
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.vertical, Spacing.sm)
    }

    private func modelRow(
        title: String,
        provider: String,
        model: String,
        options: [TranscriptionModelOption],
        context: TranscriptionModelOptionContext
    ) -> some View {
        let option = options.first { $0.provider == provider && $0.model == model }
        return HStack(alignment: .top, spacing: Spacing.sm) {
            Image(systemName: option == nil ? "exclamationmark.triangle" : "cpu")
                .font(.system(size: 16, weight: .medium))
                .foregroundStyle(option == nil ? .orange : Palette.accent)
                .frame(width: 24)
                .padding(.top, 2)
                .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: Spacing.xs) {
                Text(title)
                    .font(Typography.body)
                Text(option?.label ?? "\(provider) \(model)")
                    .font(Typography.label)
                    .foregroundStyle(Palette.textPrimary)
                Text(modelDescription(option: option, provider: provider, model: model, context: context))
                    .font(Typography.caption)
                    .foregroundStyle(option == nil ? .orange : Palette.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.vertical, Spacing.sm)
    }

    private func modelDescription(
        option: TranscriptionModelOption?,
        provider: String,
        model: String,
        context: TranscriptionModelOptionContext
    ) -> String {
        guard let option else {
            return t(
                "Configured model \(provider)/\(model) is not present in the server options response.",
                "Настроенная модель \(provider)/\(model) отсутствует в ответе сервера со списком моделей."
            )
        }
        return TranscriptionModelDescriptionCopy.description(
            for: option,
            context: context,
            language: languageManager.current
        )
    }

    private func loadSnapshot(force: Bool = false) async {
        guard force || snapshot == nil else { return }
        isLoading = true
        defer { isLoading = false }

        do {
            snapshot = try await loadRecordingPipelineSnapshot(appState: appState)
            loadError = nil
        } catch {
            loadError = t(
                "Couldn't load recording pipeline: \(error.userFacingMessage(context: .generic))",
                "Не удалось загрузить пайплайн записи: \(error.userFacingMessage(context: .generic))"
            )
        }
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

struct SummarySettingsView: View {
    @EnvironmentObject var appState: AppState
    @EnvironmentObject var languageManager: LanguageManager
    @Environment(\.horizontalSizeClass) private var summaryHorizontalSizeClass
    @State private var summaryLanguage = "auto"
    @State private var summaryStyle = "medium"
    @State private var summaryInstructions = ""
    @State private var settingsLoaded = false
    @State private var isLoading = false
    @State private var settingsError: String?
    @State private var instructionsSaveTask: Task<Void, Never>?

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
        Group {
            if summaryHorizontalSizeClass == .regular {
                summaryRegularLayout
            } else {
                summaryCompactList
            }
        }
        .navigationTitle(t("AI Summary", "AI-резюме"))
        .navigationBarTitleDisplayMode(summaryHorizontalSizeClass == .regular ? .inline : .large)
        .accessibilityIdentifier("settings-summary-view")
        .task {
            await loadSettings()
        }
        .onDisappear {
            flushInstructionsSave()
        }
    }

    private var summaryCompactList: some View {
        List {
            if isLoading && !settingsLoaded {
                Section {
                    HStack {
                        ProgressView()
                        Text(t("Loading summary settings…", "Загружаем настройки резюме…"))
                            .foregroundStyle(.secondary)
                    }
                }
            }

            Section(t("Language", "Язык")) {
                summaryLanguagePicker
            }

            Section(t("Detail Level", "Уровень детализации")) {
                summaryStylePicker
            }

            Section {
                summaryInstructionsField
            } header: {
                Text(t("Custom Instructions", "Особые инструкции"))
            } footer: {
                Text(t(
                    "Saved to your server account and used when new recording summaries are generated.",
                    "Сохраняется в серверном аккаунте и используется при создании новых резюме записей."
                ))
            }

            if let settingsError {
                Section {
                    Text(settingsError)
                        .font(Typography.caption)
                        .foregroundStyle(.red)
                        .fixedSize(horizontal: false, vertical: true)
                    Button(t("Retry", "Повторить")) {
                        Task { await loadSettings(force: true) }
                    }
                }
            }
        }
    }

    private var summaryRegularLayout: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Spacing.xl) {
                summaryRegularHeader

                if settingsLoaded {
                    LazyVGrid(
                        columns: [GridItem(.adaptive(minimum: 320), spacing: Spacing.lg, alignment: .top)],
                        alignment: .leading,
                        spacing: Spacing.lg
                    ) {
                        summaryRegularDefaultsPanel
                        summaryRegularInstructionsPanel
                        summaryRegularPreviewPanel
                    }
                } else if isLoading {
                    summaryRegularLoadingPanel
                } else {
                    summaryRegularUnavailablePanel
                }

                if let settingsError, settingsLoaded {
                    summaryRegularError(settingsError)
                }
            }
            .padding(.horizontal, Spacing.xxl)
            .padding(.vertical, Spacing.xxl)
            .frame(maxWidth: 920, alignment: .topLeading)
            .frame(maxWidth: .infinity, alignment: .top)
        }
        .background(Color(uiColor: .systemGroupedBackground))
        .accessibilityIdentifier("settings-summary-regular-layout")
    }

    private var summaryRegularHeader: some View {
        HStack(alignment: .center, spacing: Spacing.md) {
            Image(systemName: "sparkles")
                .font(.system(size: 18, weight: .semibold))
                .foregroundStyle(Palette.accent)
                .frame(width: 42, height: 42)
                .background(Color(uiColor: .secondarySystemGroupedBackground))
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .strokeBorder(Palette.border, lineWidth: 1)
                )
                .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: Spacing.xs) {
                Text(t("AI Summary", "AI-резюме"))
                    .font(Typography.displayMedium)
                    .foregroundStyle(Palette.textPrimary)
                Text(t(
                    "Language, detail level, and custom guidance for new recording summaries.",
                    "Язык, детализация и инструкции для новых резюме записей."
                ))
                .font(Typography.bodySmall)
                .foregroundStyle(Palette.textSecondary)
            }
        }
        .accessibilityIdentifier("settings-summary-regular-header")
    }

    private var summaryRegularDefaultsPanel: some View {
        summaryRegularPanel(
            title: t("Defaults", "Настройки"),
            subtitle: t(
                "Used when the server generates a new summary.",
                "Используются сервером при создании нового резюме."
            ),
            systemImage: "slider.horizontal.3",
            identifier: "settings-summary-regular-defaults-panel"
        ) {
            VStack(alignment: .leading, spacing: Spacing.md) {
                summaryLanguagePicker
                Divider()
                summaryStylePicker
            }
        }
    }

    private var summaryRegularInstructionsPanel: some View {
        summaryRegularPanel(
            title: t("Custom Instructions", "Особые инструкции"),
            subtitle: t(
                "Tell Wai what to emphasize in every new recording summary.",
                "Подскажи Wai, на чём делать акцент в новых резюме записей."
            ),
            systemImage: "text.alignleft",
            identifier: "settings-summary-regular-instructions-panel"
        ) {
            VStack(alignment: .leading, spacing: Spacing.sm) {
                summaryInstructionsEditor
                Text(t(
                    "Example: focus on decisions, risks, and action items.",
                    "Пример: фокус на решениях, рисках и задачах."
                ))
                .font(Typography.caption)
                .foregroundStyle(Palette.textTertiary)
            }
        }
    }

    private var summaryRegularPreviewPanel: some View {
        summaryRegularPanel(
            title: t("Preview", "Предпросмотр"),
            subtitle: t(
                "Current settings at a glance.",
                "Текущие настройки одним взглядом."
            ),
            systemImage: "doc.text.magnifyingglass",
            identifier: "settings-summary-regular-preview-panel"
        ) {
            VStack(alignment: .leading, spacing: Spacing.md) {
                summaryRegularInfoRow(
                    title: t("Summary language", "Язык резюме"),
                    value: summaryLanguageLabel,
                    systemImage: "text.bubble"
                )
                Divider()
                summaryRegularInfoRow(
                    title: t("Detail level", "Уровень детализации"),
                    value: summaryStyleLabel,
                    systemImage: "list.bullet.rectangle"
                )
                Divider()
                summaryRegularInfoRow(
                    title: t("Applies to", "Применяется"),
                    value: t("New recording summaries", "Новые резюме записей"),
                    systemImage: "sparkle"
                )
            }
        }
    }

    private var summaryRegularLoadingPanel: some View {
        summaryRegularPanel(
            title: t("AI Summary", "AI-резюме"),
            subtitle: nil,
            systemImage: "sparkles",
            identifier: "settings-summary-loading-panel"
        ) {
            HStack(spacing: Spacing.sm) {
                ProgressView()
                    .controlSize(.small)
                Text(t("Loading summary settings…", "Загружаем настройки резюме…"))
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textTertiary)
            }
        }
    }

    private var summaryRegularUnavailablePanel: some View {
        summaryRegularPanel(
            title: t("Could not load settings", "Не удалось загрузить настройки"),
            subtitle: settingsError,
            systemImage: "exclamationmark.triangle",
            identifier: "settings-summary-unavailable-panel"
        ) {
            Button(t("Retry", "Повторить")) {
                Task { await loadSettings(force: true) }
            }
            .buttonStyle(.borderedProminent)
        }
    }

    private var summaryLanguagePicker: some View {
        Picker(t("Summary Language", "Язык резюме"), selection: $summaryLanguage) {
            ForEach(summaryLanguageOptions, id: \.value) { option in
                Text(option.label).tag(option.value)
            }
        }
        .disabled(!settingsLoaded || isLoading)
        .onChange(of: summaryLanguage) { _, newValue in
            guard settingsLoaded else { return }
            Task { await saveSettings(language: newValue) }
        }
        .accessibilityIdentifier("settings-summary-language-picker")
    }

    private var summaryStylePicker: some View {
        Picker(t("Summary Style", "Стиль резюме"), selection: $summaryStyle) {
            ForEach(summaryStyleOptions, id: \.value) { option in
                Text(option.label).tag(option.value)
            }
        }
        .disabled(!settingsLoaded || isLoading)
        .onChange(of: summaryStyle) { _, newValue in
            guard settingsLoaded else { return }
            Task { await saveSettings(style: newValue) }
        }
        .accessibilityIdentifier("settings-summary-style-picker")
    }

    private var summaryInstructionsField: some View {
        TextField(
            t("E.g. \"Focus on action items\"", "Например: «Фокус на задачах»"),
            text: $summaryInstructions,
            axis: .vertical
        )
        .lineLimit(2...4)
        .disabled(!settingsLoaded || isLoading)
        .onChange(of: summaryInstructions) { _, newValue in
            guard settingsLoaded else { return }
            scheduleInstructionsSave(newValue)
        }
        .accessibilityIdentifier("settings-summary-instructions-field")
    }

    private var summaryInstructionsEditor: some View {
        TextEditor(text: $summaryInstructions)
            .font(Typography.body)
            .frame(minHeight: 112)
            .scrollContentBackground(.hidden)
            .padding(Spacing.sm)
            .background(Color(uiColor: .tertiarySystemGroupedBackground))
            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .strokeBorder(Palette.border, lineWidth: 1)
            )
            .disabled(!settingsLoaded || isLoading)
            .onChange(of: summaryInstructions) { _, newValue in
                guard settingsLoaded else { return }
                scheduleInstructionsSave(newValue)
            }
            .accessibilityIdentifier("settings-summary-instructions-editor")
    }

    private func summaryRegularPanel<Content: View>(
        title: String,
        subtitle: String?,
        systemImage: String,
        identifier: String,
        @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            HStack(alignment: .top, spacing: Spacing.md) {
                Image(systemName: systemImage)
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(Palette.accent)
                    .frame(width: 30, height: 30)
                    .background(Palette.accentSubtle)
                    .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                    .accessibilityHidden(true)

                VStack(alignment: .leading, spacing: Spacing.xs) {
                    Text(title)
                        .font(Typography.headingLarge)
                        .foregroundStyle(Palette.textPrimary)
                    if let subtitle {
                        Text(subtitle)
                            .font(Typography.caption)
                            .foregroundStyle(Palette.textSecondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }

            Divider()
            content()
        }
        .padding(Spacing.lg)
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .background(Color(uiColor: .secondarySystemGroupedBackground))
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .strokeBorder(Palette.border, lineWidth: 1)
        )
        .accessibilityIdentifier(identifier)
    }

    private func summaryRegularInfoRow(
        title: String,
        value: String,
        systemImage: String
    ) -> some View {
        HStack(alignment: .top, spacing: Spacing.sm) {
            Image(systemName: systemImage)
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(Palette.accent)
                .frame(width: 24, height: 24)
                .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: Spacing.xxs) {
                Text(title)
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textTertiary)
                Text(value)
                    .font(Typography.body)
                    .foregroundStyle(Palette.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private func summaryRegularError(_ error: String) -> some View {
        Text(error)
            .font(Typography.caption)
            .foregroundStyle(.red)
            .fixedSize(horizontal: false, vertical: true)
            .accessibilityIdentifier("settings-summary-error")
    }

    private var summaryLanguageLabel: String {
        summaryLanguageOptions.first { $0.value == summaryLanguage }?.label ?? summaryLanguage
    }

    private var summaryStyleLabel: String {
        summaryStyleOptions.first { $0.value == summaryStyle }?.label ?? summaryStyle
    }

    private func loadSettings(force: Bool = false) async {
        guard force || !settingsLoaded else { return }
        isLoading = true
        defer { isLoading = false }

        #if DEBUG
        if IOSTestingMode.current.isScreenshot {
            applySettings(IOSSummarySettingsFixtures.settings)
            settingsError = nil
            settingsLoaded = true
            return
        }
        #endif

        do {
            let settings = try await appState.getAPIClient().getSettings()
            applySettings(settings)
            settingsError = nil
            settingsLoaded = true
        } catch {
            settingsError = t(
                "Couldn't load summary settings: \(error.userFacingMessage(context: .generic))",
                "Не удалось загрузить настройки резюме: \(error.userFacingMessage(context: .generic))"
            )
        }
    }

    private func saveSettings(
        language: String? = nil,
        style: String? = nil,
        instructions: String? = nil
    ) async {
        #if DEBUG
        if IOSTestingMode.current.isScreenshot {
            settingsError = nil
            return
        }
        #endif

        let request = UpdateSettingsRequest(
            summaryLanguage: language,
            summaryStyle: style,
            summaryInstructions: instructions
        )

        do {
            let settings = try await appState.getAPIClient().updateSettings(request)
            applySettings(settings)
            settingsError = nil
        } catch {
            settingsError = t(
                "Couldn't save summary settings: \(error.userFacingMessage(context: .generic))",
                "Не удалось сохранить настройки резюме: \(error.userFacingMessage(context: .generic))"
            )
        }
    }

    private func applySettings(_ settings: UserSettings) {
        summaryLanguage = settings.summaryLanguage
        summaryStyle = settings.summaryStyle
        summaryInstructions = settings.summaryInstructions ?? ""
    }

    private func scheduleInstructionsSave(_ instructions: String) {
        instructionsSaveTask?.cancel()
        instructionsSaveTask = Task { @MainActor in
            do {
                try await Task.sleep(for: .milliseconds(600))
            } catch {
                return
            }
            guard !Task.isCancelled else { return }
            await saveSettings(instructions: instructions)
            guard !Task.isCancelled else { return }
            instructionsSaveTask = nil
        }
    }

    private func flushInstructionsSave() {
        guard settingsLoaded, instructionsSaveTask != nil else { return }
        instructionsSaveTask?.cancel()
        instructionsSaveTask = nil
        let instructions = summaryInstructions
        Task { await saveSettings(instructions: instructions) }
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

#if DEBUG
private enum IOSSummarySettingsFixtures {
    static let settings: UserSettings = {
        let json = """
        {
          "default_language": "multi",
          "summary_language": "auto",
          "summary_style": "medium",
          "summary_instructions": "Focus on decisions, risks, and action items.",
          "dictation_live_stt_provider": "deepgram",
          "dictation_live_stt_model": "nova-3",
          "recording_live_stt_provider": "deepgram",
          "recording_live_stt_model": "nova-3",
          "file_stt_provider": "deepgram",
          "file_stt_model": "nova-3",
          "dictation_post_filter_enabled": false,
          "dictation_cleanup_level": "none",
          "dictation_post_filter_provider": "openai",
          "dictation_post_filter_model": "gpt-4.1-mini",
          "region": "global"
        }
        """
        do {
            return try JSONDecoder().decode(UserSettings.self, from: Data(json.utf8))
        } catch {
            fatalError("summary settings fixture JSON is malformed - fix IOSSummarySettingsFixtures")
        }
    }()
}
#endif

private struct RecordingPipelineSnapshot {
    let settings: UserSettings
    let options: TranscriptionOptions
}

@MainActor
private func loadRecordingPipelineSnapshot(appState: AppState) async throws -> RecordingPipelineSnapshot {
    #if DEBUG
        if IOSTestingMode.current.isScreenshot {
            return IOSRecordingPipelineFixtures.snapshot
        }
    #endif

    let client = appState.getAPIClient()
    async let settings = client.getSettings()
    async let options = client.getTranscriptionOptions()
    return try await RecordingPipelineSnapshot(
        settings: settings,
        options: options
    )
}

#if DEBUG
private enum IOSRecordingPipelineFixtures {
    static let snapshot = RecordingPipelineSnapshot(
        settings: settings,
        options: TranscriptionOptions(
            dictationLiveSTT: [nova3],
            recordingLiveSTT: [nova3],
            fileSTT: [nova3],
            dictationPostFilter: [
                TranscriptionModelOption(
                    provider: "openai",
                    model: "gpt-4.1-mini",
                    label: "OpenAI GPT-4.1 mini",
                    description: "Optional cleanup pass for dictation text."
                ),
            ]
        )
    )

    private static let nova3 = TranscriptionModelOption(
        provider: "deepgram",
        model: "nova-3",
        label: "Deepgram Nova-3",
        description: "Fast streaming speech recognition for live capture and final transcription."
    )

    private static let settings: UserSettings = {
        let json = """
        {
          "default_language": "multi",
          "summary_language": "auto",
          "summary_style": "medium",
          "summary_instructions": "Focus on decisions and action items.",
          "dictation_live_stt_provider": "deepgram",
          "dictation_live_stt_model": "nova-3",
          "recording_live_stt_provider": "deepgram",
          "recording_live_stt_model": "nova-3",
          "file_stt_provider": "deepgram",
          "file_stt_model": "nova-3",
          "dictation_post_filter_enabled": false,
          "dictation_cleanup_level": "none",
          "dictation_post_filter_provider": "openai",
          "dictation_post_filter_model": "gpt-4.1-mini",
          "region": "global"
        }
        """
        do {
            return try JSONDecoder().decode(UserSettings.self, from: Data(json.utf8))
        } catch {
            fatalError("recording pipeline fixture JSON is malformed — fix IOSRecordingPipelineFixtures")
        }
    }()
}
#endif

struct ServerDataView: View {
    @EnvironmentObject var appState: AppState
    @EnvironmentObject var languageManager: LanguageManager
    @Environment(\.horizontalSizeClass) private var serverDataHorizontalSizeClass
    @State private var snapshot: ServerDataSnapshot?
    @State private var isLoading = false
    @State private var loadError: String?

    var body: some View {
        Group {
            if serverDataHorizontalSizeClass == .regular {
                serverDataRegularLayout
            } else {
                serverDataCompactList
            }
        }
        .navigationTitle(t("Server & Data", "Сервер и данные"))
        .navigationBarTitleDisplayMode(serverDataHorizontalSizeClass == .regular ? .inline : .large)
        .task { await loadSnapshot() }
        .refreshable { await loadSnapshot(force: true) }
    }

    private var serverDataCompactList: some View {
        List {
            Section {
                if let snapshot {
                    LabeledContent {
                        Text(serverLabel(snapshot.systemInfo))
                            .foregroundStyle(Palette.textPrimary)
                    } label: {
                        Text(t("Current server", "Текущий сервер"))
                    }

                    LabeledContent {
                        Text(snapshot.dataMap.audioRetentionPolicy)
                            .multilineTextAlignment(.trailing)
                            .foregroundStyle(Palette.textSecondary)
                    } label: {
                        Text(t("Audio retention", "Хранение аудио"))
                    }
                } else if isLoading {
                    ProgressView(t("Loading data map…", "Загружаем карту данных…"))
                }
            } header: {
                Text(t("Server", "Сервер"))
            }

            if let snapshot {
                Section {
                    ServerDataMetricsView(
                        ownedCount: ownershipCount(.ownedExportable, in: snapshot.dataMap),
                        fileCount: snapshot.dataMap.artifacts.count,
                        reconnectCount: reconnectCount(in: snapshot.dataMap),
                        language: languageManager.current
                    )
                } header: {
                    Text(t("Data map", "Карта данных"))
                } footer: {
                    Text(t(
                        "This is the same ownership map used by the Mac self-host migration flow. Credential entry stays out of iOS for now.",
                        "Это та же карта владения данными, что используется в Mac-флоу self-host миграции. Ввод серверных доступов пока не переносим в iOS."
                    ))
                }

                ownershipSection(
                    title: t("Owned tables", "Таблицы данных"),
                    entries: exportableTableEntries(in: snapshot.dataMap)
                )

                ownershipSection(
                    title: t("Files", "Файлы"),
                    entries: snapshot.dataMap.artifacts
                )
            }

            if let loadError {
                Section {
                    Text(loadError)
                        .font(Typography.caption)
                        .foregroundStyle(.red)
                        .fixedSize(horizontal: false, vertical: true)
                    Button(t("Retry", "Повторить")) {
                        Task { await loadSnapshot(force: true) }
                    }
                }
            }
        }
        .accessibilityIdentifier("settings-server-data-view")
    }

    private var serverDataRegularLayout: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Spacing.xl) {
                serverDataRegularHeader

                if let snapshot {
                    LazyVGrid(
                        columns: [GridItem(.adaptive(minimum: 320), spacing: Spacing.lg, alignment: .top)],
                        alignment: .leading,
                        spacing: Spacing.lg
                    ) {
                        serverDataRegularOverviewPanel(snapshot)
                        serverDataRegularOwnedPanel(snapshot)
                        serverDataRegularFilesPanel(snapshot)
                    }
                } else if isLoading {
                    dataRegularPanel(
                        title: t("Loading data map", "Загружаем карту данных"),
                        subtitle: nil,
                        systemImage: "arrow.triangle.2.circlepath",
                        identifier: "settings-server-data-loading-panel"
                    ) {
                        HStack(spacing: Spacing.sm) {
                            ProgressView()
                                .controlSize(.small)
                            Text(t("Reading ownership and server status…", "Читаем владение данными и статус сервера…"))
                                .font(Typography.caption)
                                .foregroundStyle(Palette.textTertiary)
                        }
                    }
                }

                if let loadError {
                    dataRegularPanel(
                        title: t("Could not load data map", "Не удалось загрузить карту данных"),
                        subtitle: loadError,
                        systemImage: "exclamationmark.triangle",
                        identifier: "settings-server-data-error-panel"
                    ) {
                        Button(t("Retry", "Повторить")) {
                            Task { await loadSnapshot(force: true) }
                        }
                        .buttonStyle(.borderedProminent)
                    }
                }
            }
            .padding(.horizontal, Spacing.xxl)
            .padding(.vertical, Spacing.xxl)
            .frame(maxWidth: 980, alignment: .topLeading)
            .frame(maxWidth: .infinity, alignment: .top)
        }
        .background(Color(uiColor: .systemGroupedBackground))
        .accessibilityIdentifier("settings-server-data-regular-layout")
    }

    private var serverDataRegularHeader: some View {
        HStack(alignment: .center, spacing: Spacing.md) {
            Image(systemName: "externaldrive.connected.to.line.below")
                .font(.system(size: 18, weight: .semibold))
                .foregroundStyle(Palette.accent)
                .frame(width: 42, height: 42)
                .background(Color(uiColor: .secondarySystemGroupedBackground))
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .strokeBorder(Palette.border, lineWidth: 1)
                )
                .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: Spacing.xs) {
                Text(t("Server & Data", "Сервер и данные"))
                    .font(Typography.displayMedium)
                    .foregroundStyle(Palette.textPrimary)
                Text(t(
                    "See what belongs to you before moving to a server you own.",
                    "Проверьте, какие данные принадлежат вам перед переносом на свой сервер."
                ))
                .font(Typography.bodySmall)
                .foregroundStyle(Palette.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            }
        }
        .accessibilityIdentifier("settings-server-data-regular-header")
    }

    private func serverDataRegularOverviewPanel(_ snapshot: ServerDataSnapshot) -> some View {
        dataRegularPanel(
            title: t("Current Server", "Текущий сервер"),
            subtitle: t(
                "iOS shows the ownership map; server setup remains in the Mac app.",
                "iOS показывает карту владения; настройка сервера остаётся в Mac-приложении."
            ),
            systemImage: "server.rack",
            identifier: "settings-server-data-regular-overview-panel"
        ) {
            VStack(alignment: .leading, spacing: Spacing.md) {
                ServerDataMetricsView(
                    ownedCount: ownershipCount(.ownedExportable, in: snapshot.dataMap),
                    fileCount: snapshot.dataMap.artifacts.count,
                    reconnectCount: reconnectCount(in: snapshot.dataMap),
                    language: languageManager.current
                )

                Divider()

                dataRegularInfoRow(
                    title: t("Current server", "Текущий сервер"),
                    value: serverLabel(snapshot.systemInfo),
                    systemImage: "cloud"
                )
                dataRegularInfoRow(
                    title: t("Audio retention", "Хранение аудио"),
                    value: snapshot.dataMap.audioRetentionPolicy,
                    systemImage: "waveform"
                )
            }
        }
    }

    private func serverDataRegularOwnedPanel(_ snapshot: ServerDataSnapshot) -> some View {
        dataRegularPanel(
            title: t("Owned Tables", "Таблицы данных"),
            subtitle: t(
                "Records that move with your account export.",
                "Записи, которые переезжают вместе с экспортом аккаунта."
            ),
            systemImage: "tablecells",
            identifier: "settings-server-data-regular-owned-panel"
        ) {
            dataRegularOwnershipRows(
                exportableTableEntries(in: snapshot.dataMap),
                emptyText: t("No exportable tables reported.", "Нет экспортируемых таблиц.")
            )
        }
    }

    private func serverDataRegularFilesPanel(_ snapshot: ServerDataSnapshot) -> some View {
        dataRegularPanel(
            title: t("Files", "Файлы"),
            subtitle: t(
                "Audio and other artifacts included or excluded by policy.",
                "Аудио и другие артефакты, включенные или исключённые по политике."
            ),
            systemImage: "folder",
            identifier: "settings-server-data-regular-files-panel"
        ) {
            dataRegularOwnershipRows(
                snapshot.dataMap.artifacts,
                emptyText: t("No file artifacts reported.", "Нет файловых артефактов.")
            )
        }
    }

    @ViewBuilder
    private func ownershipSection(title: String, entries: [OwnershipEntry]) -> some View {
        if !entries.isEmpty {
            Section(title) {
                ForEach(entries) { entry in
                    OwnershipEntryRow(entry: entry)
                }
            }
        }
    }

    @MainActor
    private func loadSnapshot(force: Bool = false) async {
        guard force || snapshot == nil else { return }
        isLoading = true
        loadError = nil
        do {
            snapshot = try await loadServerDataSnapshot(appState: appState)
        } catch {
            loadError = error.userFacingMessage(context: .generic)
        }
        isLoading = false
    }

    private func serverLabel(_ info: SystemInfo) -> String {
        switch info.deploymentMode {
        case .waiCloud:
            return t("Wai Cloud (wai.computer)", "Wai Cloud (wai.computer)")
        case .selfHost:
            return t("My server", "Мой сервер")
        case .provisioning:
            return t("Provisioning", "Настройка")
        }
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

struct ExportReadinessView: View {
    @EnvironmentObject var appState: AppState
    @EnvironmentObject var languageManager: LanguageManager
    @Environment(\.horizontalSizeClass) private var exportHorizontalSizeClass
    @State private var snapshot: ServerDataSnapshot?
    @State private var isLoading = false
    @State private var loadError: String?

    var body: some View {
        Group {
            if exportHorizontalSizeClass == .regular {
                exportRegularLayout
            } else {
                exportCompactList
            }
        }
        .navigationTitle(t("Export Readiness", "Готовность экспорта"))
        .navigationBarTitleDisplayMode(exportHorizontalSizeClass == .regular ? .inline : .large)
        .task { await loadSnapshot() }
        .refreshable { await loadSnapshot(force: true) }
    }

    private var exportCompactList: some View {
        List {
            Section {
                if let snapshot {
                    ServerDataMetricsView(
                        ownedCount: ownershipCount(.ownedExportable, in: snapshot.dataMap),
                        fileCount: snapshot.dataMap.artifacts.count,
                        reconnectCount: reconnectCount(in: snapshot.dataMap),
                        language: languageManager.current
                    )
                } else if isLoading {
                    ProgressView(t("Loading export map…", "Загружаем карту экспорта…"))
                }
            } header: {
                Text(t("Export readiness", "Готовность экспорта"))
            } footer: {
                Text(t(
                    "This screen shows what can move cleanly to a server you own and what needs reconnecting after migration. It does not pretend to export from iOS when no archive writer is available here.",
                    "Этот экран показывает, что можно перенести на свой сервер сразу, а что нужно переподключить после миграции. Он не притворяется экспортом из iOS, пока здесь нет сборщика архива."
                ))
            }

            if let snapshot {
                ownershipSection(
                    title: t("Moves in export", "Переезжает в экспорте"),
                    entries: exportableEntries(in: snapshot.dataMap)
                )
                ownershipSection(
                    title: t("Reconnect after move", "Переподключить после переноса"),
                    entries: reconnectEntries(in: snapshot.dataMap)
                )
                ownershipSection(
                    title: t("Not exported", "Не экспортируется"),
                    entries: nonExportedEntries(in: snapshot.dataMap)
                )
            }

            if let loadError {
                Section {
                    Text(loadError)
                        .font(Typography.caption)
                        .foregroundStyle(.red)
                        .fixedSize(horizontal: false, vertical: true)
                    Button(t("Retry", "Повторить")) {
                        Task { await loadSnapshot(force: true) }
                    }
                }
            }
        }
        .accessibilityIdentifier("settings-export-readiness-view")
    }

    private var exportRegularLayout: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Spacing.xl) {
                exportRegularHeader

                if let snapshot {
                    dataRegularPanel(
                        title: t("Export Readiness", "Готовность экспорта"),
                        subtitle: t(
                            "What moves cleanly, what must be reconnected, and what stays out.",
                            "Что переезжает сразу, что нужно переподключить и что не экспортируется."
                        ),
                        systemImage: "shippingbox",
                        identifier: "settings-export-readiness-regular-summary-panel"
                    ) {
                        VStack(alignment: .leading, spacing: Spacing.md) {
                            ServerDataMetricsView(
                                ownedCount: ownershipCount(.ownedExportable, in: snapshot.dataMap),
                                fileCount: snapshot.dataMap.artifacts.count,
                                reconnectCount: reconnectCount(in: snapshot.dataMap),
                                language: languageManager.current
                            )
                            Text(t(
                                "iOS does not create migration archives yet; this page makes export scope inspectable before you use Mac or web migration tools.",
                                "iOS пока не создаёт архив миграции; эта страница показывает состав экспорта перед использованием Mac или web-инструментов."
                            ))
                            .font(Typography.caption)
                            .foregroundStyle(Palette.textSecondary)
                            .fixedSize(horizontal: false, vertical: true)
                        }
                    }

                    LazyVGrid(
                        columns: [GridItem(.adaptive(minimum: 300), spacing: Spacing.lg, alignment: .top)],
                        alignment: .leading,
                        spacing: Spacing.lg
                    ) {
                        exportRegularOwnershipPanel(
                            title: t("Moves in Export", "Переезжает в экспорте"),
                            subtitle: t("Data and files owned by your account.", "Данные и файлы вашего аккаунта."),
                            systemImage: "checkmark.circle",
                            identifier: "settings-export-readiness-regular-exportable-panel",
                            entries: exportableEntries(in: snapshot.dataMap),
                            emptyText: t("Nothing is marked exportable.", "Ничего не отмечено для экспорта.")
                        )
                        exportRegularOwnershipPanel(
                            title: t("Reconnect After Move", "Переподключить после переноса"),
                            subtitle: t("OAuth grants and linked services are recreated after migration.", "OAuth-доступы и связанные сервисы пересоздаются после миграции."),
                            systemImage: "link.badge.plus",
                            identifier: "settings-export-readiness-regular-reconnect-panel",
                            entries: reconnectEntries(in: snapshot.dataMap),
                            emptyText: t("No reconnect work is listed.", "Нет пунктов для переподключения.")
                        )
                        exportRegularOwnershipPanel(
                            title: t("Not Exported", "Не экспортируется"),
                            subtitle: t("Hosted control plane state and secrets stay out of the archive.", "Состояние hosted control plane и секреты не попадают в архив."),
                            systemImage: "lock.slash",
                            identifier: "settings-export-readiness-regular-excluded-panel",
                            entries: nonExportedEntries(in: snapshot.dataMap),
                            emptyText: t("No excluded entries reported.", "Нет исключённых пунктов.")
                        )
                    }
                } else if isLoading {
                    dataRegularPanel(
                        title: t("Loading export map", "Загружаем карту экспорта"),
                        subtitle: nil,
                        systemImage: "arrow.triangle.2.circlepath",
                        identifier: "settings-export-readiness-loading-panel"
                    ) {
                        HStack(spacing: Spacing.sm) {
                            ProgressView()
                                .controlSize(.small)
                            Text(t("Reading migration ownership data…", "Читаем данные владения для миграции…"))
                                .font(Typography.caption)
                                .foregroundStyle(Palette.textTertiary)
                        }
                    }
                }

                if let loadError {
                    dataRegularPanel(
                        title: t("Could not load export map", "Не удалось загрузить карту экспорта"),
                        subtitle: loadError,
                        systemImage: "exclamationmark.triangle",
                        identifier: "settings-export-readiness-error-panel"
                    ) {
                        Button(t("Retry", "Повторить")) {
                            Task { await loadSnapshot(force: true) }
                        }
                        .buttonStyle(.borderedProminent)
                    }
                }
            }
            .padding(.horizontal, Spacing.xxl)
            .padding(.vertical, Spacing.xxl)
            .frame(maxWidth: 980, alignment: .topLeading)
            .frame(maxWidth: .infinity, alignment: .top)
        }
        .background(Color(uiColor: .systemGroupedBackground))
        .accessibilityIdentifier("settings-export-readiness-regular-layout")
    }

    private var exportRegularHeader: some View {
        HStack(alignment: .center, spacing: Spacing.md) {
            Image(systemName: "shippingbox")
                .font(.system(size: 18, weight: .semibold))
                .foregroundStyle(Palette.accent)
                .frame(width: 42, height: 42)
                .background(Color(uiColor: .secondarySystemGroupedBackground))
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .strokeBorder(Palette.border, lineWidth: 1)
                )
                .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: Spacing.xs) {
                Text(t("Export Readiness", "Готовность экспорта"))
                    .font(Typography.displayMedium)
                    .foregroundStyle(Palette.textPrimary)
                Text(t(
                    "Review migration scope without pretending iOS can create the archive.",
                    "Проверьте состав миграции без имитации создания архива на iOS."
                ))
                .font(Typography.bodySmall)
                .foregroundStyle(Palette.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
            }
        }
        .accessibilityIdentifier("settings-export-readiness-regular-header")
    }

    private func exportRegularOwnershipPanel(
        title: String,
        subtitle: String,
        systemImage: String,
        identifier: String,
        entries: [OwnershipEntry],
        emptyText: String
    ) -> some View {
        dataRegularPanel(
            title: title,
            subtitle: subtitle,
            systemImage: systemImage,
            identifier: identifier
        ) {
            dataRegularOwnershipRows(entries, emptyText: emptyText)
        }
    }

    @ViewBuilder
    private func ownershipSection(title: String, entries: [OwnershipEntry]) -> some View {
        if !entries.isEmpty {
            Section(title) {
                ForEach(entries) { entry in
                    OwnershipEntryRow(entry: entry)
                }
            }
        }
    }

    @MainActor
    private func loadSnapshot(force: Bool = false) async {
        guard force || snapshot == nil else { return }
        isLoading = true
        loadError = nil
        do {
            snapshot = try await loadServerDataSnapshot(appState: appState)
        } catch {
            loadError = error.userFacingMessage(context: .generic)
        }
        isLoading = false
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

private func dataRegularPanel<Content: View>(
    title: String,
    subtitle: String?,
    systemImage: String,
    identifier: String,
    @ViewBuilder content: () -> Content
) -> some View {
    VStack(alignment: .leading, spacing: Spacing.md) {
        HStack(alignment: .top, spacing: Spacing.md) {
            Image(systemName: systemImage)
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(Palette.accent)
                .frame(width: 30, height: 30)
                .background(Palette.accentSubtle)
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: Spacing.xs) {
                Text(title)
                    .font(Typography.headingLarge)
                    .foregroundStyle(Palette.textPrimary)
                if let subtitle {
                    Text(subtitle)
                        .font(Typography.caption)
                        .foregroundStyle(Palette.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }

        Divider()
        content()
    }
    .padding(Spacing.lg)
    .frame(maxWidth: .infinity, alignment: .topLeading)
    .background(Color(uiColor: .secondarySystemGroupedBackground))
    .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    .overlay(
        RoundedRectangle(cornerRadius: 8, style: .continuous)
            .strokeBorder(Palette.border, lineWidth: 1)
    )
    .accessibilityIdentifier(identifier)
}

private func dataRegularInfoRow(
    title: String,
    value: String,
    systemImage: String
) -> some View {
    HStack(alignment: .top, spacing: Spacing.sm) {
        Image(systemName: systemImage)
            .font(.system(size: 14, weight: .semibold))
            .foregroundStyle(Palette.accent)
            .frame(width: 24, height: 24)
            .accessibilityHidden(true)

        VStack(alignment: .leading, spacing: Spacing.xxs) {
            Text(title)
                .font(Typography.caption)
                .foregroundStyle(Palette.textTertiary)
            Text(value)
                .font(Typography.body)
                .foregroundStyle(Palette.textPrimary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}

@ViewBuilder
private func dataRegularOwnershipRows(
    _ entries: [OwnershipEntry],
    emptyText: String
) -> some View {
    if entries.isEmpty {
        Text(emptyText)
            .font(Typography.caption)
            .foregroundStyle(Palette.textTertiary)
            .fixedSize(horizontal: false, vertical: true)
    } else {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            ForEach(entries) { entry in
                OwnershipEntryRow(entry: entry)
                if entry.id != entries.last?.id {
                    Divider()
                }
            }
        }
    }
}

private struct ServerDataSnapshot {
    let systemInfo: SystemInfo
    let dataMap: DataOwnershipMap
}

private struct ServerDataMetricsView: View {
    let ownedCount: Int
    let fileCount: Int
    let reconnectCount: Int
    let language: LanguageManager.SupportedLanguage

    var body: some View {
        HStack(spacing: Spacing.md) {
            metric(value: "\(ownedCount)", label: t("Owned data", "Ваши данные"))
            metric(value: "\(fileCount)", label: t("Files", "Файлы"))
            metric(value: "\(reconnectCount)", label: t("Reconnect", "Переподключить"))
        }
        .padding(.vertical, Spacing.xs)
        .accessibilityIdentifier("settings-server-data-metrics")
    }

    private func metric(value: String, label: String) -> some View {
        VStack(alignment: .leading, spacing: Spacing.xxs) {
            Text(value)
                .font(Typography.headingLarge)
                .foregroundStyle(Palette.textPrimary)
            Text(label)
                .font(Typography.caption)
                .foregroundStyle(Palette.textSecondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: language)
    }
}

private struct OwnershipEntryRow: View {
    let entry: OwnershipEntry

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.xxs) {
            HStack(spacing: Spacing.sm) {
                Text(entry.name)
                    .font(Typography.body)
                    .foregroundStyle(Palette.textPrimary)
                    .lineLimit(1)
                    .minimumScaleFactor(0.82)
                Spacer()
                classificationBadge
            }

            Text(entry.reason)
                .font(Typography.caption)
                .foregroundStyle(Palette.textSecondary)
                .fixedSize(horizontal: false, vertical: true)

            if let pathHint = entry.pathHint, !pathHint.isEmpty {
                Text(pathHint)
                    .font(Typography.caption.monospaced())
                    .foregroundStyle(Palette.textTertiary)
                    .lineLimit(1)
                    .truncationMode(.middle)
            }
        }
        .padding(.vertical, Spacing.xxs)
    }

    private var classificationBadge: some View {
        Text(entry.classification.rawValue.replacingOccurrences(of: "_", with: " "))
            .font(.system(size: 9, weight: .semibold, design: .monospaced))
            .foregroundStyle(classificationColor)
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(classificationColor.opacity(0.12))
            .clipShape(RoundedRectangle(cornerRadius: 4, style: .continuous))
    }

    private var classificationColor: Color {
        switch entry.classification {
        case .ownedExportable:
            return Palette.accent
        case .reconnectRequired:
            return .orange
        case .selfHostLocal:
            return .green
        case .hostedControlPlane, .excludedWithReason:
            return Palette.textTertiary
        }
    }
}

@MainActor
private func loadServerDataSnapshot(appState: AppState) async throws -> ServerDataSnapshot {
    #if DEBUG
    if IOSTestingMode.current.isScreenshot {
        return IOSServerDataFixtures.snapshot
    }
    #endif

    let client = appState.getAPIClient()
    async let info = client.getSystemInfo()
    async let dataMap = client.getDataOwnershipMap()
    return try await ServerDataSnapshot(systemInfo: info, dataMap: dataMap)
}

private func ownershipCount(_ classification: OwnershipClassification, in map: DataOwnershipMap) -> Int {
    allOwnershipEntries(in: map).filter { $0.classification == classification }.count
}

private func reconnectCount(in map: DataOwnershipMap) -> Int {
    allOwnershipEntries(in: map).filter { $0.requiresReconnect || $0.classification == .reconnectRequired }.count
}

private func exportableEntries(in map: DataOwnershipMap) -> [OwnershipEntry] {
    allOwnershipEntries(in: map).filter { $0.classification == .ownedExportable }
}

private func exportableTableEntries(in map: DataOwnershipMap) -> [OwnershipEntry] {
    map.tables.filter { $0.classification == .ownedExportable }
}

private func reconnectEntries(in map: DataOwnershipMap) -> [OwnershipEntry] {
    allOwnershipEntries(in: map).filter { $0.classification == .reconnectRequired }
}

private func nonExportedEntries(in map: DataOwnershipMap) -> [OwnershipEntry] {
    allOwnershipEntries(in: map).filter {
        $0.classification == .hostedControlPlane
            || $0.classification == .excludedWithReason
            || $0.classification == .selfHostLocal
    }
}

private func allOwnershipEntries(in map: DataOwnershipMap) -> [OwnershipEntry] {
    map.tables + map.artifacts
}

#if DEBUG
private enum IOSServerDataFixtures {
    static let snapshot = ServerDataSnapshot(
        systemInfo: SystemInfo(
            appName: "WaiComputer",
            deploymentMode: .waiCloud,
            publicBaseURL: "https://wai.computer",
            cloudBaseURL: "https://wai.computer",
            mcpURL: "https://wai.computer/mcp",
            gitSHA: "ios-fixture",
            gitDirty: false,
            audioRetentionPolicy: "Original audio stays available until you delete it.",
            selfHostingAvailable: true,
            billingMode: "cloud"
        ),
        dataMap: DataOwnershipMap(
            audioRetentionPolicy: "Original audio stays available until you delete it.",
            tables: [
                OwnershipEntry(
                    name: "recordings",
                    table: "recordings",
                    classification: .ownedExportable,
                    reason: "Recordings, transcripts, summaries, and speakers belong to your account.",
                    containsUserContent: true,
                    requiresReconnect: false,
                    pathHint: nil
                ),
                OwnershipEntry(
                    name: "captured_items",
                    table: "items",
                    classification: .ownedExportable,
                    reason: "Saved notes, URLs, uploads, and generated summaries move with you.",
                    containsUserContent: true,
                    requiresReconnect: false,
                    pathHint: nil
                ),
                OwnershipEntry(
                    name: "oauth_connections",
                    table: "oauth_connections",
                    classification: .reconnectRequired,
                    reason: "OAuth grants are recreated on the destination server.",
                    containsUserContent: false,
                    requiresReconnect: true,
                    pathHint: nil
                ),
            ],
            artifacts: [
                OwnershipEntry(
                    name: "recording_audio",
                    table: nil,
                    classification: .ownedExportable,
                    reason: "Uploaded audio artifacts are included in the migration archive.",
                    containsUserContent: true,
                    requiresReconnect: false,
                    pathHint: "recordings/audio/"
                ),
                OwnershipEntry(
                    name: "provider_tokens",
                    table: nil,
                    classification: .excludedWithReason,
                    reason: "Provider secrets stay server-side and must be configured again.",
                    containsUserContent: false,
                    requiresReconnect: true,
                    pathHint: nil
                ),
            ]
        )
    )
}
#endif

struct BillingSettingsView: View {
    @EnvironmentObject var languageManager: LanguageManager

    var body: some View {
        List {
            BillingStatusSection()
        }
        .navigationTitle(t("Subscription", "Подписка"))
        .navigationBarTitleDisplayMode(.inline)
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

#Preview {
    SettingsView()
        .environmentObject(AppState())
        .environmentObject(LanguageManager.shared)
        .environmentObject(DictationLanguageStore())
        .environmentObject(DictationHistoryStore())
        .environmentObject(DictationDictionaryStore())
}
