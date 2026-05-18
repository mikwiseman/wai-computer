import SwiftUI
import WaiComputerKit

struct SettingsView: View {
    @EnvironmentObject var appState: AppState
    @State private var showingLogoutConfirmation = false
    @State private var showingDeleteAccountConfirmation = false
    @State private var isDeletingAccount = false
    @State private var deleteAccountError: String?

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
                Section("Account") {
                    if let user = appState.currentUser {
                        HStack {
                            Image(systemName: "person.circle.fill")
                                .font(.largeTitle)
                                .foregroundStyle(.blue)

                            VStack(alignment: .leading, spacing: 4) {
                                Text(user.email)
                                    .font(.headline)
                                    .lineLimit(1)
                                    .minimumScaleFactor(0.82)
                                Text("Member since \(user.createdAt.formatted(date: .abbreviated, time: .omitted))")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                        .padding(.vertical, 4)
                    }
                }

                // Recording settings
                Section("Recording") {
                    NavigationLink(destination: AudioSettingsView()) {
                        Label("Audio Settings", systemImage: "waveform")
                    }

                    NavigationLink(destination: TranscriptionSettingsView()) {
                        Label("Transcription", systemImage: "text.bubble")
                    }

                    NavigationLink(destination: SummarySettingsView()) {
                        Label("AI Summary", systemImage: "sparkles")
                    }
                }

                // Data section
                Section("Data") {
                    NavigationLink(destination: StorageView()) {
                        Label("Storage", systemImage: "internaldrive")
                    }

                    NavigationLink(destination: ExportView()) {
                        Label("Export Data", systemImage: "square.and.arrow.up")
                    }
                }

                // Integrations section
                Section("Integrations") {
                    NavigationLink(destination: McpConnectView()) {
                        Label("MCP", systemImage: "link.circle")
                    }
                }

                if !isScreenshotMode {
                    // About section
                    Section("About") {
                        HStack {
                            Text("Version")
                            Spacer()
                            Text(appVersionDisplay)
                                .foregroundStyle(.secondary)
                        }

                        Link(destination: Self.privacyPolicyURL) {
                            Label("Privacy Policy", systemImage: "lock.shield")
                        }

                        Link(destination: Self.termsOfServiceURL) {
                            Label("Terms of Service", systemImage: "doc.text")
                        }
                    }

                    // Logout
                    Section {
                        Button(role: .destructive) {
                            showingLogoutConfirmation = true
                        } label: {
                            Label("Logout", systemImage: "rectangle.portrait.and.arrow.right")
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
                                Label("Delete Account", systemImage: "trash")
                                if isDeletingAccount {
                                    Spacer()
                                    ProgressView()
                                }
                            }
                        }
                        .disabled(isDeletingAccount)
                        .accessibilityIdentifier("delete-account-button")
                    } header: {
                        Text("Danger zone")
                    } footer: {
                        Text("Permanently removes your account, recordings, transcripts, and summaries from WaiComputer. This cannot be undone.")
                    }
                }
            }
            .navigationTitle("Settings")
            .confirmationDialog("Logout", isPresented: $showingLogoutConfirmation) {
                Button("Logout", role: .destructive) {
                    Task {
                        await appState.logout()
                    }
                }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("Are you sure you want to logout?")
            }
            .alert("Delete account?", isPresented: $showingDeleteAccountConfirmation) {
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
    @State private var transcriptionOptions: TranscriptionOptions?
    @State private var dictationLiveSTTSelection = ""
    @State private var recordingLiveSTTSelection = ""
    @State private var fileSTTSelection = ""
    @State private var dictationPostFilterEnabled = true
    @State private var dictationPostFilterSelection = ""

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

            Section("Models") {
                if let transcriptionOptions {
                    transcriptionModelPicker(
                        "Dictation live",
                        selection: $dictationLiveSTTSelection,
                        options: transcriptionOptions.dictationLiveSTT,
                        save: { await saveDictationLiveSTT(selection: $0) }
                    )
                    transcriptionModelPicker(
                        "Recording live",
                        selection: $recordingLiveSTTSelection,
                        options: transcriptionOptions.recordingLiveSTT,
                        save: { await saveRecordingLiveSTT(selection: $0) }
                    )
                    transcriptionModelPicker(
                        "Full session",
                        selection: $fileSTTSelection,
                        options: transcriptionOptions.fileSTT,
                        save: { await saveFileSTT(selection: $0) }
                    )
                } else if let settingsError {
                    Text(settingsError)
                        .foregroundStyle(.red)
                } else {
                    ProgressView()
                }
            }

            Section("Dictation post-filter") {
                Toggle("Enabled", isOn: $dictationPostFilterEnabled)
                    .onChange(of: dictationPostFilterEnabled) { _, enabled in
                        guard settingsLoaded else { return }
                        Task { await saveDictationPostFilterEnabled(enabled) }
                    }

                if let transcriptionOptions, dictationPostFilterEnabled {
                    transcriptionModelPicker(
                        "Model",
                        selection: $dictationPostFilterSelection,
                        options: transcriptionOptions.dictationPostFilter,
                        save: { await saveDictationPostFilter(selection: $0) }
                    )
                }

                if let settingsError, transcriptionOptions != nil {
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

    @ViewBuilder
    private func transcriptionModelPicker(
        _ title: String,
        selection: Binding<String>,
        options: [TranscriptionModelOption],
        save: @escaping (String) async -> Void
    ) -> some View {
        Picker(title, selection: selection) {
            ForEach(options) { option in
                Text(option.label).tag(option.id)
            }
        }
        .disabled(options.isEmpty)
        .onChange(of: selection.wrappedValue) { _, newValue in
            guard settingsLoaded else { return }
            Task { await save(newValue) }
        }

        if let description = options.first(where: { $0.id == selection.wrappedValue })?.description {
            Text(description)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    private func splitSelection(_ selection: String) -> (provider: String, model: String)? {
        let parts = selection.split(separator: ":", maxSplits: 1, omittingEmptySubsequences: false)
        guard parts.count == 2, !parts[0].isEmpty, !parts[1].isEmpty else { return nil }
        return (String(parts[0]), String(parts[1]))
    }

    private func applySettings(_ settings: UserSettings) {
        dictationLiveSTTSelection = "\(settings.dictationLiveSTTProvider):\(settings.dictationLiveSTTModel)"
        recordingLiveSTTSelection = "\(settings.recordingLiveSTTProvider):\(settings.recordingLiveSTTModel)"
        fileSTTSelection = "\(settings.fileSTTProvider):\(settings.fileSTTModel)"
        dictationPostFilterEnabled = settings.dictationPostFilterEnabled
        dictationPostFilterSelection = "\(settings.dictationPostFilterProvider):\(settings.dictationPostFilterModel)"
    }

    private func loadSettings() async {
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

        do {
            transcriptionOptions = try await appState.getAPIClient().getTranscriptionOptions()
            settingsError = nil
        } catch {
            settingsError = "Couldn't load transcription model options: \(error.localizedDescription)"
        }
    }

    private func saveDictationLiveSTT(selection: String) async {
        guard let pair = splitSelection(selection) else { return }
        await saveTranscriptionSettings(
            UpdateSettingsRequest(
                dictationLiveSTTProvider: pair.provider,
                dictationLiveSTTModel: pair.model
            )
        )
    }

    private func saveRecordingLiveSTT(selection: String) async {
        guard let pair = splitSelection(selection) else { return }
        await saveTranscriptionSettings(
            UpdateSettingsRequest(
                recordingLiveSTTProvider: pair.provider,
                recordingLiveSTTModel: pair.model
            )
        )
    }

    private func saveFileSTT(selection: String) async {
        guard let pair = splitSelection(selection) else { return }
        await saveTranscriptionSettings(
            UpdateSettingsRequest(
                fileSTTProvider: pair.provider,
                fileSTTModel: pair.model
            )
        )
    }

    private func saveDictationPostFilterEnabled(_ enabled: Bool) async {
        await saveTranscriptionSettings(UpdateSettingsRequest(dictationPostFilterEnabled: enabled))
    }

    private func saveDictationPostFilter(selection: String) async {
        guard let pair = splitSelection(selection) else { return }
        await saveTranscriptionSettings(
            UpdateSettingsRequest(
                dictationPostFilterProvider: pair.provider,
                dictationPostFilterModel: pair.model
            )
        )
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
}
