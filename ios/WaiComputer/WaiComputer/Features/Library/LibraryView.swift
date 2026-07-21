import SwiftUI
import UniformTypeIdentifiers
import WaiComputerKit

struct LibraryView: View {
    @EnvironmentObject var appState: AppState
    @EnvironmentObject private var languageManager: LanguageManager
    @Environment(\.horizontalSizeClass) private var libraryHorizontalSizeClass
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
    @State private var selectedLibraryRecordingId: String?

    private var isScreenshotMode: Bool {
        IOSTestingMode.current.isScreenshot
    }

    private var isEditing: Bool {
        editMode == .active
    }

    private var isRegularWidth: Bool {
        libraryHorizontalSizeClass == .regular
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
                    ProgressView(t("Loading recordings…", "Загрузка записей…"))
                } else if viewModel.recordings.isEmpty && viewModel.trashedRecordings.isEmpty && viewModel.folders.isEmpty {
                    ContentUnavailableView(
                        t("No Recordings", "Нет записей"),
                        systemImage: "waveform",
                        description: Text(t("Start recording to see your notes here", "Начни запись, чтобы увидеть заметки здесь"))
                    )
                } else {
                    libraryContent
                }
            }
            .background(SearchActivityReader(isActive: $isSearchActive))
            .environment(\.editMode, $editMode)
            .navigationTitle(t("Library", "Библиотека"))
            .navigationBarTitleDisplayMode(isRegularWidth ? .inline : .large)
            .searchable(
                text: $searchViewModel.query,
                placement: .navigationBarDrawer(displayMode: .automatic),
                prompt: Text(t("Search recordings…", "Искать в записях…"))
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
                    RecordingDetailView(
                        recording: Recording(
                            id: result.recordingId,
                            title: result.recordingTitle,
                            type: result.recordingType,
                            createdAt: Date()
                        ),
                        onTrash: {
                            let id = result.recordingId
                            Task {
                                await viewModel.trashRecording(
                                    id: id,
                                    apiClient: appState.getAPIClient()
                                )
                                // Refresh the search surface so the trashed
                                // result no longer appears behind the dismiss.
                                performSearch()
                            }
                        },
                        onDetailChange: { detail in
                            viewModel.applyRecordingDetail(detail)
                        }
                    )
                }
            }
            .navigationDestination(isPresented: $showImportedDetail) {
                if let importedRecording {
                    RecordingDetailView(
                        recording: importedRecording,
                        onDetailChange: { detail in
                            viewModel.applyRecordingDetail(detail)
                            if importedRecording.id == detail.id {
                                self.importedRecording = Recording(detail: detail)
                            }
                        }
                    )
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
                            Label(t("Import Audio or Video", "Импорт аудио или видео"), systemImage: "square.and.arrow.down")
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
            .onChange(of: viewModel.recordings.map(\.id)) { _, visibleIds in
                reconcileLibrarySelection(visibleIds)
            }
            .onDisappear {
                errorAutoDismissTask?.cancel()
            }
        }
    }

    // MARK: - Library List

    @ViewBuilder
    private var libraryContent: some View {
        if isRegularWidth {
            regularLibraryLayout
        } else {
            compactLibraryList
        }
    }

    private var compactLibraryList: some View {
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
                                folder: folder
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
                                .foregroundStyle(Palette.danger)
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

    private var regularLibraryLayout: some View {
        HStack(spacing: 0) {
            List(selection: $selectedRecordingIds) {
                if !viewModel.folders.isEmpty {
                    Section(t("Folders", "Папки")) {
                        ForEach(viewModel.folders) { folder in
                            NavigationLink(destination: FolderRecordingsView(
                                folder: folder,
                                viewModel: viewModel
                            )) {
                                FolderRow(folder: folder)
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

                Section(t("Recordings", "Записи")) {
                    ForEach(viewModel.recordings) { recording in
                        regularLibraryRow(for: recording)
                            .tag(recording.id)
                            .swipeActions(edge: .trailing) {
                                Button(role: .destructive) {
                                    Task {
                                        await trashRecording(id: recording.id)
                                    }
                                } label: {
                                    Label(t("Trash", "Корзина"), systemImage: "trash")
                                }
                            }
                            .contextMenu {
                                recordingContextMenu(for: recording)
                            }
                    }
                }

                if !viewModel.trashedRecordings.isEmpty {
                    Section {
                        NavigationLink(destination: TrashView(viewModel: viewModel)) {
                            HStack {
                                Image(systemName: "trash")
                                    .foregroundStyle(Palette.danger)
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
            .listStyle(.plain)
            .scrollContentBackground(.hidden)
            .frame(minWidth: 320, idealWidth: 390, maxWidth: 460, maxHeight: .infinity, alignment: .topLeading)
            .background(Palette.surfaceSubtle)
            .accessibilityIdentifier("ios-library-list-pane")

            Divider()

            regularLibraryDetailPane
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                .background(Color(uiColor: .systemGroupedBackground))
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .accessibilityIdentifier("ios-library-regular-layout")
    }

    @ViewBuilder
    private func regularLibraryRow(for recording: Recording) -> some View {
        if isEditing {
            recordingPlainRow(recording)
        } else {
            Button {
                selectedLibraryRecordingId = recording.id
            } label: {
                recordingPlainRow(recording)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .listRowBackground(selectedLibraryRecordingId == recording.id ? Palette.accentSubtle : Color.clear)
            .accessibilityIdentifier("ios-library-row-\(recording.id)")
        }
    }

    @ViewBuilder
    private var regularLibraryDetailPane: some View {
        if let id = selectedLibraryRecordingId,
           let recording = viewModel.recordings.first(where: { $0.id == id }) {
            recordingDetailView(for: recording)
                .id(id)
                .accessibilityIdentifier("ios-library-detail-pane")
        } else {
            regularLibraryPlaceholder
        }
    }

    private var regularLibraryPlaceholder: some View {
        VStack(spacing: Spacing.lg) {
            Image(systemName: "waveform")
                .font(.system(size: 30, weight: .semibold))
                .foregroundStyle(Palette.accent)
                .frame(width: 64, height: 64)
                .background(Palette.accentSubtle)
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))

            VStack(spacing: Spacing.xxs) {
                Text(t("Select a recording", "Выберите запись"))
                    .font(Typography.displaySmall)
                    .foregroundStyle(Palette.textPrimary)
                    .multilineTextAlignment(.center)
                Text(t(
                    "Open a transcript, summary, or AI-generated details without leaving the library list.",
                    "Откройте расшифровку, сводку или AI-детали, не уходя из списка библиотеки."
                ))
                .font(Typography.bodySmall)
                .foregroundStyle(Palette.textSecondary)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: 420)
            }
        }
        .padding(Spacing.xl)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .accessibilityIdentifier("ios-library-placeholder")
    }

    private func recordingPlainRow(_ recording: Recording) -> some View {
        RecordingRow(
            recording: recording,
            hasLocalRecoveryBackup: viewModel.localRecoveryRecordingIDs.contains(recording.id),
            hasPermanentLocalFailure: viewModel.permanentLocalFailureRecordingIDs.contains(recording.id)
        )
    }

    @ViewBuilder
    private func recordingRowLink(_ recording: Recording) -> some View {
        NavigationLink(destination: recordingDetailView(for: recording)) {
            recordingPlainRow(recording)
        }
        .draggable(IOSInboxDragItem(kind: .recording, id: recording.id))
        .swipeActions(edge: .trailing) {
            Button(role: .destructive) {
                Task {
                    await trashRecording(id: recording.id)
                }
            } label: {
                Label(t("Trash", "Корзина"), systemImage: "trash")
            }
        }
        .contextMenu {
            recordingContextMenu(for: recording)
        }
    }

    private func recordingDetailView(for recording: Recording) -> some View {
        RecordingDetailView(
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
                    await trashRecording(id: recording.id)
                }
            },
            onDetailChange: { detail in
                viewModel.applyRecordingDetail(detail)
            },
            onDidRename: {
                Task { await viewModel.loadLibrary(apiClient: appState.getAPIClient()) }
            }
        )
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
                await trashRecording(id: recording.id)
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
            if let selectedLibraryRecordingId, ids.contains(selectedLibraryRecordingId) {
                self.selectedLibraryRecordingId = nil
            }
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

    private func trashRecording(id: String) async {
        await viewModel.trashRecording(
            id: id,
            apiClient: appState.getAPIClient()
        )
        clearLibrarySelectionIfNeeded(id: id)
    }

    private func clearLibrarySelectionIfNeeded(id: String) {
        selectedRecordingIds.remove(id)
        if selectedLibraryRecordingId == id {
            selectedLibraryRecordingId = nil
        }
    }

    private func reconcileLibrarySelection(_ visibleIds: [String]) {
        let visible = Set(visibleIds)
        selectedRecordingIds = selectedRecordingIds.intersection(visible)
        if let selectedLibraryRecordingId, !visible.contains(selectedLibraryRecordingId) {
            self.selectedLibraryRecordingId = nil
        }
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

    var body: some View {
        HStack {
            Image(systemName: "folder.fill")
                .foregroundStyle(.orange)
            Text(folder.name)
                .font(.body)
            Spacer()
            Text("\(folder.itemCount)")
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
    @State private var renameRecordingTarget: Recording?
    @State private var recordingTitleDraft = ""

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
                            onDetailChange: { detail in
                                viewModel.applyRecordingDetail(detail)
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
                        .draggable(IOSInboxDragItem(kind: .recording, id: recording.id))
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
                            .tint(Palette.accent)
                        }
                        .contextMenu {
                            Button {
                                recordingTitleDraft = recording.title ?? ""
                                renameRecordingTarget = recording
                            } label: {
                                Label(t("Rename", "Переименовать"), systemImage: "pencil")
                            }

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
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

// MARK: - Trash View

struct TrashView: View {
    @EnvironmentObject var appState: AppState
    @EnvironmentObject private var languageManager: LanguageManager
    @Environment(\.horizontalSizeClass) private var trashHorizontalSizeClass
    @ObservedObject var viewModel: LibraryViewModel
    @State private var showEmptyTrashConfirmation = false
    @State private var showBulkDeleteConfirmation = false
    @State private var editMode: EditMode = .inactive
    @State private var selection = Set<String>()
    @State private var selectedTrashRecordingId: String?

    private var isEditing: Bool { editMode == .active }
    private var isRegularWidth: Bool { trashHorizontalSizeClass == .regular }

    var body: some View {
        Group {
            if viewModel.trashedRecordings.isEmpty {
                ContentUnavailableView(
                    t("Trash is Empty", "Корзина пуста"),
                    systemImage: "trash",
                    description: Text(t("Deleted recordings will appear here", "Удаленные записи появятся здесь"))
                )
                .accessibilityIdentifier("ios-trash-empty")
            } else if isRegularWidth {
                regularTrashLayout
            } else {
                compactTrashList
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
        .navigationBarTitleDisplayMode(isRegularWidth ? .inline : .large)
        .toolbar {
            if !viewModel.trashedRecordings.isEmpty {
                ToolbarItem(placement: .topBarLeading) {
                    EditButton()
                }
                ToolbarItem(placement: .primaryAction) {
                    Button(t("Empty Trash", "Очистить корзину"), role: .destructive) {
                        showEmptyTrashConfirmation = true
                    }
                    .foregroundStyle(Palette.danger)
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
                    selectedTrashRecordingId = nil
                    selection.removeAll()
                    editMode = .inactive
                }
            }
            Button(t("Cancel", "Отмена"), role: .cancel) {}
        } message: {
            Text(emptyTrashMessage)
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
                    if let selectedTrashRecordingId, ids.contains(selectedTrashRecordingId) {
                        self.selectedTrashRecordingId = nil
                    }
                    selection.removeAll()
                    editMode = .inactive
                }
            }
            Button(t("Cancel", "Отмена"), role: .cancel) {}
        } message: {
            Text(t("This action cannot be undone.", "Это действие нельзя отменить."))
        }
        .onChange(of: viewModel.trashedRecordings.map(\.id)) { _, visibleIds in
            reconcileTrashSelection(visibleIds)
        }
    }

    private var compactTrashList: some View {
        List(selection: $selection) {
            ForEach(viewModel.trashedRecordings) { recording in
                NavigationLink(destination: trashDetailView(for: recording)) {
                    trashRecordingRow(for: recording)
                }
                .tag(recording.id)
                .swipeActions(edge: .trailing) {
                    Button(role: .destructive) {
                        Task {
                            await permanentlyDeleteRecording(id: recording.id)
                        }
                    } label: {
                        Label(t("Delete", "Удалить"), systemImage: "trash.slash")
                    }
                }
                .swipeActions(edge: .leading) {
                    Button {
                        Task {
                            await restoreRecording(id: recording.id)
                        }
                    } label: {
                        Label(t("Restore", "Восстановить"), systemImage: "arrow.uturn.backward")
                    }
                    .tint(Palette.success)
                }
            }
        }
    }

    private var regularTrashLayout: some View {
        HStack(spacing: 0) {
            List(selection: $selection) {
                ForEach(viewModel.trashedRecordings) { recording in
                    regularTrashRow(for: recording)
                        .tag(recording.id)
                        .swipeActions(edge: .trailing) {
                            Button(role: .destructive) {
                                Task {
                                    await permanentlyDeleteRecording(id: recording.id)
                                }
                            } label: {
                                Label(t("Delete", "Удалить"), systemImage: "trash.slash")
                            }
                        }
                        .swipeActions(edge: .leading) {
                            Button {
                                Task {
                                    await restoreRecording(id: recording.id)
                                }
                            } label: {
                                Label(t("Restore", "Восстановить"), systemImage: "arrow.uturn.backward")
                            }
                            .tint(Palette.success)
                        }
                }
            }
            .listStyle(.plain)
            .scrollContentBackground(.hidden)
            .frame(minWidth: 320, idealWidth: 390, maxWidth: 460, maxHeight: .infinity, alignment: .topLeading)
            .background(Palette.surfaceSubtle)
            .accessibilityIdentifier("ios-trash-list-pane")

            Divider()

            regularTrashDetailPane
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                .background(Color(uiColor: .systemGroupedBackground))
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .accessibilityIdentifier("ios-trash-regular-layout")
    }

    @ViewBuilder
    private func regularTrashRow(for recording: Recording) -> some View {
        if isEditing {
            trashRecordingRow(for: recording)
        } else {
            Button {
                selectedTrashRecordingId = recording.id
            } label: {
                trashRecordingRow(for: recording)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .listRowBackground(selectedTrashRecordingId == recording.id ? Palette.accentSubtle : Color.clear)
            .accessibilityIdentifier("ios-trash-row-\(recording.id)")
        }
    }

    private func trashRecordingRow(for recording: Recording) -> some View {
        RecordingRow(
            recording: recording,
            hasLocalRecoveryBackup: viewModel.localRecoveryRecordingIDs.contains(recording.id),
            hasPermanentLocalFailure: viewModel.permanentLocalFailureRecordingIDs.contains(recording.id)
        )
    }

    @ViewBuilder
    private var regularTrashDetailPane: some View {
        if let id = selectedTrashRecordingId,
           let recording = viewModel.trashedRecordings.first(where: { $0.id == id }) {
            trashDetailView(for: recording)
                .id(id)
                .accessibilityIdentifier("ios-trash-detail-pane")
        } else {
            regularTrashPlaceholder
        }
    }

    private var regularTrashPlaceholder: some View {
        VStack(spacing: Spacing.lg) {
            Image(systemName: "trash")
                .font(.system(size: 30, weight: .semibold))
                .foregroundStyle(Palette.accent)
                .frame(width: 64, height: 64)
                .background(Palette.accentSubtle)
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))

            VStack(spacing: Spacing.xxs) {
                Text(t("Select a deleted recording", "Выберите удаленную запись"))
                    .font(Typography.displaySmall)
                    .foregroundStyle(Palette.textPrimary)
                    .multilineTextAlignment(.center)
                Text(t(
                    "Review the transcript before restoring it or deleting it forever.",
                    "Проверьте расшифровку перед восстановлением или окончательным удалением."
                ))
                .font(Typography.bodySmall)
                .foregroundStyle(Palette.textSecondary)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: 420)
            }
        }
        .padding(Spacing.xl)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .accessibilityIdentifier("ios-trash-placeholder")
    }

    private func trashDetailView(for recording: Recording) -> some View {
        RecordingDetailView(
            recording: recording,
            isTrash: true,
            onRestore: {
                Task {
                    await restoreRecording(id: recording.id)
                }
            },
            onPermanentDelete: {
                Task {
                    await permanentlyDeleteRecording(id: recording.id)
                }
            },
            onDetailChange: { detail in
                viewModel.applyRecordingDetail(detail)
            }
        )
    }

    private func restoreRecording(id: String) async {
        await viewModel.restoreRecording(
            id: id,
            apiClient: appState.getAPIClient()
        )
        clearSelectionIfNeeded(id: id)
    }

    private func permanentlyDeleteRecording(id: String) async {
        await viewModel.permanentlyDeleteRecording(
            id: id,
            apiClient: appState.getAPIClient()
        )
        clearSelectionIfNeeded(id: id)
    }

    private func clearSelectionIfNeeded(id: String) {
        selection.remove(id)
        if selectedTrashRecordingId == id {
            selectedTrashRecordingId = nil
        }
    }

    private func reconcileTrashSelection(_ visibleIds: [String]) {
        let visible = Set(visibleIds)
        selection = selection.intersection(visible)
        if let selectedTrashRecordingId, !visible.contains(selectedTrashRecordingId) {
            self.selectedTrashRecordingId = nil
        }
    }

    /// Count-aware empty-trash warning with correct English and Russian plurals
    /// and natural Russian word order (e.g. "удалит 1 запись" / "удалит 5 записей").
    private var emptyTrashMessage: String {
        let count = viewModel.trashedRecordings.count
        if OnboardingL10n.language(for: languageManager.current) == .russian {
            let noun = RussianPlural.form(count, one: "запись", few: "записи", many: "записей")
            return "Это навсегда удалит \(count) \(noun). Это действие нельзя отменить."
        }
        let noun = count == 1 ? "recording" : "recordings"
        return "This will permanently delete \(count) \(noun). This cannot be undone."
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
        .background(Palette.warning)
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
        VStack(alignment: .leading, spacing: Spacing.xs) {
            HStack(spacing: Spacing.sm) {
                Text(recording.title ?? t("Untitled", "Без названия"))
                    .font(Typography.headingMedium)
                    .foregroundStyle(Palette.textPrimary)
                    .lineLimit(1)
                    .truncationMode(.tail)
                    .layoutPriority(1)

                Spacer(minLength: Spacing.sm)

                if let statusText = recording.statusDisplayText(
                    hasLocalRecoveryBackup: hasLocalRecoveryBackup,
                    hasPermanentLocalFailure: hasPermanentLocalFailure,
                    languageCode: speakerLanguageCode
                ) {
                    Text(statusText)
                        .font(Typography.label)
                        .foregroundStyle(statusColor)
                        .lineLimit(1)
                        .minimumScaleFactor(0.85)
                        .truncationMode(.tail)
                        .fixedSize(horizontal: true, vertical: false)
                        .layoutPriority(2)
                }
            }

            HStack(spacing: Spacing.sm) {
                Circle()
                    .fill(Palette.typeColor(recording.type))
                    .frame(width: 6, height: 6)

                Text(IOSDateFormatting.listTimestamp(
                    from: recording.createdAt,
                    language: languageManager.current
                ))
                .font(Typography.label)
                .foregroundStyle(Palette.textSecondary)

                if let duration = recording.durationSeconds, duration > 0 {
                    Text(IOSDateFormatting.duration(seconds: duration))
                        .font(Typography.mono)
                        .foregroundStyle(Palette.textSecondary)
                }
            }

            if let failurePreviewText = recording.failurePreviewText,
               recording.isFailedUpload {
                Text(failurePreviewText)
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textSecondary)
                    .lineLimit(1)
            }
        }
        .padding(.vertical, Spacing.xs)
        .frame(maxWidth: .infinity, minHeight: rowMinHeight, alignment: .leading)
    }

    private var rowMinHeight: CGFloat {
        if recording.failurePreviewText != nil, recording.isFailedUpload {
            return 68
        }
        return 48
    }

    private var statusColor: Color {
        if recording.isFailedUpload || hasPermanentLocalFailure {
            return Palette.danger
        }
        return Palette.textSecondary
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

            // Read the local backup manifests separately: a failure here must
            // surface (no-fallbacks) and must NOT silently wipe the existing
            // "saved locally" / "needs attention" badges. If it throws we keep
            // the prior badge sets and show a dismissible banner; the fetched
            // recordings still render below. The crawl decodes one JSON file
            // per backup, so it runs off the main actor — this reload repeats
            // every ~4s while anything is processing.
            let manifestsResult = await Task.detached(priority: .userInitiated) {
                Result { try RecordingBackupStore.manifestsByRecordingId() }
            }.value
            let backupManifests: [String: RecordingBackupManifest]?
            switch manifestsResult {
            case .success(let manifests):
                backupManifests = manifests
            case .failure(let error):
                backupManifests = nil
                self.error = error.userFacingMessage(context: .library)
            }
            guard generation == loadGeneration else { return }

            recordings = fetchedRecordings
            trashedRecordings = fetchedTrashed
            folders = fetchedFolders
            if let backupManifests {
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
            }

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
        trashedRecordings = IOSScreenshotFixtures.trashedRecordings
        folders = IOSScreenshotFixtures.folders
        localRecoveryRecordingIDs = []
        permanentLocalFailureRecordingIDs = []
        isLoading = false
        error = nil
        #endif
    }

    func applyRecordingDetail(_ detail: RecordingDetail) {
        let updated = Recording(detail: detail)

        if let index = recordings.firstIndex(where: { $0.id == detail.id }),
           recordings[index] != updated {
            var next = recordings
            next[index] = updated
            recordings = next
        }

        if let index = trashedRecordings.firstIndex(where: { $0.id == detail.id }),
           trashedRecordings[index] != updated {
            var next = trashedRecordings
            next[index] = updated
            trashedRecordings = next
        }
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
        case .ready:
            return recording.automaticTitlePending
        case .failed:
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
                    Text(String(format: t("Uploading %@…", "Загрузка %@…"), filename))
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
