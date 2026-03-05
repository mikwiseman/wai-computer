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
    @State private var selectedSection: SidebarSection? = .allRecordings
    @State private var selectedRecordingId: String?
    @State private var columnVisibility: NavigationSplitViewVisibility = .all

    enum SidebarSection: Hashable {
        case allRecordings
        case calls
        case notes
        case chat
        case search
        case settings
    }

    private var hasListColumn: Bool {
        switch selectedSection {
        case .allRecordings, .calls, .notes, .none:
            return true
        case .chat, .search, .settings:
            return false
        }
    }

    private var currentTypeFilter: RecordingType? {
        switch selectedSection {
        case .calls: return .meeting
        case .notes: return .note
        default: return nil
        }
    }

    var body: some View {
        NavigationSplitView(columnVisibility: $columnVisibility) {
            sidebar
                .navigationSplitViewColumnWidth(min: 160, ideal: 180, max: 220)
        } content: {
            listColumn
                .navigationSplitViewColumnWidth(
                    min: hasListColumn ? 220 : 0,
                    ideal: hasListColumn ? 280 : 0,
                    max: hasListColumn ? 360 : 0
                )
        } detail: {
            detailColumn
        }
        .toolbar {
            ToolbarItemGroup(placement: .primaryAction) {
                Button {
                    startRecording(type: .note)
                } label: {
                    Image(systemName: "plus")
                        .foregroundStyle(Palette.textSecondary)
                }
                .disabled(appState.isRecording)
                .help("New Recording")

                Button {
                    importAudioFile()
                } label: {
                    Image(systemName: "square.and.arrow.down")
                        .foregroundStyle(Palette.textSecondary)
                }
                .disabled(importViewModel.isImporting || appState.isRecording)
                .help("Import Audio File")
            }
        }
        .overlay {
            if importViewModel.isImporting {
                VStack(spacing: Spacing.md) {
                    ProgressView()
                        .controlSize(.small)
                    Text("Importing \(importViewModel.currentFilename)...")
                        .font(Typography.bodySmall)
                        .foregroundStyle(Palette.textSecondary)
                        .lineLimit(1)
                }
                .padding(Spacing.lg)
                .background(.ultraThinMaterial)
                .clipShape(RoundedRectangle(cornerRadius: 8))
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottom)
                .padding(.bottom, Spacing.xl)
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
        .onChange(of: appState.isRecording) { wasRecording, isNowRecording in
            if wasRecording && !isNowRecording {
                handleRecordingStop()
            }
        }
        .onChange(of: appState.selectedRecordingFromMenu) { _, newId in
            if let id = newId {
                selectedSection = .allRecordings
                selectedRecordingId = id
                appState.selectedRecordingFromMenu = nil
            }
        }
    }

    // MARK: - Sidebar

    private var sidebar: some View {
        List {
            Section {
                sidebarRow("All Recordings", icon: "folder", section: .allRecordings)
                sidebarRow("Calls", icon: "phone", section: .calls)
                sidebarRow("Notes", icon: "note.text", section: .notes)
            } header: {
                Text("Library")
                    .waiSectionHeader()
            }

            Section {
                sidebarRow("Chat", icon: "bubble.left.and.bubble.right", section: .chat)
                sidebarRow("Search", icon: "magnifyingglass", section: .search)
                sidebarRow("Settings", icon: "gear", section: .settings)
            } header: {
                Text("Tools")
                    .waiSectionHeader()
            }
        }
        .listStyle(.sidebar)
    }

    private func sidebarRow(_ title: String, icon: String, section: SidebarSection) -> some View {
        Button {
            selectedSection = section
        } label: {
            Label(title, systemImage: icon)
                .font(Typography.body)
        }
        .buttonStyle(.plain)
        .listRowBackground(
            selectedSection == section
                ? Color.accentColor.opacity(0.15)
                : Color.clear
        )
    }

    // MARK: - List Column

    @ViewBuilder
    private var listColumn: some View {
        if hasListColumn {
            let filtered = libraryViewModel.filteredRecordings(for: currentTypeFilter)

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
        } else {
            // Non-list sections: empty content column
            Color.clear
        }
    }

    // MARK: - Detail Column

    @ViewBuilder
    private var detailColumn: some View {
        if appState.isRecording {
            LiveRecordingView()
        } else {
            switch selectedSection {
            case .allRecordings, .calls, .notes, .none:
                if let recordingId = selectedRecordingId {
                    MacRecordingDetailView(recordingId: recordingId) {
                        selectedRecordingId = nil
                        Task {
                            await libraryViewModel.loadRecordings(apiClient: appState.getAPIClient())
                        }
                    }
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

    /// When recording state changes from recording to not-recording,
    /// select the completed recording and refresh the library.
    private func handleRecordingStop() {
        if let completedId = appState.recordingViewModel.currentRecordingId {
            selectedRecordingId = completedId
            selectedSection = .allRecordings
            appState.resetRecordingState()
            Task {
                // Load immediately so the recording appears in the list
                await libraryViewModel.loadRecordings(apiClient: appState.getAPIClient())
                // Reload again after a short delay — the server may still be
                // saving segments, generating embeddings, and uploading audio
                try? await Task.sleep(for: .seconds(3))
                await libraryViewModel.loadRecordings(apiClient: appState.getAPIClient())
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

    enum AuthMode: String, CaseIterable, Hashable {
        case login = "Login"
        case register = "Register"
        case magicLink = "Magic Link"
    }

    @State private var authMode: AuthMode = .login
    @State private var email = ""
    @State private var password = ""
    @State private var confirmPassword = ""
    @FocusState private var focusedField: Field?

    enum Field: Hashable {
        case email, password, confirmPassword
    }

    var body: some View {
        VStack(spacing: Spacing.xxl) {
            Spacer()

            // Icon + wordmark
            VStack(spacing: Spacing.lg) {
                WaiTriangleIcon(size: 48)

                HStack(spacing: 0) {
                    Text("wai")
                        .font(Typography.displayLarge)
                    Text("computer")
                        .font(.system(size: 32, weight: .light, design: .serif))
                }

                Text("YOUR SECOND BRAIN")
                    .waiSectionHeader()
            }

            // Tab bar
            WaiTabBar(
                tabs: [
                    ("Login", AuthMode.login),
                    ("Register", AuthMode.register),
                    ("Magic Link", AuthMode.magicLink),
                ],
                selection: $authMode
            )

            // Form
            if authMode == .magicLink && appState.magicLinkSent {
                magicLinkSentView
            } else {
                formView
            }

            if let error = appState.error {
                Text(error)
                    .foregroundStyle(Palette.recording)
                    .font(Typography.caption)
            }

            // Submit button
            Button(action: submit) {
                if appState.isLoading {
                    ProgressView()
                        .controlSize(.small)
                } else {
                    Text(buttonTitle)
                }
            }
            .buttonStyle(WaiPrimaryButtonStyle(isDisabled: !isFormValid || appState.isLoading))
            .disabled(!isFormValid || appState.isLoading)

            Spacer()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(Spacing.huge)
        .onChange(of: authMode) {
            appState.magicLinkSent = false
            appState.error = nil
        }
    }

    @ViewBuilder
    private var formView: some View {
        VStack(spacing: Spacing.md) {
            TextField("Email", text: $email)
                .textFieldStyle(.plain)
                .waiTextField(isActive: focusedField == .email)
                .focused($focusedField, equals: .email)
                .frame(maxWidth: 380)

            if authMode != .magicLink {
                SecureField("Password", text: $password)
                    .textFieldStyle(.plain)
                    .waiTextField(isActive: focusedField == .password)
                    .focused($focusedField, equals: .password)
                    .frame(maxWidth: 380)

                if authMode == .register {
                    SecureField("Confirm Password", text: $confirmPassword)
                        .textFieldStyle(.plain)
                        .waiTextField(isActive: focusedField == .confirmPassword)
                        .focused($focusedField, equals: .confirmPassword)
                        .frame(maxWidth: 380)
                }
            }
        }
    }

    private var magicLinkSentView: some View {
        VStack(spacing: Spacing.lg) {
            Image(systemName: "envelope.badge")
                .font(.system(size: Spacing.xxxl))
                .foregroundStyle(Palette.textSecondary)

            Text("Check your email")
                .font(Typography.displaySmall)

            Text("We sent a sign-in link to \(email)")
                .font(Typography.body)
                .foregroundStyle(Palette.textSecondary)

            Button("Send again") {
                appState.magicLinkSent = false
            }
            .buttonStyle(WaiGhostButtonStyle())
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
