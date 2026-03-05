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
    @StateObject private var importViewModel = MacImportViewModel()
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
                    Divider()
                    Button("Import Audio File...") {
                        importAudioFile()
                    }
                    .disabled(importViewModel.isImporting)
                } label: {
                    Label("New Recording", systemImage: "plus")
                }
                .disabled(appState.isRecording)
            }
        }
        .alert("Import Error", isPresented: $importViewModel.showError) {
            Button("OK") {}
        } message: {
            Text(importViewModel.errorMessage)
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
        }
    }

    private func importAudioFile() {
        Task {
            await importViewModel.pickAndUpload(apiClient: appState.getAPIClient())
            if importViewModel.importState == .done {
                await libraryViewModel.loadRecordings(apiClient: appState.getAPIClient())
            }
        }
    }
}

// MARK: - Auth View

struct MacAuthView: View {
    @EnvironmentObject var appState: MacAppState

    enum AuthMode: String, CaseIterable {
        case login = "Login"
        case register = "Register"
        case magicLink = "Magic Link"
    }

    @State private var authMode: AuthMode = .login
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

            Picker("", selection: $authMode) {
                ForEach(AuthMode.allCases, id: \.self) { mode in
                    Text(mode.rawValue).tag(mode)
                }
            }
            .pickerStyle(.segmented)
            .frame(width: 300)

            if authMode == .magicLink && appState.magicLinkSent {
                magicLinkSentView
            } else {
                formView
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
                    Text(buttonTitle)
                }
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .disabled(!isFormValid || appState.isLoading)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(60)
        .onChange(of: authMode) {
            appState.magicLinkSent = false
            appState.error = nil
        }
    }

    @ViewBuilder
    private var formView: some View {
        VStack(spacing: 12) {
            TextField("Email", text: $email)
                .textFieldStyle(.roundedBorder)
                .frame(width: 300)

            if authMode != .magicLink {
                SecureField("Password", text: $password)
                    .textFieldStyle(.roundedBorder)
                    .frame(width: 300)

                if authMode == .register {
                    SecureField("Confirm Password", text: $confirmPassword)
                        .textFieldStyle(.roundedBorder)
                        .frame(width: 300)
                }
            }
        }
    }

    private var magicLinkSentView: some View {
        VStack(spacing: 16) {
            Image(systemName: "envelope.badge")
                .font(.system(size: 48))
                .foregroundStyle(.green)

            Text("Check your email")
                .font(.title2)
                .fontWeight(.semibold)

            Text("We sent a sign-in link to \(email)")
                .foregroundStyle(.secondary)

            Button("Send again") {
                appState.magicLinkSent = false
            }
            .buttonStyle(.plain)
            .foregroundStyle(.blue)
        }
    }

    private var buttonTitle: String {
        switch authMode {
        case .login: return "Login"
        case .register: return "Create Account"
        case .magicLink: return "Send Magic Link"
        }
    }

    private var isFormValid: Bool {
        if authMode == .magicLink && appState.magicLinkSent {
            return false
        }

        let emailValid = email.contains("@") && email.contains(".")

        switch authMode {
        case .login:
            return emailValid && password.count >= 6
        case .register:
            return emailValid && password.count >= 6 && password == confirmPassword
        case .magicLink:
            return emailValid
        }
    }

    private func submit() {
        Task {
            switch authMode {
            case .login:
                await appState.login(email: email, password: password)
            case .register:
                await appState.register(email: email, password: password)
            case .magicLink:
                await appState.requestMagicLink(email: email)
            }
        }
    }
}

#Preview {
    MacContentView()
        .environmentObject(MacAppState())
}
