import SwiftUI
import WaiComputerKit

struct SettingsView: View {
    @EnvironmentObject var appState: AppState
    @State private var showingLogoutConfirmation = false

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

                            VStack(alignment: .leading) {
                                Text(user.email)
                                    .font(.headline)
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

                // About section
                Section("About") {
                    HStack {
                        Text("Version")
                        Spacer()
                        Text("1.0.0")
                            .foregroundStyle(.secondary)
                    }

                    Link(destination: URL(string: "https://waicomputer.com/privacy")!) {
                        Label("Privacy Policy", systemImage: "lock.shield")
                    }

                    Link(destination: URL(string: "https://waicomputer.com/terms")!) {
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
    @AppStorage("autoSummarize") private var autoSummarize = true
    @AppStorage("summaryLength") private var summaryLength = "medium"

    var body: some View {
        List {
            Section("Automation") {
                Toggle("Auto-summarize recordings", isOn: $autoSummarize)
            }

            Section("Preferences") {
                Picker("Summary Length", selection: $summaryLength) {
                    Text("Brief").tag("brief")
                    Text("Medium").tag("medium")
                    Text("Detailed").tag("detailed")
                }
            }
        }
        .navigationTitle("AI Summary")
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
