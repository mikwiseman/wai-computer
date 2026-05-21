import SwiftUI
import WaiComputerKit

struct MacContentView: View {
    @EnvironmentObject var appState: MacAppState
    @EnvironmentObject var recordingViewModel: MacRecordingViewModel
    @EnvironmentObject var dictationManager: DictationManager
    @EnvironmentObject private var languageManager: LanguageManager
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        Group {
            if appState.isCheckingAuth {
                ProgressView(t("Loading...", "Загрузка..."))
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if !appState.isAuthenticated {
                MacAuthView()
            } else if !appState.hasCompletedOnboarding {
                OnboardingView()
            } else {
                MacMainView()
                    .overlay(alignment: .bottom) {
                        permissionBannerLayer
                    }
            }
        }
        .onAppear { appState.refreshPermissionStatus(rearmDismissed: true) }
        .onChange(of: scenePhase) { _, newPhase in
            if newPhase == .active {
                appState.refreshPermissionStatus(rearmDismissed: true)
            }
        }
        .alert(
            t("Dictation Error", "Ошибка диктовки"),
            isPresented: Binding(
                get: { dictationManager.error != nil },
                set: { if !$0 { dictationManager.clearError() } }
            )
        ) {
            if (dictationManager.error ?? "").contains("Microphone permission") {
                Button(t("Open Microphone Settings", "Открыть настройки микрофона")) {
                    MacPrivacySettings.openMicrophone()
                    dictationManager.clearError()
                }
                Button(t("Cancel", "Отмена"), role: .cancel) {
                    dictationManager.clearError()
                }
            } else {
                Button(t("OK", "ОК")) {
                    dictationManager.clearError()
                }
            }
        } message: {
            Text(dictationManager.error ?? t("Dictation could not continue.", "Диктовка не может продолжаться."))
        }
    }

