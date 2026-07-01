import SwiftUI
import WaiComputerKit

private enum IOSInboxSource: String, CaseIterable, Identifiable {
    case recordings
    case materials

    var id: String { rawValue }

    func title(language: LanguageManager.SupportedLanguage) -> String {
        switch self {
        case .recordings:
            return OnboardingL10n.text("Recordings", "Записи", language: language)
        case .materials:
            return OnboardingL10n.text("Materials", "Материалы", language: language)
        }
    }
}

private enum IOSInboxDetailSelection: Equatable {
    case recording(String)
    case material(String)
}

/// iPad workspace Inbox. It mirrors the Mac app's primary mental model:
/// recordings and captured materials are one second-brain inbox, with a source
/// switch for scanning the two streams.
struct IOSInboxView: View {
    @EnvironmentObject private var languageManager: LanguageManager
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass
    @ObservedObject private var libraryViewModel: LibraryViewModel
    @StateObject private var feed: ContentFeedViewModel
    @State private var source: IOSInboxSource = .recordings
    @State private var showAddMaterial = false
    @State private var showFileImporter = false
    @State private var selectedDetail: IOSInboxDetailSelection?

    let apiClient: APIClient
    let folder: Folder?
    let onStartRecording: () -> Void

    init(
        apiClient: APIClient,
        libraryViewModel: LibraryViewModel,
        folder: Folder? = nil,
        onStartRecording: @escaping () -> Void
    ) {
        self.apiClient = apiClient
        self.folder = folder
        self.onStartRecording = onStartRecording
        _libraryViewModel = ObservedObject(wrappedValue: libraryViewModel)
        _feed = StateObject(wrappedValue: ContentFeedViewModel(
            apiClient: apiClient,
            folderId: folder?.id
        ))
    }

    var body: some View {
        NavigationStack {
            Group {
                if isRegularWidth {
                    regularInboxLayout
                } else {
                    compactInboxLayout
                }
            }
            .navigationTitle(title)
            .navigationBarTitleDisplayMode(isRegularWidth ? .inline : .large)
            .background(Color(uiColor: .systemGroupedBackground))
            .toolbar {
                ToolbarItem(placement: .primaryAction) {
                    if source == .recordings {
                        Button {
                            onStartRecording()
                        } label: {
                            Label(t("Record", "Записать"), systemImage: "waveform")
                        }
                        .accessibilityIdentifier("ios-inbox-primary-action")
                    } else {
                        Menu {
                            Button {
                                showAddMaterial = true
                            } label: {
                                Label(t("Paste Link or Text", "Вставить ссылку или текст"), systemImage: "doc.text")
                            }

                            Button {
                                showFileImporter = true
                            } label: {
                                Label(t("Upload File", "Загрузить файл"), systemImage: "paperclip")
                            }
                        } label: {
                            Label(t("Add Material", "Добавить материал"), systemImage: "plus")
                        }
                        .disabled(feed.isAdding || feed.isUploadingFile)
                        .accessibilityIdentifier("ios-inbox-primary-action")
                    }
                }
            }
            .refreshable {
                await loadInbox()
            }
            .task {
                await loadInbox()
            }
            .onReceive(NotificationCenter.default.publisher(for: .pendingRecordingSyncDidFinish)) { _ in
                Task { await loadRecordings() }
            }
            .onChange(of: source) { _, _ in
                selectedDetail = nil
            }
            .sheet(isPresented: $showAddMaterial) {
                AddAnythingSheet(isPresented: $showAddMaterial, isAdding: feed.isAdding) { text in
                    Task {
                        if await feed.add(text) != nil {
                            showAddMaterial = false
                            await loadRecordings()
                        }
                    }
                }
                .environmentObject(languageManager)
            }
            .fileImporter(
                isPresented: $showFileImporter,
                allowedContentTypes: ContentFeedViewModel.importContentTypes,
                allowsMultipleSelection: false
            ) { result in
                handleImportedFile(result)
            }
            .overlay(alignment: .top) {
                if let error = currentError {
                    IOSWorkspaceErrorBanner(message: error) {
                        libraryViewModel.error = nil
                        feed.errorMessage = nil
                    }
                    .padding(.top, Spacing.sm)
                    .padding(.horizontal, Spacing.lg)
                }
            }
            .overlay(alignment: .bottom) {
                if feed.isUploadingFile {
                    IOSInboxStatusBanner(
                        systemImage: "arrow.up.doc",
                        message: t("Uploading file...", "Загружаем файл...")
                    )
                    .padding(.bottom, Spacing.lg)
                } else if let status = feed.statusMessage {
                    IOSInboxStatusBanner(systemImage: "checkmark.circle.fill", message: status) {
                        feed.statusMessage = nil
                    }
                    .padding(.bottom, Spacing.lg)
                }
            }
        }
        .accessibilityIdentifier("ios-inbox-view")
    }

