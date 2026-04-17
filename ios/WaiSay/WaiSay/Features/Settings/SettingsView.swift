import SwiftUI
import WaiSayKit

struct SettingsView: View {
    @EnvironmentObject var appState: AppState
    @State private var showingLogoutConfirmation = false

    private var isScreenshotMode: Bool {
        IOSTestingMode.current.isScreenshot
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

                if !isScreenshotMode {
                    // About section
                    Section("About") {
                        HStack {
                            Text("Version")
                            Spacer()
                            Text("1.0.0")
                                .foregroundStyle(.secondary)
                        }

                        Link(destination: URL(string: "https://waisay.com/privacy")!) {
                            Label("Privacy Policy", systemImage: "lock.shield")
                        }

                        Link(destination: URL(string: "https://waisay.com/terms")!) {
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
    @AppStorage("transcriptionLanguage") private var language = "multi"
    @AppStorage("enableDiarization") private var enableDiarization = true

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
        }
        .navigationTitle("Transcription")
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