    @ViewBuilder
    private var permissionBannerLayer: some View {
        if let kind = appState.visiblePermissionBanner,
           !isRecordingHandoffActive {
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

    private var isRecordingHandoffActive: Bool {
        recordingViewModel.shouldPresentLiveView || appState.completedRecordingContext != nil
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

// MARK: - Main View

struct MacMainView: View {
    @EnvironmentObject var appState: MacAppState
    @EnvironmentObject var recordingViewModel: MacRecordingViewModel
    @EnvironmentObject private var languageManager: LanguageManager
    @StateObject private var libraryViewModel = MacLibraryViewModel()
    @StateObject private var importViewModel = MacImportViewModel()
    @State private var selectedSection: SidebarSection? = .allRecordings
    @State private var selectedRecordingIds: Set<String> = []
    @State private var prefetchedRecordingDetail: RecordingDetail?
    @State private var pendingTitleEditId: String?
    @State private var completionTask: Task<Void, Never>?
    @State private var columnVisibility: NavigationSplitViewVisibility = .all
    @State private var isShowingCreateFolderSheet = false
    @State private var newFolderName = ""
    @State private var shouldAssignNewFolderToSelection = true
    @State private var isShowingRenameFolderSheet = false
    @State private var folderBeingEdited: Folder?
    @State private var editedFolderName = ""
    @State private var folderPendingDeletion: Folder?
    @State private var libraryErrorAutoDismissTask: Task<Void, Never>?
    @State private var recoveryNotice: String?
    @State private var recoveryNoticeAutoDismissTask: Task<Void, Never>?
    @State private var lastMeasuredLayoutWidth: CGFloat = 0

    enum SidebarSection: Hashable {
        case allRecordings
        case folder(String)
        case trash
        case search
        case history
        case dictionary
        case wai
        case settings
    }

    private var hasListColumn: Bool {
        switch selectedSection {
        case .allRecordings, .folder(_), .trash, .none:
            return true
        case .search, .history, .dictionary, .wai, .settings:
            return false
        }
    }

    private var currentRecordingType: RecordingType? {
        nil
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
            type: currentRecordingType,
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
            return t("All Recordings", "Все записи")
        case .folder(let folderId):
            return libraryViewModel.folders.first(where: { $0.id == folderId })?.name ?? t("Folder", "Папка")
        case .trash:
            return t("Trash", "Корзина")
        case .search:
            return t("Search", "Поиск")
        case .history:
            return t("History", "История")
        case .dictionary:
            return t("Dictionary", "Словарь")
        case .wai:
            return "Wai"
        case .settings:
            return t("Settings", "Настройки")
        case .none:
            return t("Library", "Библиотека")
        }
    }

    private var isRecordingHandoffActive: Bool {
        recordingViewModel.shouldPresentLiveView || appState.completedRecordingContext != nil
    }

    private var selectedRecordingsForActions: [Recording] {
        libraryViewModel.recordings.filter { selectedRecordingIds.contains($0.id) }
    }

    private var canMoveSelectedRecordingsToUnfiled: Bool {
        selectedRecordingsForActions.contains { $0.folderId != nil }
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }

    @ViewBuilder
    private var mainSplitView: some View {
        if hasListColumn {
            NavigationSplitView(columnVisibility: $columnVisibility) {
                sidebar
                    .navigationSplitViewColumnWidth(
                        min: MacMainLayoutMetrics.sidebarMinWidth,
                        ideal: MacMainLayoutMetrics.sidebarIdealWidth,
                        max: MacMainLayoutMetrics.sidebarMaxWidth
                    )
            } content: {
                listColumn
                    .navigationSplitViewColumnWidth(
                        min: MacMainLayoutMetrics.listMinWidth,
                        ideal: MacMainLayoutMetrics.listIdealWidth,
                        max: MacMainLayoutMetrics.listMaxWidth
                    )
            } detail: {
                detailColumn
                    .id(detailPhaseKey)
            }
        } else {
            NavigationSplitView(columnVisibility: $columnVisibility) {
                sidebar
                    .navigationSplitViewColumnWidth(
                        min: MacMainLayoutMetrics.sidebarMinWidth,
                        ideal: MacMainLayoutMetrics.sidebarIdealWidth,
                        max: MacMainLayoutMetrics.sidebarMaxWidth
                    )
            } detail: {
                detailColumn
                    .id(detailPhaseKey)
            }
        }
    }

    private var listHeaderActions: some View {
        HStack(spacing: Spacing.sm) {
            Button {
                startRecording(type: .meeting, inputSource: .dual)
            } label: {
                MainToolbarIconLabel(title: t("New Recording", "Новая запись"), systemImage: "plus")
            }
            .buttonStyle(.plain)
            .disabled(isRecordingHandoffActive || !appState.isAuthenticated)
            .help(t("New Recording", "Новая запись"))
            .accessibilityIdentifier("new-recording-toolbar-button")

            if !isTrashSection {
                Button {
                    shouldAssignNewFolderToSelection = !selectedRecordingIds.isEmpty
                    isShowingCreateFolderSheet = true
                } label: {
                    MainToolbarIconLabel(title: t("New Folder", "Новая папка"), systemImage: "folder.badge.plus")
                }
                .buttonStyle(.plain)
                .help(t("New Folder", "Новая папка"))
                .accessibilityIdentifier("new-folder-toolbar-button")

                Menu {
                    if canMoveSelectedRecordingsToUnfiled {
                        Button(t("Remove from Folder", "Убрать из папки")) {
                            moveSelectedRecordings(to: nil)
                        }
                        .disabled(selectedRecordingIds.isEmpty)
                    }

                    ForEach(libraryViewModel.folders) { folder in
                        Button(folder.name) {
                            moveSelectedRecordings(to: folder.id)
                        }
                        .disabled(selectedRecordingIds.isEmpty)
                    }
                } label: {
                    MainToolbarIconLabel(title: t("Move to Folder", "Переместить в папку"), systemImage: "folder")
                }
                .buttonStyle(.plain)
                .help(t("Move to Folder", "Переместить в папку"))
                .accessibilityIdentifier("move-to-folder-toolbar-button")
                .disabled(selectedRecordingIds.isEmpty || (!canMoveSelectedRecordingsToUnfiled && libraryViewModel.folders.isEmpty))

                Button {
                    moveSelectedRecordingsToTrash()
                } label: {
                    MainToolbarIconLabel(title: t("Move to Trash", "Переместить в корзину"), systemImage: "trash")
                }
                .buttonStyle(.plain)
                .help(t("Move to Trash", "Переместить в корзину"))
                .disabled(selectedRecordingIds.isEmpty)
            }

            if isTrashSection {
                Button {
                    restoreSelectedRecordings()
                } label: {
                    MainToolbarIconLabel(title: t("Restore", "Восстановить"), systemImage: "arrow.uturn.backward")
                }
                .buttonStyle(.plain)
                .help(t("Restore", "Восстановить"))
                .disabled(selectedRecordingIds.isEmpty)

                Button {
                    permanentlyDeleteSelectedRecordings()
                } label: {
                    MainToolbarIconLabel(title: t("Delete Permanently", "Удалить навсегда"), systemImage: "trash.slash", color: Palette.recording)
                }
                .buttonStyle(.plain)
                .help(t("Delete Permanently", "Удалить навсегда"))
                .disabled(selectedRecordingIds.isEmpty)
            }
        }
    }

    @ViewBuilder
    private var importOverlay: some View {
        if importViewModel.isImporting {
            VStack(spacing: Spacing.md) {
                ProgressView()
                    .controlSize(.small)
                Text(t("Importing", "Импорт") + " \(importViewModel.currentFilename)...")
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

    @ViewBuilder
    private var topBanners: some View {
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

    private var deleteFolderDialogTitle: String {
        guard let folder = folderPendingDeletion else {
            return t("Delete Folder?", "Удалить папку?")
        }
        return t("Delete “\(folder.name)”?", "Удалить «\(folder.name)»?")
    }

    var body: some View {
        mainSplitView
        .background {
            GeometryReader { proxy in
                Color.clear
                    .onAppear {
                        updateColumnVisibility(for: proxy.size.width)
                    }
                    .onChange(of: proxy.size.width) { _, width in
                        updateColumnVisibility(for: width)
                    }
            }
        }
        .overlay {
            importOverlay
        }
        .overlay(alignment: .top) {
            topBanners
        }
        .alert(t("Import Error", "Ошибка импорта"), isPresented: $importViewModel.showError) {
            Button(t("OK", "ОК")) {}
        } message: {
            Text(importViewModel.errorMessage)
        }
        .alert(
            t("Recording Error", "Ошибка записи"),
            isPresented: Binding(
                get: { recordingViewModel.error != nil },
                set: { if !$0 { recordingViewModel.clearError() } }
            )
        ) {
            let message = recordingViewModel.error ?? ""
            if message.contains("Microphone permission") {
                Button(t("Open Microphone Settings", "Открыть настройки микрофона")) {
                    MacPrivacySettings.openMicrophone()
                    recordingViewModel.clearError()
                }
                Button(t("Cancel", "Отмена"), role: .cancel) {
                    recordingViewModel.clearError()
                }
            } else if message.contains("Audio Capture") || message.contains("System audio") {
                Button(t("Open System Settings", "Открыть системные настройки")) {
                    MacPrivacySettings.openSystemAudio()
                    recordingViewModel.clearError()
                }
                Button(t("Cancel", "Отмена"), role: .cancel) { recordingViewModel.clearError() }
            } else {
                Button(t("OK", "ОК")) {
                    recordingViewModel.clearError()
                }
            }
        } message: {
            Text(recordingViewModel.error ?? t("The recording could not continue.", "Запись не может продолжаться."))
        }
        .sheet(isPresented: $isShowingCreateFolderSheet) {
            FolderNameSheet(
                title: t("New Folder", "Новая папка"),
                textFieldPlaceholder: t("Folder name", "Название папки"),
                primaryTitle: t("Create", "Создать"),
                cancelTitle: t("Cancel", "Отмена"),
                folderName: $newFolderName,
                moveSelectionIntoFolder: $shouldAssignNewFolderToSelection,
                selectionCount: selectedRecordingIds.count,
                canMoveSelection: !selectedRecordingIds.isEmpty && !isTrashSection,
                moveSelectionText: t(
                    "Move \(selectedRecordingIds.count) selected \(selectedRecordingIds.count == 1 ? "recording" : "recordings") into this folder",
                    "Переместить выбранные записи (\(selectedRecordingIds.count)) в эту папку"
                ),
                onCancel: {
                    newFolderName = ""
                    isShowingCreateFolderSheet = false
                },
                onSubmit: {
                    Task {
                        await createFolder()
                    }
                }
            )
        }
        .sheet(isPresented: $isShowingRenameFolderSheet) {
            FolderNameSheet(
                title: t("Rename Folder", "Переименовать папку"),
                textFieldPlaceholder: t("Folder name", "Название папки"),
                primaryTitle: t("Rename", "Переименовать"),
                cancelTitle: t("Cancel", "Отмена"),
                folderName: $editedFolderName,
                moveSelectionIntoFolder: .constant(false),
                selectionCount: 0,
                canMoveSelection: false,
                moveSelectionText: "",
                onCancel: {
                    editedFolderName = ""
                    folderBeingEdited = nil
                    isShowingRenameFolderSheet = false
                },
                onSubmit: {
                    Task {
                        await renameFolder()
                    }
                }
            )
        }
        .confirmationDialog(
            deleteFolderDialogTitle,
            isPresented: Binding(
                get: { folderPendingDeletion != nil },
                set: { if !$0 { folderPendingDeletion = nil } }
            ),
            titleVisibility: .visible
        ) {
            Button(t("Delete Folder", "Удалить папку"), role: .destructive) {
                if let folder = folderPendingDeletion {
                    Task { await deleteFolder(folder) }
                }
            }
            Button(t("Cancel", "Отмена"), role: .cancel) {
                folderPendingDeletion = nil
            }
        } message: {
            Text(t(
                "Recordings stay in All Recordings. Only the folder is removed.",
                "Записи останутся во всех записях. Удалится только папка."
            ))
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
        .onChange(of: hasListColumn) { _, _ in
            updateColumnVisibility(for: lastMeasuredLayoutWidth)
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
            case "search": selectedSection = .search
            case "trash": selectedSection = .trash
            case "wai": selectedSection = .wai
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

    private func updateColumnVisibility(for width: CGFloat) {
        guard width > 0 else { return }
        lastMeasuredLayoutWidth = width

        let preferredVisibility = MacMainLayoutMetrics.preferredColumnVisibility(
            hasListColumn: hasListColumn,
            containerWidth: width
        )
        guard columnVisibility != preferredVisibility else { return }
        columnVisibility = preferredVisibility
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
                sidebarRow(t("All Recordings", "Все записи"), icon: "folder", section: .allRecordings, identifier: "all-recordings")
                sidebarRow(t("Trash", "Корзина"), icon: "trash", section: .trash, identifier: "trash")
            } header: {
                Text(t("Library", "Библиотека"))
                    .waiSectionHeader()
            }

            Section {
                Button {
                    shouldAssignNewFolderToSelection = !selectedRecordingIds.isEmpty
                    isShowingCreateFolderSheet = true
                } label: {
                    Label(t("New Folder", "Новая папка"), systemImage: "folder.badge.plus")
                        .font(Typography.body)
                }
                .buttonStyle(.plain)

                ForEach(libraryViewModel.folders) { folder in
                    folderSidebarRow(folder)
                }
            } header: {
                Text(t("Recording Folders", "Папки записей"))
                    .waiSectionHeader()
            }

            Section {
                sidebarRow(t("History", "История"), icon: "clock", section: .history, identifier: "history")
                sidebarRow(t("Dictionary", "Словарь"), icon: "book", section: .dictionary, identifier: "dictionary")
            } header: {
                Text(t("Dictation", "Диктовка"))
                    .waiSectionHeader()
            }

            Section {
                sidebarRow("Wai", icon: "sparkles", section: .wai, identifier: "wai")
                sidebarRow(t("Search", "Поиск"), icon: "magnifyingglass", section: .search, identifier: "search")
                sidebarRow(t("Settings", "Настройки"), icon: "gear", section: .settings, identifier: "settings")
            } header: {
                Text("Wai")
                    .waiSectionHeader()
            }
        }
        .listStyle(.sidebar)
        .accessibilityIdentifier("sidebar")
    }

    private func sidebarRow(_ title: String, icon: String, section: SidebarSection, identifier: String) -> some View {
        Button {
            selectedSection = section
        } label: {
            Label(title, systemImage: icon)
                .font(Typography.body)
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("sidebar-\(identifier)")
        .listRowBackground(
            selectedSection == section
                ? Palette.accent.opacity(0.15)
                : Color.clear
        )
    }

    private func folderSidebarRow(_ folder: Folder) -> some View {
        sidebarRow(folder.name, icon: "folder", section: .folder(folder.id), identifier: "folder-\(folder.id)")
            .contextMenu {
                Button(t("Rename…", "Переименовать…")) {
                    beginRenameFolder(folder)
                }
                Button(t("Delete Folder", "Удалить папку"), role: .destructive) {
                    folderPendingDeletion = folder
                }
            }
    }

    // MARK: - List Column

    @ViewBuilder
    private var listColumn: some View {
        if hasListColumn {
            VStack(spacing: 0) {
                HStack(spacing: Spacing.sm) {
                    Text(currentListTitle)
                        .font(Typography.displaySmall)
                        .lineLimit(1)
                        .accessibilityIdentifier("library-list-title")

                    Text("\(displayedRecordings.count)")
                        .font(Typography.label)
                        .foregroundStyle(Palette.textSecondary)

                    Spacer()

                    if libraryViewModel.isRefreshing {
                        ProgressView()
                            .controlSize(.small)
                    }

                    listHeaderActions
                        .fixedSize(horizontal: true, vertical: false)
                }
                .padding(.horizontal, Spacing.lg)
                .padding(.vertical, Spacing.md)

                WaiDivider()

                if libraryViewModel.isLoading {
                    ProgressView()
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else if displayedRecordings.isEmpty {
                    ContentUnavailableView(
                        isTrashSection ? t("Trash is Empty", "Корзина пуста") : t("No Recordings", "Нет записей"),
                        systemImage: isTrashSection ? "trash" : "waveform",
                        description: Text(emptyStateDescription)
                    )
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
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
                        },
                        onRequestRename: { id in
                            selectedRecordingIds = [id]
                            pendingTitleEditId = id
                        }
                    )
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
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
                    pendingTitleEditId: $pendingTitleEditId,
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
                    },
                    onDidRename: {
                        prefetchedRecordingDetail = nil
                        Task {
                            await libraryViewModel.loadLibrary(apiClient: appState.getAPIClient())
                        }
                    }
                )
            } else if isTrashSection {
                ContentUnavailableView(
                    t("Select a Recording", "Выбери запись"),
                    systemImage: "trash",
                    description: Text(t("Choose a recording to view its details.", "Выбери запись, чтобы открыть детали."))
                )
            } else {
                NewRecordingView(
                    onStartRecording: { startRecording(type: .meeting, inputSource: .dual) },
                    onImportFile: { importAudioFile() },
                    isImporting: importViewModel.isImporting
                )
            }
        case .search:
            MacSearchView()
        case .history:
            DictationHistoryView()
        case .dictionary:
            DictationDictionaryView()
        case .wai:
            CompanionView(
                apiClient: appState.getAPIClient(),
                recordings: libraryViewModel.recordings
            )
        case .settings:
            MacSettingsView()
        }
    }

    /// When recording state changes from recording to not-recording,
    /// select the completed recording and refresh the library.
    ///
    /// We pre-select the recording immediately so the user lands on its
    /// detail view (with a loading state if needed) instead of a blank
    /// All Recordings list while the upload + summary pipeline finishes.
    private func handleCompletedRecordingChange() {
        completionTask?.cancel()

        guard let completedContext = appState.completedRecordingContext else { return }

        selectedSection = .allRecordings
        prefetchedRecordingDetail = nil
        // Immediate selection — the detail view shows a loading state until
        // resolveCompletedRecording returns. This avoids the "where did my
        // recording go?" moment from WW-50 #2.
        selectedRecordingIds = [completedContext.recordingId]

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
                // User navigated away while we were waiting — respect that.
                withAnimation(.easeInOut(duration: 0.25)) {
                    appState.finishCompletedRecordingTransition(recordingId: completedContext.recordingId)
                }
                return
            }

            // Hand the detail to the already-selected detail view.
            prefetchedRecordingDetail = detail

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
        }
    }

    private var emptyStateDescription: String {
        if isTrashSection {
            return t(
                "Deleted recordings appear here until you permanently remove them.",
                "Удаленные записи остаются здесь, пока ты не удалишь их навсегда."
            )
        }
        if currentFolderId != nil {
            return t(
                "Move recordings into this folder to organize them here.",
                "Перемести записи в эту папку, чтобы организовать их здесь."
            )
        }
        return t("Start a recording to see it here.", "Начни запись, чтобы она появилась здесь.")
    }

    private func beginRenameFolder(_ folder: Folder) {
        folderBeingEdited = folder
        editedFolderName = folder.name
        isShowingRenameFolderSheet = true
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

    private func renameFolder() async {
        guard let folder = folderBeingEdited else { return }
        let name = editedFolderName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty else { return }

        if let renamed = await libraryViewModel.renameFolder(id: folder.id, name: name, apiClient: appState.getAPIClient()) {
            if selectedSection == .folder(folder.id) {
                selectedSection = .folder(renamed.id)
            }
            editedFolderName = ""
            folderBeingEdited = nil
            isShowingRenameFolderSheet = false
        }
    }

    private func deleteFolder(_ folder: Folder) async {
        if await libraryViewModel.deleteFolder(id: folder.id, apiClient: appState.getAPIClient()) {
            if selectedSection == .folder(folder.id) {
                selectedSection = .allRecordings
            }
            selectedRecordingIds.removeAll()
            prefetchedRecordingDetail = nil
            folderPendingDeletion = nil
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

private struct FolderNameSheet: View {
    let title: String
    let textFieldPlaceholder: String
    let primaryTitle: String
    let cancelTitle: String
    @Binding var folderName: String
    @Binding var moveSelectionIntoFolder: Bool
    let selectionCount: Int
    let canMoveSelection: Bool
    let moveSelectionText: String
    let onCancel: () -> Void
    let onSubmit: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.lg) {
            Text(title)
                .font(Typography.displaySmall)

            TextField(textFieldPlaceholder, text: $folderName)
                .textFieldStyle(.plain)
                .waiTextField()
                .frame(maxWidth: .infinity)

            if canMoveSelection {
                Toggle(moveSelectionText, isOn: $moveSelectionIntoFolder)
                    .toggleStyle(.checkbox)
                    .fixedSize(horizontal: false, vertical: true)
            }

            HStack(spacing: Spacing.md) {
                Spacer()

                Button(cancelTitle, action: onCancel)
                    .buttonStyle(WaiGhostButtonStyle())
                    .frame(width: MacMainLayoutMetrics.folderNameSheetActionWidth)

                Button(primaryTitle, action: onSubmit)
                    .buttonStyle(WaiPrimaryButtonStyle(isDisabled: folderName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty))
                    .disabled(folderName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    .frame(width: MacMainLayoutMetrics.folderNameSheetActionWidth)
            }
        }
        .padding(Spacing.xl)
        .frame(width: MacMainLayoutMetrics.folderNameSheetWidth)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("folder-name-sheet")
    }
}

private struct MainToolbarIconLabel: View {
    let title: String
    let systemImage: String
    var color: Color = Palette.textSecondary

    var body: some View {
        Label(title, systemImage: systemImage)
            .labelStyle(.iconOnly)
            .font(.system(size: 15, weight: .semibold))
            .symbolRenderingMode(.hierarchical)
            .foregroundStyle(color)
            .frame(
                width: MacMainLayoutMetrics.toolbarIconFrame,
                height: MacMainLayoutMetrics.toolbarIconFrame
            )
            .contentShape(Rectangle())
            .accessibilityLabel(title)
    }
}

private struct BulkSelectionDetailView: View {
    let selectionCount: Int
    let isTrash: Bool
    let onTrash: () -> Void
    let onRestore: () -> Void
    let onPermanentDelete: () -> Void
    @EnvironmentObject private var languageManager: LanguageManager

    var body: some View {
        VStack(spacing: Spacing.lg) {
            ContentUnavailableView(
                t(
                    "\(selectionCount) Recordings Selected",
                    "Выбрано записей: \(selectionCount)"
                ),
                systemImage: isTrash ? "trash" : "checklist",
                description: Text(
                    isTrash
                        ? t("Restore them or delete them permanently.", "Восстанови их или удали навсегда.")
                        : t("Use the list header buttons to move them into folders or send them to trash.", "Используй кнопки в заголовке списка, чтобы переместить их в папку или корзину.")
                )
            )

            HStack(spacing: Spacing.md) {
                if isTrash {
                    Button(t("Restore", "Восстановить"), action: onRestore)
                        .buttonStyle(WaiGhostButtonStyle())

                    Button(t("Delete Permanently", "Удалить навсегда"), action: onPermanentDelete)
                        .buttonStyle(WaiGhostButtonStyle())
                } else {
                    Button(t("Move to Trash", "Переместить в корзину"), action: onTrash)
                        .buttonStyle(WaiGhostButtonStyle())
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(Spacing.huge)
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

private struct CompletedRecordingTransitionView: View {
    let transition: CompletedRecordingContext
    @EnvironmentObject private var languageManager: LanguageManager

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: Spacing.md) {
                ProgressView()
                    .controlSize(.small)
                    .frame(width: 12, height: 12)

                Text(t("Saving transcript...", "Сохраняем транскрипт..."))
                    .font(Typography.displaySmall)
                    .foregroundStyle(Palette.textSecondary)

                Spacer()

                Text(formatDuration(transition.duration))
                    .font(Typography.monoLarge)
                    .foregroundStyle(Palette.textSecondary)

                Text(recordingTypeLabel(transition.recordingType))
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
                    ProgressView(t("Finalizing transcript...", "Завершаем транскрипт..."))
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

    private func recordingTypeLabel(_ type: RecordingType) -> String {
        switch type {
        case .meeting:
            return t("Meeting", "Встреча")
        case .note:
            return t("Note", "Заметка")
        case .reflection:
            return t("Reflection", "Рефлексия")
        }
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

// MARK: - Auth View

struct MacAuthView: View {
    @EnvironmentObject var appState: MacAppState
    @EnvironmentObject var languageManager: LanguageManager

    private static let privacyPolicyURL = URL(string: "https://wai.computer/privacy")!
    private static let termsOfServiceURL = URL(string: "https://wai.computer/terms")!

    enum AuthMode: String, CaseIterable, Hashable {
        case login = "Login"
        case register = "Register"
        case magicLink = "Magic Link"
    }

    @State private var authMode: AuthMode = .login
    @State private var email = ""
    @State private var password = ""
    @State private var confirmPassword = ""
    @State private var acceptedLegalTerms = false
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

                Text("WaiComputer")
                    .font(Typography.displayLarge)

                Text(t("YOUR SECOND BRAIN", "ТВОЙ ВТОРОЙ МОЗГ"))
                    .waiSectionHeader()
            }

            // Tab bar
            WaiTabBar(
                tabs: [
                    (t("Login", "Вход"), AuthMode.login),
                    (t("Register", "Регистрация"), AuthMode.register),
                    (t("Magic Link", "Ссылка на email"), AuthMode.magicLink),
                ],
                selection: $authMode
            )

            // Form
            if authMode == .magicLink && appState.magicLinkSent {
                magicLinkSentView
            } else {
                formView
            }

            if authMode == .login, appState.passwordResetSent {
                Text(t(
                    "If this email is registered, we sent a password reset link.",
                    "Если этот email зарегистрирован, мы отправили ссылку для сброса пароля."
                ))
                .font(Typography.caption)
                .foregroundStyle(Palette.textSecondary)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 380)
                .accessibilityIdentifier("auth-password-reset-sent-text")
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
            appState.passwordResetSent = false
            appState.error = nil
            acceptedLegalTerms = false
        }
        .onChange(of: email) {
            appState.passwordResetSent = false
        }
    }

    @ViewBuilder
    private var formView: some View {
        VStack(spacing: Spacing.md) {
            TextField(t("Email", "Email"), text: $email)
                .textFieldStyle(.plain)
                .waiTextField(isActive: focusedField == .email)
                .focused($focusedField, equals: .email)
                .frame(maxWidth: 380)
                .accessibilityIdentifier("auth-email-field")

            if authMode != .magicLink {
                SecureField(t("Password", "Пароль"), text: $password)
                    .textFieldStyle(.plain)
                    .waiTextField(isActive: focusedField == .password)
                    .focused($focusedField, equals: .password)
                    .frame(maxWidth: 380)
                    .accessibilityIdentifier("auth-password-field")

                if authMode == .register {
                    SecureField(t("Confirm Password", "Повтори пароль"), text: $confirmPassword)
                        .textFieldStyle(.plain)
                        .waiTextField(isActive: focusedField == .confirmPassword)
                        .focused($focusedField, equals: .confirmPassword)
                        .frame(maxWidth: 380)
                        .accessibilityIdentifier("auth-confirm-password-field")

                    legalConsentRow
                }

                if authMode == .login {
                    Button(t("Forgot password?", "Забыли пароль?")) {
                        Task {
                            await appState.requestPasswordReset(
                                email: email,
                                locale: authLocale
                            )
                        }
                    }
                    .buttonStyle(WaiGhostButtonStyle())
                    .disabled(!emailLooksValid || appState.isLoading)
                    .accessibilityIdentifier("auth-forgot-password-button")
                }
            }
        }
    }

    private var legalConsentRow: some View {
        HStack(alignment: .top, spacing: Spacing.sm) {
            Toggle("", isOn: $acceptedLegalTerms)
                .labelsHidden()
                .toggleStyle(.checkbox)
                .accessibilityIdentifier("auth-legal-consent-toggle")

            VStack(alignment: .leading, spacing: 4) {
                Text(t("I agree to WaiComputer's legal terms.", "Я принимаю юридические условия WaiComputer."))
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textSecondary)

                HStack(spacing: 6) {
                    Link(t("Terms of Service", "Условия сервиса"), destination: Self.termsOfServiceURL)
                    Text("·")
                        .foregroundStyle(Palette.textTertiary)
                    Link(t("Privacy Policy", "Политика конфиденциальности"), destination: Self.privacyPolicyURL)
                }
                .font(Typography.caption)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .frame(maxWidth: 380, alignment: .leading)
    }

    private var magicLinkSentView: some View {
        VStack(spacing: Spacing.lg) {
            Image(systemName: "envelope.badge")
                .font(.system(size: Spacing.xxxl))
                .foregroundStyle(Palette.textSecondary)

            Text(t("Check your email", "Проверь email"))
                .font(Typography.displaySmall)

            Text(String(format: t("We sent a sign-in link to %@", "Мы отправили ссылку для входа на %@"), email))
                .font(Typography.body)
                .foregroundStyle(Palette.textSecondary)

            Button(t("Send again", "Отправить ещё раз")) {
                appState.magicLinkSent = false
            }
            .buttonStyle(WaiGhostButtonStyle())
        }
    }

    private var buttonTitle: String {
        switch authMode {
        case .login: return t("Login", "Войти")
        case .register: return t("Create Account", "Создать аккаунт")
        case .magicLink: return t("Send Magic Link", "Отправить ссылку")
        }
    }

    private var isFormValid: Bool {
        if authMode == .magicLink && appState.magicLinkSent {
            return false
        }

        switch authMode {
        case .login:
            return emailLooksValid && password.count >= 6
        case .register:
            return emailLooksValid && password.count >= 6 && password == confirmPassword && acceptedLegalTerms
        case .magicLink:
            return emailLooksValid
        }
    }

    private var emailLooksValid: Bool {
        email.contains("@") && email.contains(".")
    }

    private var authLocale: String {
        languageManager.current == .russian ? "ru" : "en"
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

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
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
