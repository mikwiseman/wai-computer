import SwiftUI
import UniformTypeIdentifiers
import WaiSayKit

struct LibraryView: View {
    @EnvironmentObject var appState: AppState
    @StateObject private var viewModel = LibraryViewModel()
    @StateObject private var importViewModel = ImportViewModel()
    @State private var errorAutoDismissTask: Task<Void, Never>?
    @State private var importedRecording: Recording?
    @State private var showImportedDetail = false
    @State private var showNewFolderAlert = false
    @State private var newFolderName = ""
    @State private var showDeleteFolderConfirmation: Folder?

    private var isScreenshotMode: Bool {
        IOSTestingMode.current.isScreenshot
    }

    var body: some View {
        NavigationStack {
            Group {
                if viewModel.isLoading && viewModel.recordings.isEmpty {
                    ProgressView("Loading recordings...")
                } else if viewModel.recordings.isEmpty && viewModel.trashedRecordings.isEmpty && viewModel.folders.isEmpty {
                    ContentUnavailableView(
                        "No Recordings",
                        systemImage: "waveform",
                        description: Text("Start recording to see your notes here")
                    )
                } else {
                    libraryList
                }
            }
            .navigationTitle("Library")
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
            .overlay {
                if importViewModel.isUploading {
                    ImportUploadOverlay(filename: importViewModel.uploadingFilename)
                }
            }
            .toolbar {
                ToolbarItem(placement: .primaryAction) {
                    Menu {
                        Button {
                            importViewModel.showFileImporter = true
                        } label: {
                            Label("Import Audio File", systemImage: "square.and.arrow.down")
                        }

                        Button(action: { showNewFolderAlert = true }) {
                            Label("New Folder", systemImage: "folder.badge.plus")
                        }
                    } label: {
                        Image(systemName: "ellipsis.circle")
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
                "Import Failed",
                isPresented: Binding(
                    get: { importViewModel.errorMessage != nil },
                    set: { if !$0 { importViewModel.errorMessage = nil } }
                )
            ) {
                Button("OK") { importViewModel.errorMessage = nil }
            } message: {
                Text(importViewModel.errorMessage ?? "")
            }
            .alert("New Folder", isPresented: $showNewFolderAlert) {
                TextField("Folder name", text: $newFolderName)
                Button("Create") {
                    let name = newFolderName.trimmingCharacters(in: .whitespacesAndNewlines)
                    guard !name.isEmpty else { return }
                    Task {
                        await viewModel.createFolder(name: name, apiClient: appState.getAPIClient())
                    }
                    newFolderName = ""
                }
                Button("Cancel", role: .cancel) {
                    newFolderName = ""
                }
            }
            .confirmationDialog(
                "Delete folder \"\(showDeleteFolderConfirmation?.name ?? "")\"?",
                isPresented: Binding(
                    get: { showDeleteFolderConfirmation != nil },
                    set: { if !$0 { showDeleteFolderConfirmation = nil } }
                ),
                titleVisibility: .visible
            ) {
                Button("Delete Folder", role: .destructive) {
                    if let folder = showDeleteFolderConfirmation {
                        Task {
                            await viewModel.deleteFolder(id: folder.id, apiClient: appState.getAPIClient())
                        }
                    }
                    showDeleteFolderConfirmation = nil
                }
                Button("Cancel", role: .cancel) {
                    showDeleteFolderConfirmation = nil
                }
            } message: {
                Text("Recordings in this folder will be moved to Unfiled.")
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
        List {
            // Folders section
            if !viewModel.folders.isEmpty {
                Section("Folders") {
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
                        .swipeActions(edge: .trailing) {
                            Button(role: .destructive) {
                                showDeleteFolderConfirmation = folder
                            } label: {
                                Label("Delete", systemImage: "trash")
                            }
                        }
                    }
                }
            }

            // Recordings section (unfiled / all depending on folders)
            Section(viewModel.folders.isEmpty ? "Recordings" : "Unfiled") {
                ForEach(viewModel.filteredUnfiledRecordings) { recording in
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
                        }
                    )) {
                        RecordingRow(recording: recording)
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
                            Label("Trash", systemImage: "trash")
                        }
                    }
                    .contextMenu {
                        recordingContextMenu(for: recording)
                    }
                }
            }

            // Trash section
            if !viewModel.trashedRecordings.isEmpty {
                Section {
                    NavigationLink(destination: TrashView(viewModel: viewModel)) {
                        HStack {
                            Image(systemName: "trash")
                                .foregroundStyle(.red)
                            Text("Trash")
                            Spacer()
                            Text("\(viewModel.trashedRecordings.count)")
                                .foregroundStyle(.secondary)
                                .font(.caption)
                        }
                    }
                }
            }
        }
    }

    // MARK: - Context Menu

    @ViewBuilder
    private func recordingContextMenu(for recording: Recording) -> some View {
        if !viewModel.folders.isEmpty {
            Menu("Move to Folder") {
                if recording.folderId != nil {
                    Button("Unfiled") {
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
            Label("Move to Trash", systemImage: "trash")
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
    let folder: Folder
    @ObservedObject var viewModel: LibraryViewModel

    var body: some View {
        let folderRecordings = viewModel.filteredRecordingsInFolder(folder.id)

        Group {
            if folderRecordings.isEmpty {
                ContentUnavailableView(
                    "No Recordings",
                    systemImage: "folder",
                    description: Text("Move recordings here from the library")
                )
            } else {
                List {
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
                            }
                        )) {
                            RecordingRow(recording: recording)
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
                                Label("Trash", systemImage: "trash")
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
                                Label("Unfiled", systemImage: "tray")
                            }
                            .tint(.blue)
                        }
                        .contextMenu {
                            Menu("Move to Folder") {
                                Button("Unfiled") {
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
                                Label("Move to Trash", systemImage: "trash")
                            }
                        }
                    }
                }
            }
        }
        .navigationTitle(folder.name)
    }
}

