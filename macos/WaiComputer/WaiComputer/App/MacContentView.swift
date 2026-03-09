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
    @EnvironmentObject var recordingViewModel: MacRecordingViewModel
    @StateObject private var libraryViewModel = MacLibraryViewModel()
    @StateObject private var importViewModel = MacImportViewModel()
    @State private var selectedSection: SidebarSection? = .allRecordings
    @State private var selectedRecordingIds: Set<String> = []
    @State private var prefetchedRecordingDetail: RecordingDetail?
    @State private var completionTask: Task<Void, Never>?
    @State private var columnVisibility: NavigationSplitViewVisibility = .all
    @State private var isShowingCreateFolderSheet = false
    @State private var newFolderName = ""
    @State private var shouldAssignNewFolderToSelection = true

    enum SidebarSection: Hashable {
        case allRecordings
        case meetings
        case notes
        case folder(String)
        case trash
        case chat
        case search
        case settings
    }

    private var hasListColumn: Bool {
        switch selectedSection {
        case .allRecordings, .meetings, .notes, .folder(_), .trash, .none:
            return true
        case .chat, .search, .settings:
            return false
        }
    }

    private var currentTypeFilter: RecordingType? {
        switch selectedSection {
        case .meetings: return .meeting
        case .notes: return .note
        default: return nil
        }
    }

    private var currentFolderId: String? {
        switch selectedSection {
        case .folder(let folderId):
            return folderId
        default:
            return nil
        }
    }

    private var isTrashSection: Bool {
        if case .trash = selectedSection {
            return true
        }
        return false
    }

    private var displayedRecordings: [Recording] {
        libraryViewModel.filteredRecordings(
            type: currentTypeFilter,
            folderId: currentFolderId,
            trashed: isTrashSection
        )
    }

    private var selectedRecordingId: String? {
        guard selectedRecordingIds.count == 1 else { return nil }
        return selectedRecordingIds.first
    }

    private var currentListTitle: String {
        switch selectedSection {
        case .allRecordings:
            return "All Recordings"
        case .meetings:
            return "Meetings"
        case .notes:
            return "Notes"
        case .folder(let folderId):
            return libraryViewModel.folders.first(where: { $0.id == folderId })?.name ?? "Folder"
        case .trash:
            return "Trash"
        case .chat:
            return "Chat"
        case .search:
            return "Search"
        case .settings:
            return "Settings"
        case .none:
            return "Library"
        }
    }

    private var isRecordingHandoffActive: Bool {
        recordingViewModel.shouldPresentLiveView || appState.completedRecordingContext != nil
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
                Menu {
                    Button {
                        startRecording(type: .note, inputSource: .dual)
                    } label: {
                        Text("Mic + System Audio")
                        Text("Records your mic and computer audio")
                    }

                    Button {
                        startRecording(type: .note, inputSource: .microphone)
                    } label: {
                        Text("Mic Only")
                        Text("Records from your microphone only")
                    }

                    Divider()

                    Button {
                        importAudioFile()
                    } label: {
                        Text("Import Audio File")
                        Text("Transcribe an existing audio file")
                    }
                    .disabled(importViewModel.isImporting)
                } label: {
                    Label("New Recording", systemImage: "plus")
                        .labelStyle(.iconOnly)
                        .foregroundStyle(Palette.textSecondary)
                } primaryAction: {
                    startRecording(type: .note, inputSource: .dual)
                }
                .menuIndicator(.hidden)
                .fixedSize()
                .disabled(isRecordingHandoffActive)
                .help("New Recording (click to record, hold for options)")
                .accessibilityIdentifier("start-recording-button")

                if hasListColumn && !isTrashSection {
                    Button {
                        shouldAssignNewFolderToSelection = !selectedRecordingIds.isEmpty
                        isShowingCreateFolderSheet = true
                    } label: {
                        Image(systemName: "folder.badge.plus")
                            .foregroundStyle(Palette.textSecondary)
                    }
                    .help("New Folder")

                    Menu {
                        Button("Unfiled") {
                            moveSelectedRecordings(to: nil)
                        }
                        .disabled(selectedRecordingIds.isEmpty)

                        ForEach(libraryViewModel.folders) { folder in
                            Button(folder.name) {
                                moveSelectedRecordings(to: folder.id)
                            }
                            .disabled(selectedRecordingIds.isEmpty)
                        }
                    } label: {
                        Image(systemName: "folder")
                            .foregroundStyle(Palette.textSecondary)
                    }
                    .help("Move to Folder")
                    .disabled(selectedRecordingIds.isEmpty)

                    Button {
                        moveSelectedRecordingsToTrash()
                    } label: {
                        Image(systemName: "trash")
                            .foregroundStyle(Palette.textSecondary)
                    }
                    .help("Move to Trash")
                    .disabled(selectedRecordingIds.isEmpty)
                }

                if isTrashSection {
                    Button {
                        restoreSelectedRecordings()
                    } label: {
                        Image(systemName: "arrow.uturn.backward")
                            .foregroundStyle(Palette.textSecondary)
                    }
                    .help("Restore")
                    .disabled(selectedRecordingIds.isEmpty)

                    Button {
                        permanentlyDeleteSelectedRecordings()
                    } label: {
                        Image(systemName: "trash.slash")
                            .foregroundStyle(Palette.recording)
                    }
                    .help("Delete Permanently")
                    .disabled(selectedRecordingIds.isEmpty)
                }
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
        .alert(
            "Library Error",
            isPresented: Binding(
                get: { libraryViewModel.error != nil },
                set: { if !$0 { libraryViewModel.error = nil } }
            )
        ) {
            Button("OK") {
                libraryViewModel.error = nil
            }
        } message: {
            Text(libraryViewModel.error ?? "The library could not be updated.")
        }
        .alert(
            "Recording Error",
            isPresented: Binding(
                get: { recordingViewModel.error != nil },
                set: { if !$0 { recordingViewModel.clearError() } }
            )
        ) {
            Button("OK") {
                recordingViewModel.clearError()
            }
        } message: {
            Text(recordingViewModel.error ?? "The recording could not continue.")
        }
        .sheet(isPresented: $isShowingCreateFolderSheet) {
            CreateFolderSheet(
                folderName: $newFolderName,
                moveSelectionIntoFolder: $shouldAssignNewFolderToSelection,
                selectionCount: selectedRecordingIds.count,
                canMoveSelection: !selectedRecordingIds.isEmpty && !isTrashSection,
                onCancel: {
                    newFolderName = ""
                    isShowingCreateFolderSheet = false
                },
                onCreate: {
                    Task {
                        await createFolder()
                    }
                }
            )
        }
        .task {
            await reloadLibrary()
        }
        .onAppear {
            handleCompletedRecordingChange()
        }
        .onChange(of: selectedSection) { _, _ in
            selectedRecordingIds.removeAll()
            prefetchedRecordingDetail = nil
        }
        .onChange(of: appState.completedRecordingContext?.recordingId) { _, _ in
            handleCompletedRecordingChange()
        }
        .onChange(of: appState.selectedRecordingFromMenu) { _, newId in
            if let id = newId {
                selectedSection = .allRecordings
                selectedRecordingIds = [id]
                prefetchedRecordingDetail = nil
                appState.selectedRecordingFromMenu = nil
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: .importAudioFile)) { _ in
            importAudioFile()
        }
        .onDisappear {
            completionTask?.cancel()
        }
    }

    // MARK: - Sidebar

    private var sidebar: some View {
        List {
            Section {
                sidebarRow("All Recordings", icon: "folder", section: .allRecordings)
                sidebarRow("Meetings", icon: "video", section: .meetings)
                sidebarRow("Notes", icon: "note.text", section: .notes)
                sidebarRow("Trash", icon: "trash", section: .trash)
            } header: {
                Text("Library")
                    .waiSectionHeader()
            }

            Section {
                Button {
                    shouldAssignNewFolderToSelection = !selectedRecordingIds.isEmpty
                    isShowingCreateFolderSheet = true
                } label: {
                    Label("New Folder", systemImage: "folder.badge.plus")
                        .font(Typography.body)
                }
                .buttonStyle(.plain)

                ForEach(libraryViewModel.folders) { folder in
                    sidebarRow(folder.name, icon: "folder", section: .folder(folder.id))
                }
            } header: {
                Text("Folders")
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
            VStack(spacing: 0) {
                HStack(spacing: Spacing.sm) {
                    Text(currentListTitle)
                        .font(Typography.displaySmall)

                    Text("\(displayedRecordings.count)")
                        .font(Typography.label)
                        .foregroundStyle(Palette.textSecondary)

                    Spacer()

                    if libraryViewModel.isRefreshing {
                        ProgressView()
                            .controlSize(.small)
                    }
                }
                .padding(.horizontal, Spacing.lg)
                .padding(.vertical, Spacing.md)

                WaiDivider()

                if libraryViewModel.isLoading {
                    ProgressView()
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else if displayedRecordings.isEmpty {
                    VStack {
                        Spacer().frame(height: Spacing.xxxl)
                        ContentUnavailableView(
                            isTrashSection ? "Trash is Empty" : "No Recordings",
                            systemImage: isTrashSection ? "trash" : "waveform",
                            description: Text(emptyStateDescription)
                        )
                        Spacer()
                    }
                } else {
                    RecordingListView(
                        recordings: displayedRecordings,
                        folders: libraryViewModel.folders,
                        isTrash: isTrashSection,
                        selectedRecordingIds: $selectedRecordingIds,
                        onTrash: { ids in
                            trashRecordings(ids)
                        },
                        onRestore: { ids in
                            restoreRecordings(ids)
                        },
                        onPermanentDelete: { ids in
                            permanentlyDeleteRecordings(ids)
                        },
                        onMoveToFolder: { ids, folderId in
                            moveRecordings(ids, to: folderId)
                        }
                    )
                }
            }
        } else {
            // Non-list sections: empty content column
            Color.clear
        }
    }

    // MARK: - Detail Column

    /// Stable key for driving detail column cross-fade animation.
    private var detailPhaseKey: String {
        if recordingViewModel.shouldPresentLiveView {
            return "live"
        } else if appState.completedRecordingContext != nil {
            return "transition"
        } else {
            return "content"
        }
    }

    @ViewBuilder
    private var detailColumn: some View {
        ZStack {
            if recordingViewModel.shouldPresentLiveView {
                LiveRecordingView()
                    .zIndex(2)
                    .transition(.opacity)
            } else if let transition = appState.completedRecordingContext {
                CompletedRecordingTransitionView(transition: transition)
                    .zIndex(1)
                    .transition(.opacity)
            } else {
                detailContentView
                    .zIndex(0)
                    .transition(.opacity)
            }
        }
        .animation(.easeInOut(duration: 0.3), value: detailPhaseKey)
    }

    @ViewBuilder
    private var detailContentView: some View {
        switch selectedSection {
        case .allRecordings, .meetings, .notes, .folder(_), .trash, .none:
            if selectedRecordingIds.count > 1 {
                BulkSelectionDetailView(
                    selectionCount: selectedRecordingIds.count,
                    isTrash: isTrashSection,
                    onTrash: moveSelectedRecordingsToTrash,
                    onRestore: restoreSelectedRecordings,
                    onPermanentDelete: permanentlyDeleteSelectedRecordings
                )
            } else if let recordingId = selectedRecordingId {
                let detailMode: MacRecordingDetailView.Mode = isTrashSection ? .trash : .active
                let activeFolders = libraryViewModel.folders
                MacRecordingDetailView(
                    recordingId: recordingId,
                    initialDetail: prefetchedRecordingDetail?.id == recordingId ? prefetchedRecordingDetail : nil,
                    mode: detailMode,
                    folders: activeFolders,
                    onDelete: {
                        selectedRecordingIds.removeAll()
                        prefetchedRecordingDetail = nil
                        Task {
                            await libraryViewModel.loadLibrary(apiClient: appState.getAPIClient())
                        }
                    },
                    onRestore: {
                        selectedRecordingIds.removeAll()
                        prefetchedRecordingDetail = nil
                        Task {
                            await libraryViewModel.loadLibrary(apiClient: appState.getAPIClient())
                        }
                    },
                    onMoveToFolder: { folderId in
                        if currentFolderId != nil, currentFolderId != folderId {
                            selectedRecordingIds.removeAll()
                        }
                        prefetchedRecordingDetail = nil
                        Task {
                            await libraryViewModel.loadLibrary(apiClient: appState.getAPIClient())
                        }
                    }
                )
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

    /// When recording state changes from recording to not-recording,
    /// select the completed recording and refresh the library.
    private func handleCompletedRecordingChange() {
        completionTask?.cancel()

        guard let completedContext = appState.completedRecordingContext else { return }

        selectedSection = .allRecordings
        selectedRecordingIds.removeAll()
        prefetchedRecordingDetail = nil

        completionTask = Task {
            // Wait for the upload to finish (phase goes idle when cleanup completes)
            await waitForUploadToFinish()
            guard !Task.isCancelled else { return }
            guard appState.completedRecordingContext?.recordingId == completedContext.recordingId else { return }

            // Now fetch the recording detail (title should be generated by now)
            let detail = await resolveCompletedRecording(id: completedContext.recordingId)
            guard !Task.isCancelled else { return }
            guard appState.completedRecordingContext?.recordingId == completedContext.recordingId else { return }

            if let selectedRecordingId, selectedRecordingId != completedContext.recordingId {
                withAnimation(.easeInOut(duration: 0.25)) {
                    appState.finishCompletedRecordingTransition(recordingId: completedContext.recordingId)
                }
                return
            }

            // Set prefetched detail first so MacRecordingDetailView won't show a loading state
            prefetchedRecordingDetail = detail
            selectedRecordingIds = [completedContext.recordingId]

            withAnimation(.easeInOut(duration: 0.25)) {
                appState.finishCompletedRecordingTransition(recordingId: completedContext.recordingId)
            }

            // Final library reload to pick up the AI-generated title in the sidebar
            try? await Task.sleep(for: .milliseconds(200))
            guard !Task.isCancelled else { return }
            await reloadLibrary()
        }
    }

    /// Wait until the recording view model finishes its upload/cleanup.
    private func waitForUploadToFinish() async {
        // Poll until phase is idle (upload done) — max ~15 seconds
        for _ in 0..<30 {
            if recordingViewModel.phase == .idle {
                return
            }
            try? await Task.sleep(for: .milliseconds(500))
        }
    }

    private func resolveCompletedRecording(id: String) async -> RecordingDetail? {
        if let detail = await appState.uiTestRecordingDetail(id: id) {
            libraryViewModel.setRecordings(appState.uiTestRecordings() ?? [])
            libraryViewModel.setFolders([])
            return detail
        }

        let apiClient = appState.getAPIClient()

        await reloadLibrary()

        do {
            return try await apiClient.getRecording(id: id)
        } catch {
            NSLog("[Recording] Failed to fetch completed recording %@: %@", id, error.localizedDescription)
        }

        return nil
    }

    private func reloadLibrary() async {
        if let recordings = appState.uiTestRecordings() {
            libraryViewModel.setRecordings(recordings)
            libraryViewModel.setFolders([])
            return
        }

        await libraryViewModel.loadLibrary(apiClient: appState.getAPIClient())
    }

    // MARK: - Actions

    private func startRecording(
        type: RecordingType,
        inputSource: MacRecordingInputSource = .dual
    ) {
        Task {
            await appState.startRecording(type: type, inputSource: inputSource)
        }
    }

    private func importAudioFile() {
        Task {
            await importViewModel.pickAndUpload(apiClient: appState.getAPIClient())
            if importViewModel.importState == .done {
                await libraryViewModel.loadLibrary(apiClient: appState.getAPIClient())
            }
        }
    }

    private var emptyStateDescription: String {
        if isTrashSection {
            return "Deleted recordings appear here until you permanently remove them."
        }
        if currentFolderId != nil {
            return "Move recordings into this folder to organize them here."
        }
        return "Start a recording to see it here."
    }

    private func createFolder() async {
        let name = newFolderName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty else { return }

        let selectedIds = Array(selectedRecordingIds)
        if let folder = await libraryViewModel.createFolder(name: name, apiClient: appState.getAPIClient()) {
            if shouldAssignNewFolderToSelection && !selectedIds.isEmpty && !isTrashSection {
                await libraryViewModel.moveRecordings(ids: selectedIds, to: folder.id, apiClient: appState.getAPIClient())
                selectedRecordingIds.removeAll()
            }
            selectedSection = .folder(folder.id)
            newFolderName = ""
            shouldAssignNewFolderToSelection = true
            isShowingCreateFolderSheet = false
        }
    }

    private func moveRecordings(_ ids: [String], to folderId: String?) {
        guard !ids.isEmpty else { return }
        Task {
            await libraryViewModel.moveRecordings(ids: ids, to: folderId, apiClient: appState.getAPIClient())
            selectedRecordingIds.removeAll()
        }
    }

    private func moveSelectedRecordings(to folderId: String?) {
        moveRecordings(Array(selectedRecordingIds), to: folderId)
    }

    private func trashRecordings(_ ids: [String]) {
        guard !ids.isEmpty else { return }
        Task {
            await libraryViewModel.trashRecordings(ids: ids, apiClient: appState.getAPIClient())
            selectedRecordingIds.subtract(ids)
            prefetchedRecordingDetail = nil
        }
    }

    private func moveSelectedRecordingsToTrash() {
        trashRecordings(Array(selectedRecordingIds))
    }

    private func restoreRecordings(_ ids: [String]) {
        guard !ids.isEmpty else { return }
        Task {
            await libraryViewModel.restoreRecordings(ids: ids, apiClient: appState.getAPIClient())
            selectedRecordingIds.subtract(ids)
            prefetchedRecordingDetail = nil
        }
    }

    private func restoreSelectedRecordings() {
        restoreRecordings(Array(selectedRecordingIds))
    }

    private func permanentlyDeleteRecordings(_ ids: [String]) {
        guard !ids.isEmpty else { return }
        Task {
            await libraryViewModel.permanentlyDeleteRecordings(ids: ids, apiClient: appState.getAPIClient())
            selectedRecordingIds.subtract(ids)
            prefetchedRecordingDetail = nil
        }
    }

    private func permanentlyDeleteSelectedRecordings() {
        permanentlyDeleteRecordings(Array(selectedRecordingIds))
    }
}

private struct CreateFolderSheet: View {
    @Binding var folderName: String
    @Binding var moveSelectionIntoFolder: Bool
    let selectionCount: Int
    let canMoveSelection: Bool
    let onCancel: () -> Void
    let onCreate: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.lg) {
            Text("New Folder")
                .font(Typography.displaySmall)

            TextField("Folder name", text: $folderName)
                .textFieldStyle(.plain)
                .waiTextField()

            if canMoveSelection {
                Toggle(
                    "Move \(selectionCount) selected \(selectionCount == 1 ? "recording" : "recordings") into this folder",
                    isOn: $moveSelectionIntoFolder
                )
                .toggleStyle(.checkbox)
            }

            HStack {
                Spacer()

                Button("Cancel", action: onCancel)

                Button("Create", action: onCreate)
                    .buttonStyle(WaiPrimaryButtonStyle(isDisabled: folderName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty))
                    .disabled(folderName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
        .padding(Spacing.xl)
        .frame(width: 420)
    }
}

private struct BulkSelectionDetailView: View {
    let selectionCount: Int
    let isTrash: Bool
    let onTrash: () -> Void
    let onRestore: () -> Void
    let onPermanentDelete: () -> Void

    var body: some View {
        VStack(spacing: Spacing.lg) {
            ContentUnavailableView(
                "\(selectionCount) Recordings Selected",
                systemImage: isTrash ? "trash" : "checklist",
                description: Text(
                    isTrash
                        ? "Restore them or delete them permanently."
                        : "Use the toolbar to move them into folders or send them to trash."
                )
            )

            HStack(spacing: Spacing.md) {
                if isTrash {
                    Button("Restore", action: onRestore)
                        .buttonStyle(WaiGhostButtonStyle())

                    Button("Delete Permanently", action: onPermanentDelete)
                        .buttonStyle(WaiGhostButtonStyle())
                } else {
                    Button("Move to Trash", action: onTrash)
                        .buttonStyle(WaiGhostButtonStyle())
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(Spacing.huge)
    }
}

private struct CompletedRecordingTransitionView: View {
    let transition: CompletedRecordingContext

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: Spacing.md) {
                ProgressView()
                    .controlSize(.small)
                    .frame(width: 12, height: 12)

                Text("Saving recording...")
                    .font(Typography.displaySmall)
                    .foregroundStyle(Palette.textSecondary)

                Spacer()

                Text(formatDuration(transition.duration))
                    .font(Typography.monoLarge)
                    .foregroundStyle(Palette.textSecondary)

                Text(transition.recordingType.rawValue.capitalized)
                    .font(Typography.label)
                    .foregroundStyle(Palette.typeColor(transition.recordingType))
            }
            .padding(Spacing.lg)

            WaiDivider()

            if !transition.transcript.isEmpty {
                ScrollView {
                    Text(transition.transcript)
                        .font(Typography.reading)
                        .lineSpacing(6)
                        .foregroundStyle(Palette.textPrimary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(Spacing.lg)
                        .textSelection(.enabled)
                }
            } else {
                VStack {
                    Spacer()
                    ProgressView("Processing audio...")
                        .foregroundStyle(Palette.textSecondary)
                    Spacer()
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("completed-recording-transition")
    }

    private func formatDuration(_ duration: TimeInterval) -> String {
        let totalSeconds = Int(duration)
        let minutes = totalSeconds / 60
        let seconds = totalSeconds % 60
        return String(format: "%02d:%02d", minutes, seconds)
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
    let recordingViewModel = MacRecordingViewModel()
    let appState = MacAppState(recordingViewModel: recordingViewModel)
    MacContentView()
        .environmentObject(appState)
        .environmentObject(recordingViewModel)
}
