import SwiftUI
import UniformTypeIdentifiers
import WaiComputerKit

struct LibraryView: View {
    @EnvironmentObject var appState: AppState
    @EnvironmentObject private var languageManager: LanguageManager
    @StateObject private var viewModel = LibraryViewModel()
    @StateObject private var importViewModel = ImportViewModel()
    @StateObject private var searchViewModel = SearchViewModel()
    @State private var isSearchActive = false
    @State private var searchTarget: SearchResult?
    @State private var errorAutoDismissTask: Task<Void, Never>?
    @State private var importedRecording: Recording?
    @State private var showImportedDetail = false
    @State private var showNewFolderSheet = false
    @State private var newFolderName = ""
    @State private var newFolderMovesSelection = false
    @State private var showDeleteFolderConfirmation: Folder?
    @State private var renameFolderTarget: Folder?
    @State private var folderNameDraft = ""
    @State private var renameRecordingTarget: Recording?
    @State private var recordingTitleDraft = ""
    @State private var editMode: EditMode = .inactive
    @State private var selectedRecordingIds = Set<String>()

    private var isScreenshotMode: Bool {
        IOSTestingMode.current.isScreenshot
    }

    private var isEditing: Bool {
        editMode == .active
    }

    var body: some View {
        NavigationStack {
            Group {
                // While the search field is active (or a query is committed),
                // the library list is replaced by the search results surface
                // hosted by `.searchable`. Mirrors the macOS search behaviour
                // without adding a 5th tab.
                if isSearchActive || !searchViewModel.query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    LibrarySearchResults(
                        viewModel: searchViewModel,
                        onSubmit: performSearch,
                        onOpenRecording: { result in searchTarget = result }
                    )
                } else if viewModel.isLoading && viewModel.recordings.isEmpty {
                    ProgressView(t("Loading recordings...", "Загрузка записей..."))
                } else if viewModel.recordings.isEmpty && viewModel.trashedRecordings.isEmpty && viewModel.folders.isEmpty {
                    ContentUnavailableView(
                        t("No Recordings", "Нет записей"),
                        systemImage: "waveform",
                        description: Text(t("Start recording to see your notes here", "Начни запись, чтобы увидеть заметки здесь"))
                    )
                } else {
                    libraryList
                }
            }
            .background(SearchActivityReader(isActive: $isSearchActive))
            .environment(\.editMode, $editMode)
            .navigationTitle(t("Library", "Библиотека"))
            .searchable(
                text: $searchViewModel.query,
                placement: .navigationBarDrawer(displayMode: .automatic),
                prompt: Text(t("Search recordings...", "Искать в записях..."))
            )
            .onSubmit(of: .search) {
                performSearch()
            }
            .onChange(of: searchViewModel.searchMode) { _, _ in
                guard searchViewModel.hasSearched else { return }
                performSearch()
            }
            .onChange(of: isSearchActive) { _, active in
                if !active {
                    searchViewModel.reset()
                }
            }
            .navigationDestination(isPresented: Binding(
                get: { searchTarget != nil },
                set: { if !$0 { searchTarget = nil } }
            )) {
                if let result = searchTarget {
                    RecordingDetailView(recording: Recording(
                        id: result.recordingId,
                        title: result.recordingTitle,
                        type: result.recordingType,
                        createdAt: Date()
                    ))
                }
            }
            .navigationDestination(isPresented: $showImportedDetail) {
                if let importedRecording {
                    RecordingDetailView(recording: importedRecording)
                }
            }
            .overlay(alignment: .top) {
                if let error = viewModel.error {
                    InlineLibraryBanner(
                        message: error,
                        onDismiss: { viewModel.error = nil }
                    )
                    .padding(.top, 8)
                }
            }
            .overlay(alignment: .bottom) {
                if let operation = viewModel.bulkOperation {
                    BulkOperationBanner(operation: operation)
                        .padding(.bottom, 8)
                }
            }
            .overlay {
                if importViewModel.isUploading {
                    ImportUploadOverlay(filename: importViewModel.uploadingFilename)
                }
            }
            .toolbar {
                if !viewModel.recordings.isEmpty {
                    ToolbarItem(placement: .topBarLeading) {
                        EditButton()
                    }
                }
                ToolbarItem(placement: .primaryAction) {
                    Menu {
                        Button {
                            importViewModel.showFileImporter = true
                        } label: {
                            Label(t("Import Audio File", "Импорт аудио"), systemImage: "square.and.arrow.down")
                        }

                        Button {
                            newFolderName = ""
                            newFolderMovesSelection = false
                            showNewFolderSheet = true
                        } label: {
                            Label(t("New Folder", "Новая папка"), systemImage: "folder.badge.plus")
                        }
                    } label: {
                        Image(systemName: "ellipsis.circle")
                    }
                }
                if isEditing && !selectedRecordingIds.isEmpty {
                    ToolbarItemGroup(placement: .bottomBar) {
                        if !viewModel.folders.isEmpty {
                            Menu {
                                Button(t("Unfiled", "Без папки")) {
                                    bulkMove(to: nil)
                                }
                                ForEach(viewModel.folders) { folder in
                                    Button(folder.name) { bulkMove(to: folder.id) }
                                }
                                Divider()
                                Button(t("New Folder…", "Новая папка…")) {
                                    newFolderName = ""
                                    newFolderMovesSelection = true
                                    showNewFolderSheet = true
                                }
                            } label: {
                                Label(t("Move", "Переместить"), systemImage: "folder")
                            }
                            Spacer()
                        }
                        Text(String(
                            format: t("%d selected", "Выбрано: %d"),
                            selectedRecordingIds.count
                        ))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        Spacer()
                        Button(role: .destructive) {
                            bulkTrash()
                        } label: {
                            Label(t("Trash", "Корзина"), systemImage: "trash")
                        }
                    }
                }
            }
            .fileImporter(
                isPresented: $importViewModel.showFileImporter,
                allowedContentTypes: ImportViewModel.allowedContentTypes,
                allowsMultipleSelection: false
            ) { result in
                switch result {
                case .success(let urls):
                    guard let url = urls.first else { return }
                    importViewModel.handleFileSelection(
                        result: .success(url),
                        apiClient: appState.getAPIClient()
                    )
                case .failure(let error):
                    importViewModel.handleFileSelection(
                        result: .failure(error),
                        apiClient: appState.getAPIClient()
                    )
                }
            }
            .onReceive(importViewModel.$completedRecording) { recording in
                guard let recording else { return }
                Task {
                    await viewModel.loadLibrary(apiClient: appState.getAPIClient())
                }
                importedRecording = recording
                showImportedDetail = true
                importViewModel.reset()
            }
            .alert(
                t("Import Failed", "Не удалось импортировать"),
                isPresented: Binding(
                    get: { importViewModel.errorMessage != nil },
                    set: { if !$0 { importViewModel.errorMessage = nil } }
                )
            ) {
                Button(t("OK", "ОК")) { importViewModel.errorMessage = nil }
            } message: {
                Text(importViewModel.errorMessage ?? "")
            }
            .sheet(isPresented: $showNewFolderSheet) {
                NewFolderSheet(
                    name: $newFolderName,
                    movesSelection: $newFolderMovesSelection,
                    selectionCount: selectedRecordingIds.count,
                    onCreate: { name, moveSelection in
                        Task {
                            let folder = await viewModel.createFolder(name: name, apiClient: appState.getAPIClient())
                            if moveSelection, let folder, !selectedRecordingIds.isEmpty {
                                await viewModel.moveRecordings(
                                    ids: Array(selectedRecordingIds),
                                    to: folder.id,
                                    language: languageManager.current,
                                    apiClient: appState.getAPIClient()
                                )
                                exitEditMode()
                            }
                        }
                    }
                )
                .environmentObject(languageManager)
            }
            .alert(t("Rename Folder", "Переименовать папку"), isPresented: Binding(
                get: { renameFolderTarget != nil },
                set: { if !$0 { renameFolderTarget = nil } }
            )) {
                TextField(t("Folder name", "Имя папки"), text: $folderNameDraft)
                Button(t("Save", "Сохранить")) {
                    if let folder = renameFolderTarget {
                        let name = folderNameDraft
                        Task {
                            await viewModel.renameFolder(id: folder.id, name: name, apiClient: appState.getAPIClient())
                        }
                    }
                    renameFolderTarget = nil
                }
                Button(t("Cancel", "Отмена"), role: .cancel) { renameFolderTarget = nil }
            }
            .alert(t("Rename Recording", "Переименовать запись"), isPresented: Binding(
                get: { renameRecordingTarget != nil },
                set: { if !$0 { renameRecordingTarget = nil } }
            )) {
                TextField(t("Title", "Название"), text: $recordingTitleDraft)
                Button(t("Save", "Сохранить")) {
                    if let recording = renameRecordingTarget {
                        let title = recordingTitleDraft
                        Task {
                            await viewModel.renameRecording(id: recording.id, newTitle: title, apiClient: appState.getAPIClient())
                        }
                    }
                    renameRecordingTarget = nil
                }
                Button(t("Cancel", "Отмена"), role: .cancel) { renameRecordingTarget = nil }
            }
            .confirmationDialog(
                String(format: t("Delete folder \u{201C}%@\u{201D}?", "Удалить папку \u{00AB}%@\u{00BB}?"), showDeleteFolderConfirmation?.name ?? ""),
                isPresented: Binding(
                    get: { showDeleteFolderConfirmation != nil },
                    set: { if !$0 { showDeleteFolderConfirmation = nil } }
                ),
                titleVisibility: .visible
            ) {
                Button(t("Delete Folder", "Удалить папку"), role: .destructive) {
                    if let folder = showDeleteFolderConfirmation {
                        Task {
                            await viewModel.deleteFolder(id: folder.id, apiClient: appState.getAPIClient())
                        }
                    }
                    showDeleteFolderConfirmation = nil
                }
                Button(t("Cancel", "Отмена"), role: .cancel) {
                    showDeleteFolderConfirmation = nil
                }
            } message: {
                Text(t("Recordings in this folder will be moved to Unfiled.", "Записи из этой папки будут перемещены в «Без папки»."))
            }
            .refreshable {
                guard !isScreenshotMode else { return }
                await viewModel.loadLibrary(apiClient: appState.getAPIClient())
            }
            .task {
                if isScreenshotMode {
                    viewModel.loadScreenshotFixtures()
                } else {
                    await viewModel.loadLibrary(apiClient: appState.getAPIClient())
                }
            }
            .onReceive(NotificationCenter.default.publisher(for: .pendingRecordingSyncDidFinish)) { _ in
                guard !isScreenshotMode else { return }
                Task {
                    await viewModel.loadLibrary(apiClient: appState.getAPIClient())
                }
            }
            .onChange(of: viewModel.error) { _, newValue in
                errorAutoDismissTask?.cancel()
                guard newValue != nil else { return }

                errorAutoDismissTask = Task {
                    try? await Task.sleep(for: .seconds(6))
                    guard !Task.isCancelled else { return }
                    await MainActor.run {
                        viewModel.error = nil
                    }
                }
            }
            .onDisappear {
                errorAutoDismissTask?.cancel()
            }
        }
    }

    // MARK: - Library List

    private var libraryList: some View {
        List(selection: $selectedRecordingIds) {
            // Folders section
            if !viewModel.folders.isEmpty {
                Section(t("Folders", "Папки")) {
                    ForEach(viewModel.folders) { folder in
                        NavigationLink(destination: FolderRecordingsView(
                            folder: folder,
                            viewModel: viewModel
                        )) {
                            FolderRow(
                                folder: folder,
                                recordingCount: viewModel.recordingsInFolder(folder.id).count
                            )
                        }
                        .selectionDisabled(true)
                        .swipeActions(edge: .trailing) {
                            Button(role: .destructive) {
                                showDeleteFolderConfirmation = folder
                            } label: {
                                Label(t("Delete", "Удалить"), systemImage: "trash")
                            }
                        }
                        .contextMenu {
                            Button {
                                folderNameDraft = folder.name
                                renameFolderTarget = folder
                            } label: {
                                Label(t("Rename", "Переименовать"), systemImage: "pencil")
                            }
                            Button(role: .destructive) {
                                showDeleteFolderConfirmation = folder
                            } label: {
                                Label(t("Delete", "Удалить"), systemImage: "trash")
                            }
                        }
                    }
                }
            }

            // Recordings section (unfiled / all depending on folders)
            Section(viewModel.folders.isEmpty ? t("Recordings", "Записи") : t("Unfiled", "Без папки")) {
                ForEach(viewModel.filteredUnfiledRecordings) { recording in
                    recordingRowLink(recording)
                        .tag(recording.id)
                }
            }

            // Trash section
            if !viewModel.trashedRecordings.isEmpty {
                Section {
                    NavigationLink(destination: TrashView(viewModel: viewModel)) {
                        HStack {
                            Image(systemName: "trash")
                                .foregroundStyle(.red)
                            Text(t("Trash", "Корзина"))
                            Spacer()
                            Text("\(viewModel.trashedRecordings.count)")
                                .foregroundStyle(.secondary)
                                .font(.caption)
                        }
                    }
                    .selectionDisabled(true)
                }
            }
        }
    }

    @ViewBuilder
    private func recordingRowLink(_ recording: Recording) -> some View {
        NavigationLink(destination: RecordingDetailView(
            recording: recording,
            folders: viewModel.folders,
            onMoveToFolder: { folderId in
                Task {
                    await viewModel.moveRecording(
                        id: recording.id,
                        to: folderId,
                        apiClient: appState.getAPIClient()
                    )
                }
            },
            onTrash: {
                Task {
                    await viewModel.trashRecording(
                        id: recording.id,
                        apiClient: appState.getAPIClient()
                    )
                }
            },
            onDidRename: {
                Task { await viewModel.loadLibrary(apiClient: appState.getAPIClient()) }
            }
        )) {
            RecordingRow(
                recording: recording,
                hasLocalRecoveryBackup: viewModel.localRecoveryRecordingIDs.contains(recording.id),
                hasPermanentLocalFailure: viewModel.permanentLocalFailureRecordingIDs.contains(recording.id)
            )
        }
        .swipeActions(edge: .trailing) {
            Button(role: .destructive) {
                Task {
                    await viewModel.trashRecording(
                        id: recording.id,
                        apiClient: appState.getAPIClient()
                    )
                }
            } label: {
                Label(t("Trash", "Корзина"), systemImage: "trash")
            }
        }
        .contextMenu {
            recordingContextMenu(for: recording)
        }
    }

    // MARK: - Context Menu

    @ViewBuilder
    private func recordingContextMenu(for recording: Recording) -> some View {
        Button {
            recordingTitleDraft = recording.title ?? ""
            renameRecordingTarget = recording
        } label: {
            Label(t("Rename", "Переименовать"), systemImage: "pencil")
        }

        if !viewModel.folders.isEmpty {
            Menu(t("Move to Folder", "Переместить в папку")) {
                if recording.folderId != nil {
                    Button(t("Unfiled", "Без папки")) {
                        Task {
                            await viewModel.moveRecording(
                                id: recording.id,
                                to: nil,
                                apiClient: appState.getAPIClient()
                            )
                        }
                    }
                }

                ForEach(viewModel.folders) { folder in
                    if recording.folderId != folder.id {
                        Button(folder.name) {
                            Task {
                                await viewModel.moveRecording(
                                    id: recording.id,
                                    to: folder.id,
                                    apiClient: appState.getAPIClient()
                                )
                            }
                        }
                    }
                }
            }
        }

        Button(role: .destructive) {
            Task {
                await viewModel.trashRecording(
                    id: recording.id,
                    apiClient: appState.getAPIClient()
                )
            }
        } label: {
            Label(t("Move to Trash", "Переместить в корзину"), systemImage: "trash")
        }
    }

    // MARK: - Bulk Helpers

    private func bulkTrash() {
        let ids = Array(selectedRecordingIds)
        Task {
            await viewModel.trashRecordings(ids: ids, language: languageManager.current, apiClient: appState.getAPIClient())
            exitEditMode()
        }
    }

    private func bulkMove(to folderId: String?) {
        let ids = Array(selectedRecordingIds)
        Task {
            await viewModel.moveRecordings(ids: ids, to: folderId, language: languageManager.current, apiClient: appState.getAPIClient())
            exitEditMode()
        }
    }

    private func exitEditMode() {
        selectedRecordingIds.removeAll()
        editMode = .inactive
    }

    // MARK: - Search

    private func performSearch() {
        guard !searchViewModel.query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        #if DEBUG
        if let response = appState.uiTestSearchResponse(query: searchViewModel.query) {
            searchViewModel.applySearchResponse(response)
            return
        }
        #endif
        Task {
            await searchViewModel.search(apiClient: appState.getAPIClient())
        }
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

// MARK: - Search Activity Reader

/// Bridges SwiftUI's `\.isSearching` environment value (only readable from a
/// view inside the `.searchable` container) out to a binding the parent owns,
/// so `LibraryView` can swap its content between the list and search results.
private struct SearchActivityReader: View {
    @Environment(\.isSearching) private var isSearching
    @Binding var isActive: Bool

    var body: some View {
        Color.clear
            .onChange(of: isSearching) { _, searching in
                isActive = searching
            }
    }
}

// MARK: - Folder Row

struct FolderRow: View {
    let folder: Folder
    let recordingCount: Int

    var body: some View {
        HStack {
            Image(systemName: "folder.fill")
                .foregroundStyle(.orange)
            Text(folder.name)
                .font(.body)
            Spacer()
            Text("\(recordingCount)")
                .foregroundStyle(.secondary)
                .font(.caption)
        }
        .padding(.vertical, 2)
    }
}

// MARK: - Folder Recordings View

struct FolderRecordingsView: View {
    @EnvironmentObject var appState: AppState
    @EnvironmentObject private var languageManager: LanguageManager
    let folder: Folder
    @ObservedObject var viewModel: LibraryViewModel
    @State private var editMode: EditMode = .inactive
    @State private var selection = Set<String>()

    private var isEditing: Bool { editMode == .active }

    var body: some View {
        let folderRecordings = viewModel.filteredRecordingsInFolder(folder.id)

        Group {
            if folderRecordings.isEmpty {
                ContentUnavailableView(
                    t("No Recordings", "Нет записей"),
                    systemImage: "folder",
                    description: Text(t("Move recordings here from the library", "Перемести записи сюда из библиотеки"))
                )
            } else {
                List(selection: $selection) {
                    ForEach(folderRecordings) { recording in
                        NavigationLink(destination: RecordingDetailView(
                            recording: recording,
                            folders: viewModel.folders,
                            onMoveToFolder: { folderId in
                                Task {
                                    await viewModel.moveRecording(
                                        id: recording.id,
                                        to: folderId,
                                        apiClient: appState.getAPIClient()
                                    )
                                }
                            },
                            onTrash: {
                                Task {
                                    await viewModel.trashRecording(
                                        id: recording.id,
                                        apiClient: appState.getAPIClient()
                                    )
                                }
                            },
                            onDidRename: {
                                Task { await viewModel.loadLibrary(apiClient: appState.getAPIClient()) }
                            }
                        )) {
                            RecordingRow(
                                recording: recording,
                                hasLocalRecoveryBackup: viewModel.localRecoveryRecordingIDs.contains(recording.id),
                                hasPermanentLocalFailure: viewModel.permanentLocalFailureRecordingIDs.contains(recording.id)
                            )
                        }
                        .tag(recording.id)
                        .swipeActions(edge: .trailing) {
                            Button(role: .destructive) {
                                Task {
                                    await viewModel.trashRecording(
                                        id: recording.id,
                                        apiClient: appState.getAPIClient()
                                    )
                                }
                            } label: {
                                Label(t("Trash", "Корзина"), systemImage: "trash")
                            }
                        }
                        .swipeActions(edge: .leading) {
                            Button {
                                Task {
                                    await viewModel.moveRecording(
                                        id: recording.id,
                                        to: nil,
                                        apiClient: appState.getAPIClient()
                                    )
                                }
                            } label: {
                                Label(t("Unfiled", "Без папки"), systemImage: "tray")
                            }
                            .tint(.blue)
                        }
                        .contextMenu {
                            Menu(t("Move to Folder", "Переместить в папку")) {
                                Button(t("Unfiled", "Без папки")) {
                                    Task {
                                        await viewModel.moveRecording(
                                            id: recording.id,
                                            to: nil,
                                            apiClient: appState.getAPIClient()
                                        )
                                    }
                                }

                                ForEach(viewModel.folders) { f in
                                    if f.id != folder.id {
                                        Button(f.name) {
                                            Task {
                                                await viewModel.moveRecording(
                                                    id: recording.id,
                                                    to: f.id,
                                                    apiClient: appState.getAPIClient()
                                                )
                                            }
                                        }
                                    }
                                }
                            }

                            Button(role: .destructive) {
                                Task {
                                    await viewModel.trashRecording(
                                        id: recording.id,
                                        apiClient: appState.getAPIClient()
                                    )
                                }
                            } label: {
                                Label(t("Move to Trash", "Переместить в корзину"), systemImage: "trash")
                            }
                        }
                    }
                }
            }
        }
        .environment(\.editMode, $editMode)
        .navigationTitle(folder.name)
        .toolbar {
            if !folderRecordings.isEmpty {
                ToolbarItem(placement: .primaryAction) {
                    EditButton()
                }
            }
            if isEditing && !selection.isEmpty {
                ToolbarItemGroup(placement: .bottomBar) {
                    Button(t("Unfiled", "Без папки")) {
                        let ids = Array(selection)
                        Task {
                            await viewModel.moveRecordings(ids: ids, to: nil, language: languageManager.current, apiClient: appState.getAPIClient())
                            selection.removeAll()
                            editMode = .inactive
                        }
                    }
                    Spacer()
                    Button(role: .destructive) {
                        let ids = Array(selection)
                        Task {
                            await viewModel.trashRecordings(ids: ids, language: languageManager.current, apiClient: appState.getAPIClient())
                            selection.removeAll()
                            editMode = .inactive
                        }
                    } label: {
                        Label(t("Trash", "Корзина"), systemImage: "trash")
                    }
                }
            }
        }
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

// MARK: - Trash View

struct TrashView: View {
    @EnvironmentObject var appState: AppState
    @EnvironmentObject private var languageManager: LanguageManager
    @ObservedObject var viewModel: LibraryViewModel
    @State private var showEmptyTrashConfirmation = false
    @State private var showBulkDeleteConfirmation = false
    @State private var editMode: EditMode = .inactive
    @State private var selection = Set<String>()

    private var isEditing: Bool { editMode == .active }

    var body: some View {
        Group {
            if viewModel.trashedRecordings.isEmpty {
                ContentUnavailableView(
                    t("Trash is Empty", "Корзина пуста"),
                    systemImage: "trash",
                    description: Text(t("Deleted recordings will appear here", "Удаленные записи появятся здесь"))
                )
            } else {
                List(selection: $selection) {
                    ForEach(viewModel.trashedRecordings) { recording in
                        NavigationLink(destination: RecordingDetailView(
                            recording: recording,
                            isTrash: true,
                            onRestore: {
                                Task {
                                    await viewModel.restoreRecording(
                                        id: recording.id,
                                        apiClient: appState.getAPIClient()
                                    )
                                }
                            },
                            onPermanentDelete: {
                                Task {
                                    await viewModel.permanentlyDeleteRecording(
                                        id: recording.id,
                                        apiClient: appState.getAPIClient()
                                    )
                                }
                            }
                        )) {
                            RecordingRow(
                                recording: recording,
                                hasLocalRecoveryBackup: viewModel.localRecoveryRecordingIDs.contains(recording.id),
                                hasPermanentLocalFailure: viewModel.permanentLocalFailureRecordingIDs.contains(recording.id)
                            )
                        }
                        .tag(recording.id)
                        .swipeActions(edge: .trailing) {
                            Button(role: .destructive) {
                                Task {
                                    await viewModel.permanentlyDeleteRecording(
                                        id: recording.id,
                                        apiClient: appState.getAPIClient()
                                    )
                                }
                            } label: {
                                Label(t("Delete", "Удалить"), systemImage: "trash.slash")
                            }
                        }
                        .swipeActions(edge: .leading) {
                            Button {
                                Task {
                                    await viewModel.restoreRecording(
                                        id: recording.id,
                                        apiClient: appState.getAPIClient()
                                    )
                                }
                            } label: {
                                Label(t("Restore", "Восстановить"), systemImage: "arrow.uturn.backward")
                            }
                            .tint(.green)
                        }
                    }
                }
            }
        }
        .environment(\.editMode, $editMode)
        .overlay(alignment: .bottom) {
            if let operation = viewModel.bulkOperation {
                BulkOperationBanner(operation: operation)
                    .padding(.bottom, 8)
            }
        }
        .navigationTitle(t("Trash", "Корзина"))
        .toolbar {
            if !viewModel.trashedRecordings.isEmpty {
                ToolbarItem(placement: .topBarLeading) {
                    EditButton()
                }
                ToolbarItem(placement: .primaryAction) {
                    Button(t("Empty Trash", "Очистить корзину"), role: .destructive) {
                        showEmptyTrashConfirmation = true
                    }
                    .foregroundStyle(.red)
                }
            }
            if isEditing && !selection.isEmpty {
                ToolbarItemGroup(placement: .bottomBar) {
                    Button(t("Restore", "Восстановить")) {
                        let ids = Array(selection)
                        Task {
                            await viewModel.restoreRecordings(ids: ids, language: languageManager.current, apiClient: appState.getAPIClient())
                            selection.removeAll()
                            editMode = .inactive
                        }
                    }
                    Spacer()
                    Button(role: .destructive) {
                        showBulkDeleteConfirmation = true
                    } label: {
                        Label(t("Delete", "Удалить"), systemImage: "trash.slash")
                    }
                }
            }
        }
        .confirmationDialog(
            t("Empty Trash?", "Очистить корзину?"),
            isPresented: $showEmptyTrashConfirmation,
            titleVisibility: .visible
        ) {
            Button(t("Delete All Permanently", "Удалить все навсегда"), role: .destructive) {
                Task {
                    await viewModel.emptyTrash(apiClient: appState.getAPIClient())
                }
            }
            Button(t("Cancel", "Отмена"), role: .cancel) {}
        } message: {
            Text(String(
                format: t(
                    "This will permanently delete %d recordings. This cannot be undone.",
                    "Это навсегда удалит записей: %d. Это действие нельзя отменить."
                ),
                viewModel.trashedRecordings.count
            ))
        }
        .confirmationDialog(
            t("Delete selected permanently?", "Удалить выбранные навсегда?"),
            isPresented: $showBulkDeleteConfirmation,
            titleVisibility: .visible
        ) {
            Button(t("Delete Permanently", "Удалить навсегда"), role: .destructive) {
                let ids = Array(selection)
                Task {
                    await viewModel.permanentlyDeleteRecordings(ids: ids, apiClient: appState.getAPIClient())
                    selection.removeAll()
                    editMode = .inactive
                }
            }
            Button(t("Cancel", "Отмена"), role: .cancel) {}
        } message: {
            Text(t("This action cannot be undone.", "Это действие нельзя отменить."))
        }
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

// MARK: - Inline Banner

private struct InlineLibraryBanner: View {
    let message: String
    let onDismiss: () -> Void
    @EnvironmentObject private var languageManager: LanguageManager

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "wifi.exclamationmark")
                .foregroundStyle(.white)

            Text(message)
                .font(.caption)
                .foregroundStyle(.white)
                .lineLimit(2)

            Spacer(minLength: 8)

            Button(action: onDismiss) {
                Image(systemName: "xmark")
                    .foregroundStyle(.white.opacity(0.9))
            }
            .buttonStyle(.plain)
            .accessibilityLabel(OnboardingL10n.text("Dismiss", "Закрыть", language: languageManager.current))
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .background(Color.orange)
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .shadow(color: .black.opacity(0.15), radius: 10, y: 4)
        .padding(.horizontal)
        .accessibilityIdentifier("library-inline-error-banner")
    }
}

// MARK: - New Folder Sheet

private struct NewFolderSheet: View {
    @Binding var name: String
    @Binding var movesSelection: Bool
    let selectionCount: Int
    let onCreate: (String, Bool) -> Void

    @EnvironmentObject private var languageManager: LanguageManager
    @Environment(\.dismiss) private var dismiss
    @FocusState private var nameFocused: Bool

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField(t("Folder name", "Имя папки"), text: $name)
                        .focused($nameFocused)
                }
                if selectionCount > 0 {
                    Section {
                        Toggle(
                            String(format: t("Move %d selected here", "Переместить сюда выбранные: %d"), selectionCount),
                            isOn: $movesSelection
                        )
                    }
                }
            }
            .navigationTitle(t("New Folder", "Новая папка"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(t("Cancel", "Отмена")) { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(t("Create", "Создать")) {
                        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
                        guard !trimmed.isEmpty else { return }
                        onCreate(trimmed, movesSelection)
                        dismiss()
                    }
                    .disabled(name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
            .onAppear { nameFocused = true }
        }
        .presentationDetents([.medium])
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

// MARK: - Bulk Operation Banner

private struct BulkOperationBanner: View {
    let operation: LibraryBulkOperation
    @EnvironmentObject private var languageManager: LanguageManager

    var body: some View {
        HStack(spacing: 12) {
            ProgressView()
                .controlSize(.small)
            Text(label)
                .font(.caption)
                .foregroundStyle(.primary)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .background(.ultraThinMaterial)
        .clipShape(Capsule())
        .shadow(color: .black.opacity(0.12), radius: 8, y: 3)
        .accessibilityIdentifier("library-bulk-operation-banner")
    }

    private var label: String {
        let verb: String
        switch operation.kind {
        case .moving:
            verb = t("Moving", "Перемещаем")
        case .movingToTrash:
            verb = t("Moving to Trash", "Перемещаем в корзину")
        case .restoring:
            verb = t("Restoring", "Восстанавливаем")
        case .deletingPermanently:
            verb = t("Deleting", "Удаляем")
        }
        if operation.isDeterminate {
            return String(format: "%@ %d/%d", verb, operation.completedCount, operation.totalCount)
        }
        return "\(verb)…"
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

// MARK: - Recording Row

struct RecordingRow: View {
    let recording: Recording
    var hasLocalRecoveryBackup: Bool = false
    var hasPermanentLocalFailure: Bool = false
    @EnvironmentObject private var languageManager: LanguageManager

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(recording.title ?? t("Untitled", "Без названия"))
                .font(.headline)

            if let statusText = recording.statusDisplayText(
                hasLocalRecoveryBackup: hasLocalRecoveryBackup,
                hasPermanentLocalFailure: hasPermanentLocalFailure,
                languageCode: speakerLanguageCode
            ) {
                Text(statusText)
                    .font(.caption)
                    .foregroundStyle(statusColor)
                    .lineLimit(1)
            }

            if let failurePreviewText = recording.failurePreviewText,
               recording.isFailedUpload {
                Text(failurePreviewText)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }

            HStack {
                Text(recording.createdAt.formatted(date: .abbreviated, time: .shortened))
                    .font(.caption)
                    .foregroundStyle(.secondary)

                if let duration = recording.durationSeconds {
                    Text("\u{2022}")
                        .foregroundStyle(.secondary)
                    Text(formatDuration(duration))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .padding(.vertical, 4)
    }

    private func formatDuration(_ seconds: Int) -> String {
        let minutes = seconds / 60
        let remainingSeconds = seconds % 60
        return String(format: "%d:%02d", minutes, remainingSeconds)
    }

    private var statusColor: Color {
        if recording.isFailedUpload || hasPermanentLocalFailure {
            return .red
        }
        return .secondary
    }

    private var speakerLanguageCode: String {
        switch languageManager.current {
        case .followSystem:
            return languageManager.preferredLocale.identifier
        case .english, .russian:
            return languageManager.current.rawValue
        }
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

// MARK: - Bulk Operations

enum LibraryBulkOperationKind: Equatable {
    case moving
    case movingToTrash
    case restoring
    case deletingPermanently
}

struct LibraryBulkOperation: Equatable {
    let kind: LibraryBulkOperationKind
    let totalCount: Int
    var completedCount: Int

    var isDeterminate: Bool {
        completedCount > 0 && totalCount > 0
    }
}

// MARK: - ViewModel

@MainActor
class LibraryViewModel: ObservableObject {
    @Published var recordings: [Recording] = []
    @Published var trashedRecordings: [Recording] = []
    @Published var folders: [Folder] = []
    @Published private(set) var localRecoveryRecordingIDs: Set<String> = []
    /// Recordings whose local backup hit a permanent sync failure (e.g. deleted
    /// on the server). Surfaced as "needs attention" rather than "saved locally".
    @Published private(set) var permanentLocalFailureRecordingIDs: Set<String> = []
    @Published private(set) var bulkOperation: LibraryBulkOperation?
    @Published var isLoading = false
    @Published var error: String?
    private var loadGeneration = 0
    private var processingRefreshTask: Task<Void, Never>?

    deinit {
        processingRefreshTask?.cancel()
    }

    var filteredUnfiledRecordings: [Recording] {
        recordings.filter { $0.folderId == nil }
    }

    func filteredRecordingsInFolder(_ folderId: String) -> [Recording] {
        recordings.filter { $0.folderId == folderId }
    }

    func recordingsInFolder(_ folderId: String) -> [Recording] {
        recordings.filter { $0.folderId == folderId }
    }

    func loadLibrary(apiClient: APIClient) async {
        let hasExistingContent = !recordings.isEmpty || !trashedRecordings.isEmpty || !folders.isEmpty
        loadGeneration += 1
        let generation = loadGeneration
        isLoading = true
        error = nil

        defer {
            if generation == loadGeneration {
                isLoading = false
            }
        }

        do {
            async let active = apiClient.listRecordings(limit: 100)
            async let trashed = apiClient.listRecordings(limit: 100, trashed: true)
            async let folderList = apiClient.listFolders()

            let fetchedRecordings = try await active
            let fetchedTrashed = try await trashed
            let fetchedFolders = try await folderList
            let backupManifests = (try? RecordingBackupStore.manifestsByRecordingId()) ?? [:]
            guard generation == loadGeneration else { return }

            recordings = fetchedRecordings
            trashedRecordings = fetchedTrashed
            folders = fetchedFolders
            localRecoveryRecordingIDs = Set(
                backupManifests.compactMap { element in
                    element.value.syncState != .remoteReady ? element.key : nil
                }
            )
            permanentLocalFailureRecordingIDs = Set(
                backupManifests.compactMap { element in
                    element.value.isPermanentFailure ? element.key : nil
                }
            )

            processingRefreshTask?.cancel()

            if fetchedRecordings.contains(where: { $0.status == .pendingUpload || $0.status == .uploading }) {
                await PendingRecordingSyncCoordinator.shared.scheduleSync(using: apiClient)
            }
            if fetchedRecordings.contains(where: shouldBackgroundRefresh) {
                processingRefreshTask = Task { [weak self] in
                    try? await Task.sleep(for: .seconds(4))
                    guard !Task.isCancelled else { return }
                    await self?.loadLibrary(apiClient: apiClient)
                }
            }
        } catch {
            guard generation == loadGeneration else { return }
            if hasExistingContent {
                print("Library refresh failed: \(error.localizedDescription)")
                if recordings.contains(where: shouldBackgroundRefresh) {
                    self.error = error.userFacingMessage(context: .library)
                    processingRefreshTask?.cancel()
                    processingRefreshTask = Task { [weak self] in
                        try? await Task.sleep(for: .seconds(6))
                        guard !Task.isCancelled else { return }
                        await self?.loadLibrary(apiClient: apiClient)
                    }
                }
            } else {
                self.error = error.userFacingMessage(context: .library)
            }
        }
    }

    func loadScreenshotFixtures() {
        #if DEBUG
        recordings = IOSScreenshotFixtures.recordings
        trashedRecordings = []
        folders = []
        localRecoveryRecordingIDs = []
        permanentLocalFailureRecordingIDs = []
        isLoading = false
        error = nil
        #endif
    }

    // MARK: - Folder Operations

    @discardableResult
    func createFolder(name: String, apiClient: APIClient) async -> Folder? {
        do {
            let folder = try await apiClient.createFolder(name: name)
            folders.append(folder)
            folders.sort { $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending }
            return folder
        } catch {
            self.error = error.userFacingMessage(context: .library)
            return nil
        }
    }

    func renameFolder(id: String, name: String, apiClient: APIClient) async {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        do {
            _ = try await apiClient.updateFolder(id: id, name: trimmed)
            await loadLibrary(apiClient: apiClient)
        } catch {
            self.error = error.userFacingMessage(context: .library)
        }
    }

    func deleteFolder(id: String, apiClient: APIClient) async {
        do {
            try await apiClient.deleteFolder(id: id)
            folders.removeAll { $0.id == id }
            await loadLibrary(apiClient: apiClient)
        } catch {
            self.error = error.userFacingMessage(context: .library)
        }
    }

    func renameRecording(id: String, newTitle: String, apiClient: APIClient) async {
        let trimmed = newTitle.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        do {
            _ = try await apiClient.updateRecording(id: id, title: trimmed)
            await loadLibrary(apiClient: apiClient)
        } catch {
            self.error = error.userFacingMessage(context: .library)
        }
    }

    // MARK: - Bulk Operations

    func trashRecordings(ids: [String], language: LanguageManager.SupportedLanguage, apiClient: APIClient) async {
        guard !ids.isEmpty else { return }
        await runBulkOperation(ids: ids, kind: .movingToTrash, action: .delete, folderId: nil, language: language, apiClient: apiClient)
    }

    func moveRecordings(ids: [String], to folderId: String?, language: LanguageManager.SupportedLanguage, apiClient: APIClient) async {
        guard !ids.isEmpty else { return }
        await runBulkOperation(ids: ids, kind: .moving, action: .move, folderId: folderId, language: language, apiClient: apiClient)
    }

    func restoreRecordings(ids: [String], language: LanguageManager.SupportedLanguage, apiClient: APIClient) async {
        guard !ids.isEmpty else { return }
        await runBulkOperation(ids: ids, kind: .restoring, action: .restore, folderId: nil, language: language, apiClient: apiClient)
    }

    func permanentlyDeleteRecordings(ids: [String], apiClient: APIClient) async {
        guard !ids.isEmpty else { return }
        error = nil
        bulkOperation = LibraryBulkOperation(kind: .deletingPermanently, totalCount: ids.count, completedCount: 0)
        defer { bulkOperation = nil }

        var completedCount = 0
        for id in ids {
            do {
                try await apiClient.deleteRecording(id: id, permanent: true)
                trashedRecordings.removeAll { $0.id == id }
                completedCount += 1
                updateBulkOperationCompletedCount(completedCount)
            } catch {
                self.error = error.userFacingMessage(context: .library)
                await loadLibrary(apiClient: apiClient)
                return
            }
        }
        await loadLibrary(apiClient: apiClient)
    }

    private func runBulkOperation(
        ids: [String],
        kind: LibraryBulkOperationKind,
        action: BulkRecordingAction,
        folderId: String?,
        language: LanguageManager.SupportedLanguage,
        apiClient: APIClient
    ) async {
        error = nil
        bulkOperation = LibraryBulkOperation(kind: kind, totalCount: ids.count, completedCount: 0)
        defer { bulkOperation = nil }

        do {
            let result = try await apiClient.bulkRecordingOperation(
                recordingIds: ids,
                action: action,
                folderId: folderId
            )
            updateBulkOperationCompletedCount(result.processed)
            let partialFailureMessage: String? = result.failed > 0
                ? String(
                    format: OnboardingL10n.text(
                        "Processed %d of %d. Failed: %d.",
                        "Обработано %d из %d. Не удалось: %d.",
                        language: language
                    ),
                    result.processed, ids.count, result.failed
                )
                : nil
            await loadLibrary(apiClient: apiClient)
            if let partialFailureMessage {
                error = partialFailureMessage
            }
        } catch {
            self.error = error.userFacingMessage(context: .library)
        }
    }

    private func updateBulkOperationCompletedCount(_ completedCount: Int) {
        guard var operation = bulkOperation else { return }
        operation.completedCount = completedCount
        bulkOperation = operation
    }

    // MARK: - Recording Operations

    func moveRecording(id: String, to folderId: String?, apiClient: APIClient) async {
        do {
            _ = try await apiClient.moveRecording(id: id, folderId: folderId)
            await loadLibrary(apiClient: apiClient)
        } catch {
            self.error = error.userFacingMessage(context: .library)
        }
    }

    func trashRecording(id: String, apiClient: APIClient) async {
        do {
            try await apiClient.deleteRecording(id: id)
            recordings.removeAll { $0.id == id }
            await loadLibrary(apiClient: apiClient)
        } catch {
            self.error = error.userFacingMessage(context: .library)
        }
    }

    func restoreRecording(id: String, apiClient: APIClient) async {
        do {
            _ = try await apiClient.restoreRecording(id: id)
            trashedRecordings.removeAll { $0.id == id }
            await loadLibrary(apiClient: apiClient)
        } catch {
            self.error = error.userFacingMessage(context: .library)
        }
    }

    func permanentlyDeleteRecording(id: String, apiClient: APIClient) async {
        do {
            try await apiClient.deleteRecording(id: id, permanent: true)
            trashedRecordings.removeAll { $0.id == id }
        } catch {
            self.error = error.userFacingMessage(context: .library)
        }
    }

    func emptyTrash(apiClient: APIClient) async {
        let ids = trashedRecordings.map(\.id)
        for id in ids {
            do {
                try await apiClient.deleteRecording(id: id, permanent: true)
                trashedRecordings.removeAll { $0.id == id }
            } catch {
                self.error = error.userFacingMessage(context: .library)
                return
            }
        }
    }

    private func shouldBackgroundRefresh(for recording: Recording) -> Bool {
        switch recording.status {
        case .pendingUpload, .uploading, .processing:
            return true
        case .ready, .failed:
            return false
        }
    }
}

// MARK: - Import Upload Overlay

private struct ImportUploadOverlay: View {
    let filename: String?
    @EnvironmentObject private var languageManager: LanguageManager

    var body: some View {
        ZStack {
            Color.black.opacity(0.4)
                .ignoresSafeArea()

            VStack(spacing: 16) {
                ProgressView()
                    .controlSize(.large)

                if let filename {
                    Text(String(format: t("Uploading %@...", "Загрузка %@..."), filename))
                        .font(.headline)
                        .foregroundStyle(.primary)
                }

                Text(t("The server will transcribe automatically", "Сервер расшифрует автоматически"))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .padding(32)
            .background(.ultraThinMaterial)
            .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
            .shadow(color: .black.opacity(0.15), radius: 20, y: 8)
        }
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

#Preview {
    LibraryView()
        .environmentObject(AppState())
        .environmentObject(LanguageManager.shared)
}