// MARK: - Trash View

struct TrashView: View {
    @EnvironmentObject var appState: AppState
    @ObservedObject var viewModel: LibraryViewModel
    @State private var showEmptyTrashConfirmation = false

    var body: some View {
        Group {
            if viewModel.trashedRecordings.isEmpty {
                ContentUnavailableView(
                    "Trash is Empty",
                    systemImage: "trash",
                    description: Text("Deleted recordings will appear here")
                )
            } else {
                List {
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
                            RecordingRow(recording: recording)
                        }
                        .swipeActions(edge: .trailing) {
                            Button(role: .destructive) {
                                Task {
                                    await viewModel.permanentlyDeleteRecording(
                                        id: recording.id,
                                        apiClient: appState.getAPIClient()
                                    )
                                }
                            } label: {
                                Label("Delete", systemImage: "trash.slash")
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
                                Label("Restore", systemImage: "arrow.uturn.backward")
                            }
                            .tint(.green)
                        }
                    }
                }
            }
        }
        .navigationTitle("Trash")
        .toolbar {
            if !viewModel.trashedRecordings.isEmpty {
                ToolbarItem(placement: .primaryAction) {
                    Button("Empty Trash", role: .destructive) {
                        showEmptyTrashConfirmation = true
                    }
                    .foregroundStyle(.red)
                }
            }
        }
        .confirmationDialog(
            "Empty Trash?",
            isPresented: $showEmptyTrashConfirmation,
            titleVisibility: .visible
        ) {
            Button("Delete All Permanently", role: .destructive) {
                Task {
                    await viewModel.emptyTrash(apiClient: appState.getAPIClient())
                }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("This will permanently delete \(viewModel.trashedRecordings.count) recording\(viewModel.trashedRecordings.count == 1 ? "" : "s"). This cannot be undone.")
        }
    }
}

// MARK: - Inline Banner

private struct InlineLibraryBanner: View {
    let message: String
    let onDismiss: () -> Void

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

// MARK: - Recording Row

struct RecordingRow: View {
    let recording: Recording

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(recording.title ?? "Untitled")
                .font(.headline)

            if let statusText = recording.statusDisplayText {
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
        recording.isFailedUpload ? .red : .secondary
    }
}

// MARK: - ViewModel

@MainActor
class LibraryViewModel: ObservableObject {
    @Published var recordings: [Recording] = []
    @Published var trashedRecordings: [Recording] = []
    @Published var folders: [Folder] = []
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
            guard generation == loadGeneration else { return }

            recordings = fetchedRecordings
            trashedRecordings = fetchedTrashed
            folders = fetchedFolders

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
        isLoading = false
        error = nil
        #endif
    }

    // MARK: - Folder Operations

    func createFolder(name: String, apiClient: APIClient) async {
        do {
            let folder = try await apiClient.createFolder(name: name)
            folders.append(folder)
            folders.sort { $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending }
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

    var body: some View {
        ZStack {
            Color.black.opacity(0.4)
                .ignoresSafeArea()

            VStack(spacing: 16) {
                ProgressView()
                    .controlSize(.large)

                if let filename {
                    Text("Uploading \(filename)...")
                        .font(.headline)
                        .foregroundStyle(.primary)
                }

                Text("The server will transcribe automatically")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .padding(32)
            .background(.ultraThinMaterial)
            .clipShape(RoundedRectangle(cornerRadius: 20, style: .continuous))
            .shadow(color: .black.opacity(0.15), radius: 20, y: 8)
        }
    }
}

#Preview {
    LibraryView()
        .environmentObject(AppState())
}
