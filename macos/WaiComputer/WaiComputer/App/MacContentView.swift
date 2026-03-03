import SwiftUI
import WaiComputerKit

struct MacContentView: View {
    @EnvironmentObject var appState: MacAppState

    var body: some View {
        Group {
            if appState.isCheckingAuth {
                ProgressView("Loading...")
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if appState.isAuthenticated {
                MacMainView()
            } else {
                MacAuthView()
            }
        }
    }
}

// MARK: - Main View

struct MacMainView: View {
    @EnvironmentObject var appState: MacAppState
    @StateObject private var libraryViewModel = MacLibraryViewModel()
    @State private var selectedSection: SidebarSection = .allRecordings
    @State private var selectedRecordingId: String?
    @State private var columnVisibility: NavigationSplitViewVisibility = .all

    enum SidebarSection: Hashable {
        // Library sections (show middle column)
        case allRecordings
        case meetings
        case notes
        case reflections
        // Tool sections (hide middle column, full-width detail)
        case chat
        case search
        case settings
    }

    /// Whether the current section has a list (middle) column
    private var hasListColumn: Bool {
        switch selectedSection {
        case .allRecordings, .meetings, .notes, .reflections:
            return true
        case .chat, .search, .settings:
            return false
        }
    }

    /// The recording type filter for the current section
    private var currentTypeFilter: RecordingType? {
        switch selectedSection {
        case .meetings: return .meeting
        case .notes: return .note
        case .reflections: return .reflection
        default: return nil
        }
    }

    var body: some View {
        NavigationSplitView(columnVisibility: $columnVisibility) {
            sidebar
                .navigationSplitViewColumnWidth(min: 180, ideal: 200, max: 240)
        } content: {
            if hasListColumn {
                listColumn
                    .navigationSplitViewColumnWidth(min: 220, ideal: 280, max: 360)
            } else {
                // For tool sections, show an empty content column (collapsed)
                EmptyView()
                    .navigationSplitViewColumnWidth(0)
            }
        } detail: {
            detailColumn
        }
        .toolbar {
            ToolbarItemGroup(placement: .primaryAction) {
                Menu {
                    Button("New Meeting") {
                        startRecording(type: .meeting)
                    }
                    Button("New Note") {
                        startRecording(type: .note)
                    }
                    Button("New Reflection") {
                        startRecording(type: .reflection)
                    }
                } label: {
                    Label("New Recording", systemImage: "plus")
                }
                .disabled(appState.isRecording)
            }
        }
        .task {
            await libraryViewModel.loadRecordings(apiClient: appState.getAPIClient())
        }
    }

    // MARK: - Sidebar

    private var sidebar: some View {
        List(selection: $selectedSection) {
            Section("Library") {
                Label("All Recordings", systemImage: "folder.fill")
                    .tag(SidebarSection.allRecordings)

                Label("Meetings", systemImage: "person.2.fill")
                    .tag(SidebarSection.meetings)

                Label("Notes", systemImage: "note.text")
                    .tag(SidebarSection.notes)

                Label("Reflections", systemImage: "brain.head.profile")
                    .tag(SidebarSection.reflections)
            }

            Section("Tools") {
                Label("Chat", systemImage: "bubble.left.and.bubble.right.fill")
                    .tag(SidebarSection.chat)

                Label("Search", systemImage: "magnifyingglass")
                    .tag(SidebarSection.search)

                Label("Settings", systemImage: "gear")
                    .tag(SidebarSection.settings)
            }
        }
        .listStyle(.sidebar)
    }

    // MARK: - List Column

    private var listColumn: some View {
        let filtered = libraryViewModel.filteredRecordings(for: currentTypeFilter)

        return Group {
            if libraryViewModel.isLoading {
                ProgressView()
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if filtered.isEmpty {
                ContentUnavailableView(
                    "No Recordings",
                    systemImage: "waveform",
                    description: Text("Start a recording to see it here.")
                )
            } else {
                RecordingListView(
                    recordings: filtered,
                    selectedRecordingId: $selectedRecordingId,
                    onDelete: { id in
                        Task {
                            await libraryViewModel.deleteRecording(id: id, apiClient: appState.getAPIClient())
                            if selectedRecordingId == id {
                                selectedRecordingId = nil
                            }
                        }
                    }
                )
            }
        }
    }

    // MARK: - Detail Column

    @ViewBuilder
    private var detailColumn: some View {
        if appState.isRecording {
            LiveRecordingView()
        } else {
            switch selectedSection {
            case .allRecordings, .meetings, .notes, .reflections:
                if let recordingId = selectedRecordingId {
                    MacRecordingDetailView(recordingId: recordingId)
                } else {
                    ContentUnavailableView(
                        "Select a Recording",
                        systemImage: "waveform",
                        description: Text("Choose a recording from the list to view its details.")
                    )
                }
            case .chat:
                MacChatView()
            case .search:
                MacSearchView()
            case .settings:
                MacSettingsView()
            }
        }
    }

    // MARK: - Actions

    private func startRecording(type: RecordingType) {
        Task {
            await appState.startRecording(type: type)
            // Reload recordings when recording stops later
        }
    }
}

// MARK: - Auth View

struct MacAuthView: View {
    @EnvironmentObject var appState: MacAppState
    @State private var isLoginMode = true
    @State private var email = ""
    @State private var password = ""
    @State private var confirmPassword = ""

    var body: some View {
        VStack(spacing: 32) {
            Image(systemName: "brain.head.profile")
                .font(.system(size: 80))
                .foregroundStyle(.blue)

            Text("WaiComputer")
                .font(.largeTitle)
                .fontWeight(.bold)

            Picker("", selection: $isLoginMode) {
                Text("Login").tag(true)
                Text("Register").tag(false)
            }
            .pickerStyle(.segmented)
            .frame(width: 200)

            VStack(spacing: 12) {
                TextField("Email", text: $email)
                    .textFieldStyle(.roundedBorder)
                    .frame(width: 300)

                SecureField("Password", text: $password)
                    .textFieldStyle(.roundedBorder)
                    .frame(width: 300)

                if !isLoginMode {
                    SecureField("Confirm Password", text: $confirmPassword)
                        .textFieldStyle(.roundedBorder)
                        .frame(width: 300)
                }
            }

            if let error = appState.error {
                Text(error)
                    .foregroundStyle(.red)
                    .font(.caption)
            }

            Button(action: submit) {
                if appState.isLoading {
                    ProgressView()
                        .controlSize(.small)
                } else {
                    Text(isLoginMode ? "Login" : "Create Account")
                }
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .disabled(!isFormValid || appState.isLoading)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(60)
    }

    private var isFormValid: Bool {
        let emailValid = email.contains("@") && email.contains(".")
        let passwordValid = password.count >= 6

        if isLoginMode {
            return emailValid && passwordValid
        } else {
            return emailValid && passwordValid && password == confirmPassword
        }
    }

    private func submit() {
        Task {
            if isLoginMode {
                await appState.login(email: email, password: password)
            } else {
                await appState.register(email: email, password: password)
            }
        }
    }
}

#Preview {
    MacContentView()
        .environmentObject(MacAppState())
}