    private var isRegularWidth: Bool {
        horizontalSizeClass == .regular
    }

    private var compactInboxLayout: some View {
        VStack(spacing: 0) {
            header
            Divider()
            content
        }
    }

    private var regularInboxLayout: some View {
        HStack(spacing: 0) {
            VStack(spacing: 0) {
                header
                Divider()
                content
            }
            .frame(minWidth: 320, idealWidth: 390, maxWidth: 460, maxHeight: .infinity, alignment: .topLeading)
            .background(Palette.surfaceSubtle)
            .accessibilityIdentifier("ios-inbox-list-pane")

            Divider()

            regularDetailPane
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                .background(Color(uiColor: .systemGroupedBackground))
                .accessibilityIdentifier("ios-inbox-regular-detail")
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .accessibilityIdentifier("ios-inbox-regular-layout")
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            HStack(alignment: .top, spacing: Spacing.md) {
                Image(systemName: "tray.full")
                    .font(.system(size: 22, weight: .semibold))
                    .foregroundStyle(Palette.accent)
                    .frame(width: 44, height: 44)
                    .background(Palette.accentSubtle)
                    .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))

                VStack(alignment: .leading, spacing: Spacing.xxs) {
                    Text(title)
                        .font(Typography.displaySmall)
                        .foregroundStyle(Palette.textPrimary)
                    Text(subtitle)
                        .font(Typography.bodySmall)
                        .foregroundStyle(Palette.textSecondary)
                }

                Spacer()
            }

