import AVFoundation
import SwiftUI
import UIKit
import WaiComputerKit

struct SettingsView: View {
    @EnvironmentObject var appState: AppState
    @EnvironmentObject var languageManager: LanguageManager
    @Environment(\.scenePhase) private var scenePhase
    @State private var showingLogoutConfirmation = false
    @State private var showingDeleteAccountConfirmation = false
    @State private var isDeletingAccount = false
    @State private var deleteAccountError: String?
    @State private var micPermission = AVAudioApplication.shared.recordPermission

    // Server-synced dictation stores. Owned here so the lifecycle (attach +
    // hydrate on login, clearLocalCache on logout) is self-contained on iOS.
    @StateObject private var dictationLanguageStore = DictationLanguageStore()
    @StateObject private var historyStore = DictationHistoryStore()
    @StateObject private var dictionaryStore = DictationDictionaryStore()

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

    var body: some View {
        NavigationStack {
            List {
                // Account section
                Section(t("Account", "Аккаунт")) {
                    if let user = appState.currentUser {
                        HStack {
                            Image(systemName: "person.circle.fill")
                                .font(.largeTitle)
                                .foregroundStyle(Palette.accent)

                            VStack(alignment: .leading, spacing: 4) {
                                Text(user.email)
                                    .font(.headline)
                                    .lineLimit(1)
                                    .minimumScaleFactor(0.82)
                                Text(memberSinceText(user.createdAt))
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                        .padding(.vertical, 4)
                    }
                }

                // Read-only subscription status (plan, usage, renewal, cancel).
                // No in-app upgrade button — iOS billing is read-only. Skipped
                // in screenshot mode (no live backend behind the fake session).
                if !isScreenshotMode {
                    BillingStatusSection()
                }

                // Appearance + language
                Section(t("Appearance", "Внешний вид")) {
                    NavigationLink(destination: AppearanceSettingsView()) {
                        Label(t("Appearance", "Внешний вид"), systemImage: "paintpalette")
                    }
                    AppLanguagePicker()
                }

                // Recording settings
                Section(t("Recording", "Запись")) {
                    NavigationLink(destination: AudioSettingsView()) {
                        Label(t("Audio Settings", "Настройки звука"), systemImage: "waveform")
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
                }

                // Microphone permission status (iOS-native).
                Section(t("Permissions", "Разрешения")) {
                    microphonePermissionRow
                }

                // Data section
                Section(t("Data", "Данные")) {
                    NavigationLink(destination: StorageView()) {
                        Label(t("Storage", "Хранилище"), systemImage: "internaldrive")
                    }

                    NavigationLink(destination: ExportView()) {
                        Label(t("Export Data", "Экспорт данных"), systemImage: "square.and.arrow.up")
                    }
                }

                // Integrations section
                Section(t("Integrations", "Интеграции")) {
                    NavigationLink(destination: TelegramSettingsView()) {
                        Label("Telegram", systemImage: "paperplane")
                    }

                    NavigationLink(destination: McpConnectView()) {
                        Label("MCP", systemImage: "link.circle")
                    }

                    NavigationLink(destination: McpIngestionView()) {
                        Label(t("Data sources", "Источники данных"), systemImage: "square.stack.3d.down.right")
                    }
                }

                if !isScreenshotMode {
                    // About section
                    Section(t("About", "О приложении")) {
                        HStack {
                            Text(t("Version", "Версия"))
                            Spacer()
                            Text(appVersionDisplay)
                                .foregroundStyle(.secondary)
                        }

                        Link(destination: Self.privacyPolicyURL) {
                            Label(t("Privacy Policy", "Политика конфиденциальности"), systemImage: "lock.shield")
                        }

                        Link(destination: Self.termsOfServiceURL) {
                            Label(t("Terms of Service", "Условия использования"), systemImage: "doc.text")
                        }
                    }

                    // Logout
                    Section {
                        Button(role: .destructive) {
                            showingLogoutConfirmation = true
                        } label: {
                            Label(t("Log Out", "Выйти"), systemImage: "rectangle.portrait.and.arrow.right")
                        }
                    }

                    // Danger zone: permanent account deletion.
                    // Required by App Store guideline 5.1.1(v): apps that
                    // support account creation must also offer in-app account
                    // deletion.
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
            .navigationTitle(t("Settings", "Настройки"))
            .environmentObject(dictationLanguageStore)
            .environmentObject(historyStore)
            .environmentObject(dictionaryStore)
            .task { await attachAndHydrateStores() }
            .onChange(of: appState.isAuthenticated) { _, authenticated in
                if authenticated {
                    Task { await attachAndHydrateStores() }
                } else {
                    // Logout / auth failure — drop local caches so the next
                    // login re-hydrates from the server for the right account.
                    historyStore.clearLocalCache()
                    dictionaryStore.clearLocalCache()
                }
            }
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

    // MARK: - Dictation sub-screens

    /// Single-language transcription picker, shared with Recording via the
    /// legacy `transcriptionLanguage` UserDefaults mirror.
    private var dictationLanguageScreen: some View {
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
        .navigationTitle(t("Transcription Language", "Язык расшифровки"))
        .navigationBarTitleDisplayMode(.inline)
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

    private func attachAndHydrateStores() async {
        guard appState.isAuthenticated else { return }
        let client = appState.getAPIClient()
        historyStore.attach(apiClient: client)
        dictionaryStore.attach(apiClient: client)
        await historyStore.hydrate()
        await dictionaryStore.hydrate()
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

// Placeholder views for settings sub-screens
struct AudioSettingsView: View {
    @AppStorage("audioSampleRate") private var sampleRate = 16000
    @AppStorage("enableNoiseSuppression") private var enableNoiseSuppression = true

    var body: some View {
        List {
            Section("Quality") {
                Picker("Sample Rate", selection: $sampleRate) {
                    Text("16 kHz").tag(16000)
                    Text("44.1 kHz").tag(44100)
                    Text("48 kHz").tag(48000)
                }
            }

            Section("Processing") {
                Toggle("Noise Suppression", isOn: $enableNoiseSuppression)
            }
        }
        .navigationTitle("Audio Settings")
    }
}

struct TranscriptionSettingsView: View {
    @EnvironmentObject var appState: AppState
    @AppStorage("transcriptionLanguage") private var language = "multi"
    @AppStorage("enableDiarization") private var enableDiarization = true
    @State private var settingsLoaded = false
    @State private var settingsError: String?
    @State private var dictationPostFilterEnabled = true

    private let languageOptions: [(label: String, value: String)] = [
        ("Auto-detect (Multi-language)", "multi"),
        ("English", "en"),
        ("Russian", "ru"),
        ("Spanish", "es"),
        ("German", "de"),
        ("French", "fr"),
        ("Japanese", "ja"),
    ]

    var body: some View {
        List {
            Section("Language") {
                Picker("Primary Language", selection: $language) {
                    ForEach(languageOptions, id: \.value) { option in
                        Text(option.label).tag(option.value)
                    }
                }
            }

            Section("Features") {
                Toggle("Speaker Diarization", isOn: $enableDiarization)
            }

            Section("Dictation post-filter") {
                Toggle("Enabled", isOn: $dictationPostFilterEnabled)
                    .onChange(of: dictationPostFilterEnabled) { _, enabled in
                        guard settingsLoaded else { return }
                        Task { await saveDictationPostFilterEnabled(enabled) }
                    }

                if let settingsError {
                    Text(settingsError)
                        .font(.caption)
                        .foregroundStyle(.red)
                }
            }
        }
        .navigationTitle("Transcription")
        .task {
            await loadSettings()
        }
    }

    private func applySettings(_ settings: UserSettings) {
        dictationPostFilterEnabled = settings.dictationPostFilterEnabled
    }

    private func loadSettings() async {
        guard !settingsLoaded else { return }
        do {
            let settings = try await appState.getAPIClient().getSettings()
            applySettings(settings)
            settingsError = nil
            settingsLoaded = true
        } catch {
            settingsError = "Couldn't load account settings: \(error.localizedDescription)"
            return
        }
    }

    private func saveDictationPostFilterEnabled(_ enabled: Bool) async {
        await saveTranscriptionSettings(UpdateSettingsRequest(dictationPostFilterEnabled: enabled))
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
}

struct SummarySettingsView: View {
    @EnvironmentObject var appState: AppState
    @AppStorage("autoSummarize") private var autoSummarize = true
    @State private var summaryLanguage = "auto"
    @State private var summaryStyle = "medium"
    @State private var summaryInstructions = ""
    @State private var settingsLoaded = false

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

    var body: some View {
        List {
            Section("Automation") {
                Toggle("Auto-summarize recordings", isOn: $autoSummarize)
            }

            Section("Language") {
                Picker("Summary Language", selection: $summaryLanguage) {
                    ForEach(summaryLanguageOptions, id: \.value) { option in
                        Text(option.label).tag(option.value)
                    }
                }
                .onChange(of: summaryLanguage) { _, newValue in
                    Task { await saveSettings(language: newValue) }
                }
            }

            Section("Detail Level") {
                Picker("Summary Style", selection: $summaryStyle) {
                    Text("Brief").tag("brief")
                    Text("Medium").tag("medium")
                    Text("Detailed").tag("detailed")
                }
                .onChange(of: summaryStyle) { _, newValue in
                    Task { await saveSettings(style: newValue) }
                }
            }

            Section("Custom Instructions") {
                TextField("E.g. \"Focus on action items\"", text: $summaryInstructions, axis: .vertical)
                    .lineLimit(2...4)
                    .onChange(of: summaryInstructions) { _, _ in
                        Task { await saveSettings(instructions: summaryInstructions) }
                    }
            }
        }
        .navigationTitle("AI Summary")
        .task {
            await loadSettings()
        }
    }

    private func loadSettings() async {
        guard !settingsLoaded else { return }
        do {
            let settings = try await appState.getAPIClient().getSettings()
            summaryLanguage = settings.summaryLanguage
            summaryStyle = settings.summaryStyle
            summaryInstructions = settings.summaryInstructions ?? ""
            settingsLoaded = true
        } catch {
            // Use defaults
        }
    }

    private func saveSettings(
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

struct StorageView: View {
    var body: some View {
        List {
            Section("Usage") {
                HStack {
                    Text("Local Storage")
                    Spacer()
                    Text("125 MB")
                        .foregroundStyle(.secondary)
                }
                HStack {
                    Text("Cloud Storage")
                    Spacer()
                    Text("2.3 GB")
                        .foregroundStyle(.secondary)
                }
            }

            Section {
                Button("Clear Local Cache") {
                    // Clear cache
                }
            }
        }
        .navigationTitle("Storage")
    }
}

struct ExportView: View {
    var body: some View {
        List {
            Section("Export Options") {
                Button("Export All Transcripts (TXT)") {}
                Button("Export All Transcripts (JSON)") {}
                Button("Export All Audio (ZIP)") {}
            }
        }
        .navigationTitle("Export Data")
    }
}

#Preview {
    SettingsView()
        .environmentObject(AppState())
        .environmentObject(LanguageManager.shared)
}
