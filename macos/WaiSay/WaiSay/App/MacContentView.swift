import SwiftUI
import WaiSayKit

struct MacContentView: View {
    @EnvironmentObject var appState: MacAppState
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        Group {
            if appState.isCheckingAuth {
                ProgressView("Loading...")
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if !appState.hasCompletedOnboarding {
                OnboardingView()
            } else if appState.isAuthenticated {
                MacMainView()
                    .overlay(alignment: .bottom) {
                        permissionBannerLayer
                    }
            } else {
                MacAuthView()
            }
        }
        .onAppear { appState.refreshPermissionStatus(rearmDismissed: true) }
        .onChange(of: scenePhase) { _, newPhase in
            if newPhase == .active {
                appState.refreshPermissionStatus(rearmDismissed: true)
            }
        }
    }

    @ViewBuilder
    private var permissionBannerLayer: some View {
        if let kind = appState.visiblePermissionBanner {
            PermissionBanner(
                kind: kind == .microphone ? .microphone : .accessibility,
                onPrimaryTap: {
                    appState.handlePermissionBannerTap(kind)
                },
                onDismiss: {
                    appState.dismissPermissionBanner(kind)
                }
            )
            .frame(maxWidth: 540)
            .padding(.bottom, Spacing.xl)
            .transition(.move(edge: .bottom).combined(with: .opacity))
            .animation(.easeInOut(duration: 0.25), value: kind)
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
    @State private var libraryErrorAutoDismissTask: Task<Void, Never>?
    @State private var recoveryNotice: String?
    @State private var recoveryNoticeAutoDismissTask: Task<Void, Never>?

    enum SidebarSection: Hashable {
        case allRecordings
        case folder(String)
        case trash
        case history
        case dictionary
        case settings
    }

    private var hasListColumn: Bool {
        switch selectedSection {
        case .allRecordings, .folder(_), .trash, .none:
            return true
        case .history, .dictionary, .settings:
            return false
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
            type: nil,
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
        case .folder(let folderId):
            return libraryViewModel.folders.first(where: { $0.id == folderId })?.name ?? "Folder"
        case .trash:
            return "Trash"
        case .history:
            return "History"
        case .dictionary:
            return "Dictionary"
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
                    min: hasListColumn ? 260 : 0,
                    ideal: hasListColumn ? 320 : 0,
                    max: hasListColumn ? 450 : 0
                )
        } detail: {
            detailColumn
                .id(detailPhaseKey)
        }
        .toolbar {
            ToolbarItemGroup(placement: .primaryAction) {
                Button {
                    selectedRecordingIds.removeAll()
                    prefetchedRecordingDetail = nil
                    if !hasListColumn {
                        selectedSection = .allRecordings
                    }
                } label: {
                    Label("New Recording", systemImage: "plus")
                        .labelStyle(.iconOnly)
                        .foregroundStyle(Palette.textSecondary)
                }
                .disabled(isRecordingHandoffActive || (selectedRecordingIds.isEmpty && hasListColumn))
                .help("New Recording")
                .accessibilityIdentifier("new-recording-toolbar-button")

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
        .overlay(alignment: .top) {
            VStack(spacing: Spacing.sm) {
                if let libraryError = libraryViewModel.error {
                    InlineLibraryErrorBanner(
                        message: libraryError,
                        onDismiss: { libraryViewModel.error = nil }
                    )
                }

                if let recoveryNotice {
                    RecordingRecoveryNoticeBanner(
                        message: recoveryNotice,
                        onDismiss: { dismissRecoveryNotice() }
                    )
                }
            }
            .padding(.top, Spacing.lg)
        }
        .alert("Import Error", isPresented: $importViewModel.showError) {
            Button("OK") {}
        } message: {
            Text(importViewModel.errorMessage)
        }
        .alert(
            "Recording Error",
            isPresented: Binding(
                get: { recordingViewModel.error != nil },
                set: { if !$0 { recordingViewModel.clearError() } }
            )
        ) {
            if recordingViewModel.error?.contains("System Settings") == true {
                Button("Open System Settings") {
                    if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_AudioCapture") {
                        NSWorkspace.shared.open(url)
                    }
                    recordingViewModel.clearError()
                }
                Button("Continue Mic-Only") {
                    recordingViewModel.clearError()
                }
            } else {
                Button("OK") {
                    recordingViewModel.clearError()
                }
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
            handleSelectedRecordingFromMenu(appState.selectedRecordingFromMenu)
            handlePendingMainWindowAction(appState.pendingMainWindowAction)
        }
        .onChange(of: selectedSection) { _, _ in
            selectedRecordingIds.removeAll()
            prefetchedRecordingDetail = nil
        }
        .onChange(of: appState.completedRecordingContext?.recordingId) { _, _ in
            handleCompletedRecordingChange()
        }
        .onChange(of: appState.selectedRecordingFromMenu) { _, newId in
            handleSelectedRecordingFromMenu(newId)
        }
        .onChange(of: appState.pendingMainWindowAction) { _, action in
            handlePendingMainWindowAction(action)
        }
        .onReceive(NotificationCenter.default.publisher(for: .importAudioFile)) { _ in
            importAudioFile()
        }
        .onReceive(NotificationCenter.default.publisher(for: .init("navigateToSettings"))) { _ in
            selectedSection = .settings
        }
        .onReceive(NotificationCenter.default.publisher(for: .init("navigateTo"))) { notification in
            guard let target = notification.object as? String else { return }
            switch target {
            case "allRecordings": selectedSection = .allRecordings
            case "history": selectedSection = .history
            case "dictionary": selectedSection = .dictionary
            case "trash": selectedSection = .trash
            default: break
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: .showNewRecording)) { _ in
            selectedRecordingIds.removeAll()
            prefetchedRecordingDetail = nil
            if !hasListColumn {
                selectedSection = .allRecordings
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: .pendingRecordingSyncDidFinish)) { _ in
            Task {
                await reloadLibrary()
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: .pendingRecordingRecoveryNotice)) { notification in
            guard let message = notification.userInfo?["message"] as? String,
                  !message.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            else { return }
            recoveryNotice = message
            scheduleRecoveryNoticeDismiss()
        }
        .onChange(of: libraryViewModel.error) { _, newValue in
            libraryErrorAutoDismissTask?.cancel()
            guard newValue != nil else { return }

            libraryErrorAutoDismissTask = Task {
                try? await Task.sleep(for: .seconds(6))
                guard !Task.isCancelled else { return }
                await MainActor.run {
                    libraryViewModel.error = nil
                }
            }
        }
        .onDisappear {
            completionTask?.cancel()
            libraryErrorAutoDismissTask?.cancel()
            recoveryNoticeAutoDismissTask?.cancel()
        }
    }

    private func dismissRecoveryNotice() {
        recoveryNoticeAutoDismissTask?.cancel()
        recoveryNoticeAutoDismissTask = nil
        recoveryNotice = nil
    }

    private func scheduleRecoveryNoticeDismiss() {
        recoveryNoticeAutoDismissTask?.cancel()
        recoveryNoticeAutoDismissTask = Task {
            try? await Task.sleep(for: .seconds(8))
            guard !Task.isCancelled else { return }
            await MainActor.run {
                recoveryNotice = nil
                recoveryNoticeAutoDismissTask = nil
            }
        }
    }

    // MARK: - Sidebar

    private var sidebar: some View {
        List {
            Section {
                sidebarRow("All Recordings", icon: "folder", section: .allRecordings)
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
                sidebarRow("History", icon: "clock", section: .history)
                sidebarRow("Dictionary", icon: "book", section: .dictionary)
            } header: {
                Text("Dictation")
                    .waiSectionHeader()
            }

            Section {
                sidebarRow("Settings", icon: "gear", section: .settings)
            } header: {
                Text("Wai")
                    .waiSectionHeader()
            }
        }
        .listStyle(.sidebar)
        .accessibilityIdentifier("sidebar")
    }

    private func sidebarRow(_ title: String, icon: String, section: SidebarSection) -> some View {
        Button {
            selectedSection = section
        } label: {
            Label(title, systemImage: icon)
                .font(Typography.body)
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("sidebar-\(title.lowercased().replacingOccurrences(of: " ", with: "-"))")
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
                        .accessibilityIdentifier("library-list-title")

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
                        localRecoveryRecordingIDs: libraryViewModel.localRecoveryRecordingIDs,
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
        case .allRecordings, .folder(_), .trash, .none:
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
            } else if isTrashSection {
                ContentUnavailableView(
                    "Select a Recording",
                    systemImage: "trash",
                    description: Text("Choose a recording to view its details.")
                )
            } else {
                NewRecordingView(
                    onStartDual: { startRecording(type: .note, inputSource: .dual) },
                    onStartMicOnly: { startRecording(type: .note, inputSource: .microphone) },
                    onImportFile: { importAudioFile() },
                    isImporting: importViewModel.isImporting
                )
            }
        case .history:
            DictationHistoryView()
        case .dictionary:
            DictationDictionaryView()
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

            if !recordingViewModel.isServerComplete {
                await reloadLibrary()
                guard !Task.isCancelled else { return }
                guard appState.completedRecordingContext?.recordingId == completedContext.recordingId else { return }

                withAnimation(.easeInOut(duration: 0.25)) {
                    appState.finishCompletedRecordingTransition(recordingId: completedContext.recordingId)
                }
                return
            }

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
    /// Returns `true` if upload finished, `false` if timed out.
    @discardableResult
    private func waitForUploadToFinish() async -> Bool {
        // Poll until phase is idle (upload done) — max ~30 seconds
        for _ in 0..<60 {
            if recordingViewModel.phase == .idle {
                return true
            }
            try? await Task.sleep(for: .milliseconds(500))
        }
        NSLog("[Recording] waitForUploadToFinish timed out after 30s — phase is still %@",
              String(describing: recordingViewModel.phase))
        return false
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

    private func handleSelectedRecordingFromMenu(_ id: String?) {
        guard let id else { return }

        selectedSection = .allRecordings
        selectedRecordingIds = [id]
        prefetchedRecordingDetail = nil
        appState.selectedRecordingFromMenu = nil
    }

    private func handlePendingMainWindowAction(_ action: MacMainWindowAction?) {
        guard let action else { return }

        appState.pendingMainWindowAction = nil
        switch action {
        case .importAudioFile:
            importAudioFile()
        case .settings:
            selectedSection = .settings
        case .dictationHistory:
            selectedSection = .history
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

private struct InlineLibraryErrorBanner: View {
    let message: String
    let onDismiss: () -> Void

    var body: some View {
        HStack(spacing: Spacing.sm) {
            Image(systemName: "wifi.exclamationmark")
                .foregroundStyle(Color.white)

            Text(message)
                .font(Typography.bodySmall)
                .foregroundStyle(Color.white)
                .lineLimit(2)

            Spacer(minLength: Spacing.md)

            Button(action: onDismiss) {
                Image(systemName: "xmark")
                    .foregroundStyle(Color.white.opacity(0.9))
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Dismiss library message")
        }
        .padding(.horizontal, Spacing.lg)
        .padding(.vertical, Spacing.sm)
        .background(Color.orange)
        .clipShape(RoundedRectangle(cornerRadius: 10))
        .shadow(color: .black.opacity(0.18), radius: 10, y: 4)
        .padding(.horizontal, Spacing.lg)
        .accessibilityIdentifier("library-inline-error-banner")
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

                Text("Saving transcript...")
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
                    ProgressView("Finalizing transcript...")
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
                Image(nsImage: NSApp.applicationIconImage)
                    .resizable()
                    .frame(width: 64, height: 64)

                Text("WaiSay")
                    .font(Typography.displayLarge)

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
                    .accessibilityIdentifier("auth-error-text")
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
            .accessibilityIdentifier("auth-submit-button")

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
                .accessibilityIdentifier("auth-email-field")

            if authMode != .magicLink {
                SecureField("Password", text: $password)
                    .textFieldStyle(.plain)
                    .waiTextField(isActive: focusedField == .password)
                    .focused($focusedField, equals: .password)
                    .frame(maxWidth: 380)
                    .accessibilityIdentifier("auth-password-field")

                if authMode == .register {
                    SecureField("Confirm Password", text: $confirmPassword)
                        .textFieldStyle(.plain)
                        .waiTextField(isActive: focusedField == .confirmPassword)
                        .focused($focusedField, equals: .confirmPassword)
                        .frame(maxWidth: 380)
                        .accessibilityIdentifier("auth-confirm-password-field")
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

private struct RecordingRecoveryNoticeBanner: View {
    let message: String
    let onDismiss: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: Spacing.sm) {
            Image(systemName: "checkmark.circle.fill")
                .foregroundStyle(.green)

            Text(message)
                .font(Typography.bodySmall)
                .foregroundStyle(Palette.textPrimary)
                .frame(maxWidth: .infinity, alignment: .leading)

            Button(action: onDismiss) {
                Image(systemName: "xmark")
                    .foregroundStyle(Palette.textSecondary)
            }
            .buttonStyle(.plain)
        }
        .padding(.horizontal, Spacing.lg)
        .padding(.vertical, Spacing.md)
        .background(.ultraThinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 10))
        .shadow(color: .black.opacity(0.18), radius: 10, y: 4)
        .accessibilityIdentifier("recording-recovery-banner")
    }
}

#Preview {
    let recordingViewModel = MacRecordingViewModel()
    let dictation = DictationManager()
    let appState = MacAppState(recordingViewModel: recordingViewModel, dictationManager: dictation)
    MacContentView()
        .environmentObject(appState)
        .environmentObject(recordingViewModel)
        .environmentObject(dictation)
}