            Picker(t("Source", "Источник"), selection: $source) {
                ForEach(IOSInboxSource.allCases) { source in
                    Text(source.title(language: languageManager.current)).tag(source)
                }
            }
            .pickerStyle(.segmented)
            .accessibilityIdentifier("ios-inbox-source-picker")
        }
        .padding(Spacing.lg)
        .frame(maxWidth: 760, alignment: .leading)
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .background(Palette.surfaceSubtle)
    }

    @ViewBuilder
    private var content: some View {
        switch source {
        case .recordings:
            recordingsContent
        case .materials:
            materialsContent
        }
    }

    @ViewBuilder
    private var regularDetailPane: some View {
        switch selectedDetail {
        case .recording(let id):
            if let recording = scopedRecordings.first(where: { $0.id == id }) {
                recordingDetailView(for: recording)
            } else {
                regularPlaceholder
            }
        case .material(let id):
            if let entry = feed.entries.first(where: { $0.id == id }) {
                materialDetailView(for: entry)
            } else {
                regularPlaceholder
            }
        case .none:
            regularPlaceholder
        }
    }

    private var regularPlaceholder: some View {
        IOSInboxRegularDetailPlaceholder(
            source: source,
            folderName: folder?.name,
            onRecord: onStartRecording,
            onAddMaterial: { showAddMaterial = true },
            onUploadFile: { showFileImporter = true }
        )
        .environmentObject(languageManager)
    }

    @ViewBuilder
    private var recordingsContent: some View {
        let recordings = scopedRecordings

        if libraryViewModel.isLoading && recordings.isEmpty {
            ProgressView(t("Loading recordings...", "Загрузка записей..."))
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .accessibilityIdentifier("ios-inbox-recordings-loading")
        } else if recordings.isEmpty {
            ContentUnavailableView {
                Label(t("No Recordings", "Нет записей"), systemImage: "waveform")
            } description: {
                Text(recordingsEmptyText)
            } actions: {
                Button(t("Record", "Записать"), action: onStartRecording)
                    .buttonStyle(.borderedProminent)
                    .tint(Palette.accent)
            }
            .accessibilityIdentifier("ios-inbox-recordings-empty")
        } else {
            List {
                Section {
                    ForEach(recordings) { recording in
                        recordingRow(for: recording)
                        .draggable(IOSInboxDragItem(kind: .recording, id: recording.id))
                        .accessibilityIdentifier("ios-inbox-recording-\(recording.id)")
                    }
                } header: {
                    Text(t("Recordings", "Записи"))
                }
            }
            .listStyle(.plain)
            .scrollContentBackground(.hidden)
            .frame(maxWidth: 760, alignment: .leading)
            .frame(maxWidth: .infinity, alignment: .topLeading)
            .accessibilityIdentifier("ios-inbox-recordings-list")
        }
    }

    @ViewBuilder
    private var materialsContent: some View {
        if feed.isLoading && feed.entries.isEmpty {
            ProgressView(t("Loading materials...", "Загрузка материалов..."))
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .accessibilityIdentifier("ios-inbox-materials-loading")
        } else if feed.entries.isEmpty {
            ContentUnavailableView {
                Label(t("No Materials", "Нет материалов"), systemImage: "doc.on.doc")
            } description: {
                Text(materialsEmptyText)
            } actions: {
                Button(t("Paste Link or Text", "Вставить ссылку или текст")) {
                    showAddMaterial = true
                }
                .buttonStyle(.borderedProminent)
                .tint(Palette.accent)

                Button(t("Upload File", "Загрузить файл")) {
                    showFileImporter = true
                }
                .buttonStyle(.bordered)
            }
            .accessibilityIdentifier("ios-inbox-materials-empty")
        } else {
            List {
                Section {
                    ForEach(feed.entries) { entry in
                        materialRow(for: entry)
                        .draggable(IOSInboxDragItem(kind: .item, id: entry.id))
                        .contextMenu {
                            materialContextMenu(for: entry)
                        }
                        .swipeActions(edge: .leading) {
                            if entry.folderId != nil {
                                Button {
                                    Task { await moveMaterial(entry.id, to: nil) }
                                } label: {
                                    Label(t("Unfiled", "Без папки"), systemImage: "tray")
                                }
                                .tint(.blue)
                            }
                        }
                        .accessibilityIdentifier("ios-inbox-material-\(entry.id)")
                    }
                    .onDelete { offsets in
                        let ids = offsets.map { feed.entries[$0].id }
                        Task {
                            for id in ids {
                                await feed.delete(id)
                            }
                            await loadRecordings()
                        }
                    }
                } header: {
                    Text(t("Materials", "Материалы"))
                }
            }
            .listStyle(.plain)
            .scrollContentBackground(.hidden)
            .frame(maxWidth: 760, alignment: .leading)
            .frame(maxWidth: .infinity, alignment: .topLeading)
            .accessibilityIdentifier("ios-inbox-materials-list")
        }
    }

    @ViewBuilder
    private func recordingRow(for recording: Recording) -> some View {
        if isRegularWidth {
            Button {
                selectedDetail = .recording(recording.id)
            } label: {
                RecordingRow(
                    recording: recording,
                    hasLocalRecoveryBackup: libraryViewModel.localRecoveryRecordingIDs.contains(recording.id),
                    hasPermanentLocalFailure: libraryViewModel.permanentLocalFailureRecordingIDs.contains(recording.id)
                )
                .frame(maxWidth: .infinity, alignment: .leading)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .listRowBackground(isSelected(recording) ? Palette.accentSubtle : Color.clear)
        } else {
            NavigationLink {
                recordingDetailView(for: recording)
            } label: {
                RecordingRow(
                    recording: recording,
                    hasLocalRecoveryBackup: libraryViewModel.localRecoveryRecordingIDs.contains(recording.id),
                    hasPermanentLocalFailure: libraryViewModel.permanentLocalFailureRecordingIDs.contains(recording.id)
                )
            }
        }
    }

    @ViewBuilder
    private func materialRow(for entry: ItemListEntry) -> some View {
        if isRegularWidth {
            Button {
                selectedDetail = .material(entry.id)
            } label: {
                IOSInboxMaterialRow(entry: entry)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .listRowBackground(isSelected(entry) ? Palette.accentSubtle : Color.clear)
        } else {
            NavigationLink {
                materialDetailView(for: entry)
            } label: {
                IOSInboxMaterialRow(entry: entry)
            }
        }
    }

    private func recordingDetailView(for recording: Recording) -> some View {
        RecordingDetailView(
            recording: recording,
            folders: libraryViewModel.folders,
            onMoveToFolder: { folderId in
                Task {
                    await libraryViewModel.moveRecording(
                        id: recording.id,
                        to: folderId,
                        apiClient: apiClient
                    )
                    if folder != nil, folderId != folder?.id {
                        selectedDetail = nil
                    }
                    await loadRecordings()
                }
            },
            onTrash: {
                Task {
                    await libraryViewModel.trashRecording(
                        id: recording.id,
                        apiClient: apiClient
                    )
                    selectedDetail = nil
                    await loadRecordings()
                }
            },
            onDidRename: {
                Task { await loadRecordings() }
            }
        )
    }

    private func materialDetailView(for entry: ItemListEntry) -> some View {
        ItemDetailView(itemId: entry.id, apiClient: apiClient) {
            Task { await loadMaterials() }
        }
    }

    private func isSelected(_ recording: Recording) -> Bool {
        selectedDetail == .recording(recording.id)
    }

    private func isSelected(_ entry: ItemListEntry) -> Bool {
        selectedDetail == .material(entry.id)
    }

    private var currentError: String? {
        libraryViewModel.error ?? feed.errorMessage
    }

    private var title: String {
        folder?.name ?? t("Inbox", "Инбокс")
    }

    private var subtitle: String {
        if folder != nil {
            return t(
                "Recordings and materials in this folder",
                "Записи и материалы в этой папке"
            )
        }
        return t(
            "Recordings and materials in one place",
            "Записи и материалы в одном месте"
        )
    }

    private var scopedRecordings: [Recording] {
        guard let folder else { return libraryViewModel.recordings }
        return libraryViewModel.filteredRecordingsInFolder(folder.id)
    }

    private var recordingsEmptyText: String {
        if folder != nil {
            return t(
                "Move recordings here from the library.",
                "Переместите записи сюда из библиотеки."
            )
        }
        return t(
            "Start a recording to save it into your Inbox.",
            "Начните запись, чтобы сохранить её в Инбокс."
        )
    }

    private var materialsEmptyText: String {
        if folder != nil {
            return t(
                "Paste a link, note, or file to remember it in this folder.",
                "Вставьте ссылку, заметку или файл, чтобы сохранить в эту папку."
            )
        }
        return t(
            "Paste a link, note, or file to remember it here.",
            "Вставьте ссылку, заметку или файл, чтобы сохранить здесь."
        )
    }

    private func loadInbox() async {
        await loadRecordings()
        await loadMaterials()
    }

    private func loadRecordings() async {
        #if DEBUG
        if IOSTestingMode.current.isScreenshot {
            libraryViewModel.loadScreenshotFixtures()
            return
        }
        #endif

        await libraryViewModel.loadLibrary(apiClient: apiClient)
    }

    private func loadMaterials() async {
        #if DEBUG
        if IOSTestingMode.current.isScreenshot {
            feed.loadScreenshotFixtures()
            return
        }
        #endif

        await feed.load()
    }

    private func handleImportedFile(_ result: Result<[URL], Error>) {
        switch result {
        case .success(let urls):
            guard let url = urls.first else { return }
            Task {
                let outcome = await feed.uploadFile(url)
                if outcome != nil {
                    await loadRecordings()
                }
            }
        case .failure(let error):
            feed.errorMessage = error.localizedDescription
        }
    }

    @ViewBuilder
    private func materialContextMenu(for entry: ItemListEntry) -> some View {
        if entry.folderId != nil || !libraryViewModel.folders.isEmpty {
            Menu(t("Move to Folder", "Переместить в папку")) {
                if entry.folderId != nil {
                    Button(t("Remove from Folder", "Убрать из папки")) {
                        Task { await moveMaterial(entry.id, to: nil) }
                    }
                }

                ForEach(libraryViewModel.folders) { folder in
                    if folder.id != entry.folderId {
                        Button(folder.name) {
                            Task { await moveMaterial(entry.id, to: folder.id) }
                        }
                    }
                }
            }
        }

        Button(t("Delete", "Удалить"), role: .destructive) {
            Task {
                await feed.delete(entry.id)
                await loadRecordings()
            }
        }
    }

    private func moveMaterial(_ id: String, to folderId: String?) async {
        guard await feed.moveItem(id, to: folderId) else { return }
        await loadRecordings()
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

private struct IOSInboxRegularDetailPlaceholder: View {
    @EnvironmentObject private var languageManager: LanguageManager
    let source: IOSInboxSource
    let folderName: String?
    let onRecord: () -> Void
    let onAddMaterial: () -> Void
    let onUploadFile: () -> Void

    var body: some View {
        VStack(spacing: Spacing.lg) {
            Image(systemName: folderName == nil ? "tray.full" : "folder")
                .font(.system(size: 30, weight: .semibold))
                .foregroundStyle(Palette.accent)
                .frame(width: 64, height: 64)
                .background(Palette.accentSubtle)
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))

            VStack(spacing: Spacing.xxs) {
                Text(title)
                    .font(Typography.displaySmall)
                    .foregroundStyle(Palette.textPrimary)
                    .multilineTextAlignment(.center)
                Text(subtitle)
                    .font(Typography.bodySmall)
                    .foregroundStyle(Palette.textSecondary)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: 380)
            }

            if source == .recordings {
                Button(action: onRecord) {
                    Label(t("Start Recording", "Начать запись"), systemImage: "waveform")
                }
                .buttonStyle(.borderedProminent)
                .tint(Palette.accent)
                .accessibilityIdentifier("ios-inbox-placeholder-record")
            } else {
                HStack(spacing: Spacing.sm) {
                    Button(action: onAddMaterial) {
                        Label(t("Paste Link or Text", "Вставить ссылку или текст"), systemImage: "doc.text")
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(Palette.accent)
                    .accessibilityIdentifier("ios-inbox-placeholder-add-material")

                    Button(action: onUploadFile) {
                        Label(t("Upload File", "Загрузить файл"), systemImage: "paperclip")
                    }
                    .buttonStyle(.bordered)
                    .accessibilityIdentifier("ios-inbox-placeholder-upload-file")
                }
            }
        }
        .padding(Spacing.xl)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .accessibilityIdentifier("ios-inbox-regular-placeholder")
    }

    private var title: String {
        if let folderName {
            return folderName
        }
        return t("Inbox", "Инбокс")
    }

    private var subtitle: String {
        if folderName != nil {
            return t(
                "Select a recording or material on the left to open it here.",
                "Выберите запись или материал слева, чтобы открыть здесь."
            )
        }
        return t(
            "Select a recording or material on the left, or add something new.",
            "Выберите запись или материал слева или добавьте что-нибудь новое."
        )
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

private struct IOSInboxStatusBanner: View {
    let systemImage: String
    let message: String
    var onDismiss: (() -> Void)? = nil

    var body: some View {
        HStack(spacing: Spacing.sm) {
            Image(systemName: systemImage)
                .foregroundStyle(Palette.accent)
            Text(message)
                .font(Typography.bodySmall)
                .foregroundStyle(Palette.textPrimary)
                .lineLimit(2)
            if let onDismiss {
                Button(action: onDismiss) {
                    Image(systemName: "xmark")
                        .font(.system(size: 12, weight: .semibold))
                }
                .buttonStyle(.plain)
                .foregroundStyle(Palette.textSecondary)
            }
        }
        .padding(.horizontal, Spacing.md)
        .padding(.vertical, Spacing.sm)
        .background(.thinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(Palette.border)
        }
        .accessibilityIdentifier("ios-inbox-status-banner")
    }
}

private struct IOSInboxMaterialRow: View {
    @EnvironmentObject private var languageManager: LanguageManager
    let entry: ItemListEntry

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.xxs) {
            Text(entry.title ?? t("Untitled", "Без названия"))
                .font(Typography.body.weight(.medium))
                .foregroundStyle(Palette.textPrimary)
                .lineLimit(2)

            HStack(spacing: Spacing.xs) {
                Text(entry.kind.uppercased())
                    .font(Typography.labelSmall)
                    .foregroundStyle(Palette.accent)
                if !entry.hasSummary {
                    Text(t("summarizing...", "конспект..."))
                        .font(Typography.labelSmall)
                        .foregroundStyle(Palette.textTertiary)
                }
            }
        }
        .padding(.vertical, Spacing.xs)
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

/// The iOS "Materials" tab — the captured-items inbox (links, notes, files),
/// summarized and searchable. Capture and recall stay front and center; the
/// knowledge mechanics (entity graph, recall ranking) run in the background
/// and surface through unified search and the MCP server.
struct MaterialsView: View {
    @EnvironmentObject private var languageManager: LanguageManager
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass
    @StateObject private var feed: ContentFeedViewModel
    @StateObject private var foldersModel = LibraryViewModel()
    @State private var selectedMaterialId: String?

    let apiClient: APIClient

    init(apiClient: APIClient) {
        self.apiClient = apiClient
        _feed = StateObject(wrappedValue: ContentFeedViewModel(apiClient: apiClient))
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }

    var body: some View {
        NavigationStack {
            Group {
                if feed.isSearchActive {
                    searchList
                } else if isRegularWidth {
                    regularMaterialsLayout
                } else {
                    compactMaterialsLayout
                }
            }
            .navigationTitle(t("Materials", "Материалы"))
            .navigationBarTitleDisplayMode(.inline)
            .searchable(text: $feed.query, prompt: t("Search everything", "Искать везде"))
            .task {
                await loadFolders()
            }
            .task(id: feed.query) {
                do {
                    try await Task.sleep(nanoseconds: 300_000_000)
                } catch {
                    return
                }
                guard !Task.isCancelled else { return }
                await feed.search()
            }
            .onChange(of: feed.kind) { _, _ in
                selectedMaterialId = nil
            }
            .overlay(alignment: .top) {
                if let error = currentError {
                    IOSWorkspaceErrorBanner(message: error) {
                        foldersModel.error = nil
                        feed.errorMessage = nil
                    }
                    .padding(.top, Spacing.sm)
                    .padding(.horizontal, Spacing.lg)
                }
            }
        }
    }

    private var isRegularWidth: Bool {
        horizontalSizeClass == .regular
    }

    private var compactMaterialsLayout: some View {
        CapturedFeedView(
            model: feed,
            folders: foldersModel.folders,
            onFolderContentChanged: loadFolders
        )
    }

    private var regularMaterialsLayout: some View {
        HStack(spacing: 0) {
            CapturedFeedView(
                model: feed,
                folders: foldersModel.folders,
                onFolderContentChanged: loadFolders,
                selectedMaterialId: $selectedMaterialId
            )
            .frame(minWidth: 320, idealWidth: 390, maxWidth: 460, maxHeight: .infinity, alignment: .topLeading)
            .background(Palette.surfaceSubtle)
            .accessibilityIdentifier("materials-regular-list-pane")

            Divider()

            regularDetailPane
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                .background(Color(uiColor: .systemGroupedBackground))
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .accessibilityIdentifier("materials-regular-layout")
    }

    @ViewBuilder
    private var regularDetailPane: some View {
        if let id = selectedMaterialId,
           feed.entries.contains(where: { $0.id == id }) {
            ItemDetailView(itemId: id, apiClient: apiClient) {
                selectedMaterialId = nil
                Task { await loadMaterialsFeed() }
            }
            .id(id)
            .accessibilityIdentifier("materials-regular-detail-pane")
        } else {
            regularPlaceholder
        }
    }

    private var regularPlaceholder: some View {
        VStack(spacing: Spacing.lg) {
            Image(systemName: "doc.text.magnifyingglass")
                .font(.system(size: 30, weight: .semibold))
                .foregroundStyle(Palette.accent)
                .frame(width: 64, height: 64)
                .background(Palette.accentSubtle)
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))

            VStack(spacing: Spacing.xxs) {
                Text(t("Select a material", "Выберите материал"))
                    .font(Typography.displaySmall)
                    .foregroundStyle(Palette.textPrimary)
                    .multilineTextAlignment(.center)
                Text(t(
                    "Open a note, article, PDF, or connected source to read its summary and original content.",
                    "Откройте заметку, статью, PDF или подключенный источник, чтобы прочитать сводку и исходный материал."
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
        .accessibilityIdentifier("materials-regular-placeholder")
    }

    private func loadFolders() async {
        #if DEBUG
        if IOSTestingMode.current.isScreenshot {
            foldersModel.loadScreenshotFixtures()
            return
        }
        #endif

        await foldersModel.loadLibrary(apiClient: apiClient)
    }

    private func loadMaterialsFeed() async {
        #if DEBUG
        if IOSTestingMode.current.isScreenshot {
            feed.loadScreenshotFixtures()
            return
        }
        #endif

        await feed.load()
    }

    private var currentError: String? {
        foldersModel.error ?? feed.errorMessage
    }

    // MARK: - Unified search results

    @ViewBuilder
    private var searchList: some View {
        List {
            if feed.isSearching && feed.searchResults.isEmpty {
                ProgressView()
            } else if feed.searchResults.isEmpty {
                Text(t("No results", "Ничего не найдено"))
                    .font(Typography.bodySmall).foregroundStyle(Palette.textSecondary)
            } else {
                Section(header: Text(t("Results", "Результаты"))) {
                    ForEach(feed.searchResults, id: \.chunkId) { hit in
                        NavigationLink {
                            searchDestination(for: hit)
                        } label: {
                            searchHitRow(hit)
                        }
                    }
                }
            }
        }
        .listStyle(.insetGrouped)
    }

    @ViewBuilder
    private func searchDestination(for hit: UnifiedHit) -> some View {
        if hit.sourceKind == "item" {
            ItemDetailView(itemId: hit.parentId, apiClient: apiClient) {
                Task { await feed.load() }
            }
        } else {
            RecordingDetailView(recording: Recording(id: hit.parentId, type: .meeting, createdAt: Date()))
        }
    }

    private func searchHitRow(_ hit: UnifiedHit) -> some View {
        VStack(alignment: .leading, spacing: Spacing.xxs) {
            Text(hit.title ?? t("Untitled", "Без названия"))
                .font(Typography.body.weight(.medium)).lineLimit(1)
            Text(hit.snippet).font(Typography.bodySmall).foregroundStyle(Palette.textSecondary).lineLimit(2)
            Text(hit.sourceKind == "item" ? hit.kind.uppercased() : t("RECORDING", "ЗАПИСЬ"))
                .font(Typography.labelSmall).foregroundStyle(Palette.textTertiary)
        }
        .padding(.vertical, Spacing.xxs)
    }
}
