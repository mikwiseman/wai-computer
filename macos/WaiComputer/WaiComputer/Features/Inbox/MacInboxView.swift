import AppKit
import SwiftUI
import UniformTypeIdentifiers
import WaiComputerKit

extension UTType {
    /// In-app drag payload for moving inbox content between folders. Declared
    /// as an exported type in Info.plist so the identifier resolves without a
    /// runtime warning.
    static let waiInboxMove = UTType(exportedAs: "is.waiwai.computer.inbox-move")
}

/// Transferable identifier for dragging any inbox row onto a folder
/// (or onto Inbox / Trash) in the sidebar.
struct InboxDragItem: Codable, Transferable, Equatable, Hashable {
    let kind: InboxSourceKind
    let id: String

    static var transferRepresentation: some TransferRepresentation {
        CodableRepresentation(contentType: .waiInboxMove)
    }
}

private enum InboxCreateMode {
    case record
    case file
}

struct MacInboxView: View {
    let apiClient: APIClient
    let folders: [Folder]
    let recordingsRevision: Int
    let foldersRevision: Int
    let initialSourceKind: InboxSourceKind?
    let folderId: String?
    let reloadToken: UUID
    let pendingDetail: InboxDetailRef?
    let pendingCommand: MacInboxCommand?
    let onSourceKindChanged: (InboxSourceKind) -> Void
    let onStartRecording: () -> Void
    let onLibraryChanged: () async -> Void
    let onPendingDetailConsumed: () -> Void
    let onPendingCommandConsumed: () -> Void
    /// Files a row into a folder; nil unfiles into Inbox. Backs the rows'
    /// "Move to Folder" context menu — the discoverable sibling of sidebar
    /// drag-and-drop.
    let onMoveRow: (InboxDragItem, String?) -> Void

    @EnvironmentObject private var languageManager: LanguageManager
    @StateObject private var model: MacInboxViewModel
    @State private var selectedDetail: InboxDetailRef?
    @State private var showingImporter = false
    @State private var focusedCreateMode: InboxCreateMode = .record
    /// In a folder, the right pane is a calm "nothing selected" placeholder by
    /// default (folders are for browsing). The add composer only appears when the
    /// user explicitly chooses to add — this keeps the giant "Add to Inbox" wall
    /// out of folder browsing. Always ignored in the Inbox (folderId == nil).
    @State private var folderComposerActive = false

    init(
        apiClient: APIClient,
        folders: [Folder],
        recordingsRevision: Int,
        foldersRevision: Int,
        initialSourceKind: InboxSourceKind? = nil,
        folderId: String? = nil,
        reloadToken: UUID = UUID(),
        pendingDetail: InboxDetailRef? = nil,
        pendingCommand: MacInboxCommand? = nil,
        onSourceKindChanged: @escaping (InboxSourceKind) -> Void = { _ in },
        onStartRecording: @escaping () -> Void,
        onLibraryChanged: @escaping () async -> Void,
        onPendingDetailConsumed: @escaping () -> Void = {},
        onPendingCommandConsumed: @escaping () -> Void = {},
        onMoveRow: @escaping (InboxDragItem, String?) -> Void = { _, _ in }
    ) {
        self.apiClient = apiClient
        self.folders = folders
        self.recordingsRevision = recordingsRevision
        self.foldersRevision = foldersRevision
        self.initialSourceKind = initialSourceKind
        self.folderId = folderId
        self.reloadToken = reloadToken
        self.pendingDetail = pendingDetail
        self.pendingCommand = pendingCommand
        self.onSourceKindChanged = onSourceKindChanged
        self.onStartRecording = onStartRecording
        self.onLibraryChanged = onLibraryChanged
        self.onPendingDetailConsumed = onPendingDetailConsumed
        self.onPendingCommandConsumed = onPendingCommandConsumed
        self.onMoveRow = onMoveRow
        _model = StateObject(wrappedValue: MacInboxViewModel(
            apiClient: apiClient,
            sourceKind: initialSourceKind,
            folderId: folderId
        ))
        _focusedCreateMode = State(initialValue: Self.defaultCreateMode(for: Self.visibleScope(initialSourceKind)))
    }

    private var importTypes: [UTType] {
        var types: [UTType] = [
            .pdf, .plainText, .html, .rtf, .commaSeparatedText, .json, .audio, .movie
        ]
        for ext in ["md", "doc", "docx", "pptx", "xlsx", "mkv", "webm", "opus", "ogg"] {
            if let type = UTType(filenameExtension: ext) {
                types.append(type)
            }
        }
        return types
    }

    private var selectedRowID: String? {
        guard let selectedDetail else { return nil }
        return "\(selectedDetail.kind.rawValue):\(selectedDetail.id)"
    }

    var body: some View {
        HStack(spacing: 0) {
            listPane
                .frame(minWidth: 340, idealWidth: 430, maxWidth: 520, maxHeight: .infinity, alignment: .topLeading)
            Divider()
            detailPane
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .task {
            await model.configureScope(sourceKind: initialSourceKind, folderId: folderId)
            await model.load()
            notifySourceKindChanged(model.sourceKind)
            consumePendingDetailIfNeeded()
            consumePendingCommandIfNeeded()
        }
        .onChangeCompat(of: initialSourceKind) { _, next in
            Task {
                await model.configureScope(sourceKind: next, folderId: folderId)
            }
        }
        .onChangeCompat(of: folderId) { _, next in
            folderComposerActive = false
            Task {
                await model.configureScope(sourceKind: initialSourceKind, folderId: next)
            }
        }
        .onChangeCompat(of: reloadToken) { _, _ in
            // A sidebar drag-and-drop move/trash happened — refresh the list so
            // the moved recording leaves this view immediately.
            Task { await model.load() }
        }
        .onChangeCompat(of: pendingDetail) { _, _ in
            consumePendingDetailIfNeeded()
        }
        .onChangeCompat(of: pendingCommand) { _, _ in
            consumePendingCommandIfNeeded()
        }
        .onChangeCompat(of: model.rows) { _, _ in
            consumePendingDetailIfNeeded()
        }
        .onChangeCompat(of: selectedRowID) { _, next in
            // Picking a row returns a folder to its calm placeholder. Clears are
            // programmatic (composer entry points null the selection right before
            // activating the composer) and must not undo the pane they just opened.
            if next != nil {
                folderComposerActive = false
            }
        }
        .onChangeCompat(of: model.sourceKind) { _, next in
            // The composer only offers actions that match the current scope —
            // snap focus to that scope's default when it falls outside.
            if !allowedCreateModes.contains(focusedCreateMode) {
                focusedCreateMode = Self.defaultCreateMode(for: next)
            }
            // The right pane follows the scope: a detail from another kind
            // gives way to this scope's composer. A detail that matches the
            // scope stays.
            if let open = selectedDetail, let scope = next, open.kind != scope {
                selectedDetail = nil
            }
            notifySourceKindChanged(next)
        }
        .dropDestination(for: URL.self) { urls, _ in
            handleDroppedFiles(urls)
        }
        .fileImporter(
            isPresented: $showingImporter,
            allowedContentTypes: importTypes,
            allowsMultipleSelection: false
        ) { result in
            if case let .success(urls) = result, let url = urls.first {
                selectUploadFile(url)
            } else if case let .failure(error) = result {
                model.errorMessage = error.localizedDescription
            }
        }
    }

    private var listPane: some View {
        VStack(spacing: 0) {
            header
            Divider()
            filters
            Divider()
            banners
            rows
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }

    private var header: some View {
        HStack(alignment: .center, spacing: Spacing.sm) {
            VStack(alignment: .leading, spacing: Spacing.xxs) {
                Text(headerTitle)
                    .font(Typography.displaySmall)
                Text(headerSubtitle)
                    .font(Typography.label)
                    .foregroundStyle(Palette.textSecondary)
            }
            Spacer()
            Button {
                performContextualNew()
            } label: {
                Image(systemName: "plus")
                    .font(.system(size: 15, weight: .semibold))
                    .frame(width: 30, height: 30)
            }
            .buttonStyle(.borderless)
            .help(contextualNewHelpText)
            .accessibilityLabel(t("New inbox item", "Новый объект в Инбоксе"))
            .accessibilityIdentifier("mac-inbox-contextual-new")
        }
        .padding(Spacing.lg)
    }

    private var scopedFolder: Folder? {
        guard let folderId else { return nil }
        return folders.first { $0.id == folderId }
    }

    private var headerTitle: String {
        scopedFolder?.name ?? t("Inbox", "Инбокс")
    }

    private var headerSubtitle: String {
        if scopedFolder != nil {
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

    private var createPaneTitle: String {
        if let folder = scopedFolder {
            return t("Add to \(folder.name)", "Добавить в \(folder.name)")
        }
        return t("Add to Inbox", "Добавить в Инбокс")
    }

    private var createPaneSubtitle: String {
        switch model.sourceKind {
        case .recording?:
            return t(
                "Record your microphone and computer audio.",
                "Запишите микрофон и звук компьютера."
            )
        case .item?:
            return t(
                "Upload a file.",
                "Загрузите файл."
            )
        case .chat?, nil:
            return t(
                "Record or upload a file.",
                "Запишите или загрузите файл."
            )
        }
    }

    private var contextualNewHelpText: String {
        model.sourceKind == .item
            ? t("Upload File", "Загрузить файл")
            : t("Record Now", "Записать сейчас")
    }

    /// The create actions that match the current source scope. Being offered
    /// "Записать" while filtered to Материалы felt wrong — the composer
    /// mirrors what the user is looking at.
    private var allowedCreateModes: [InboxCreateMode] {
        switch model.sourceKind {
        case .recording?: return [.record]
        case .item?: return [.file]
        case .chat?, nil: return [.record]
        }
    }

    private static func defaultCreateMode(for scope: InboxSourceKind?) -> InboxCreateMode {
        switch scope {
        case .recording?, .chat?, nil: return .record
        case .item?: return .file
        }
    }

    private static func visibleScope(_ sourceKind: InboxSourceKind?) -> InboxSourceKind? {
        sourceKind == .item ? .item : .recording
    }

    /// Focus a composer mode requested explicitly (menu bar, shortcuts,
    /// empty-state buttons). If the current scope hides that composer,
    /// widen the scope so the user sees what they asked for.
    private func focusCreateMode(_ mode: InboxCreateMode) {
        if !allowedCreateModes.contains(mode) {
            let scope: InboxSourceKind? = {
                switch mode {
                case .record: return .recording
                case .file: return .item
                }
            }()
            Task { await model.setSourceKind(scope) }
        }
        focusedCreateMode = mode
    }

    private var filters: some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            Picker(t("Source", "Источник"), selection: Binding(
                get: { model.sourceKind },
                set: { next in Task { await model.setSourceKind(next) } }
            )) {
                Text(t("Recordings", "Записи")).tag(Optional.some(InboxSourceKind.recording))
                Text(t("Materials", "Материалы")).tag(Optional.some(InboxSourceKind.item))
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .accessibilityLabel(t("Source", "Источник"))
        }
        .padding(.horizontal, Spacing.lg)
        .padding(.vertical, Spacing.md)
    }

    @ViewBuilder
    private var banners: some View {
        if let error = model.errorMessage {
            InlineMessageRow(
                systemImage: "exclamationmark.triangle.fill",
                message: error,
                color: .red,
                onDismiss: { model.errorMessage = nil }
            )
        }
        if let status = model.statusMessage {
            InlineMessageRow(
                systemImage: "checkmark.circle.fill",
                message: status,
                color: .green,
                onDismiss: { model.statusMessage = nil }
            )
        }
    }

    private var rows: some View {
        Group {
            // Spinner only on the first load — refreshes (drag-to-folder,
            // detail callbacks) keep the populated table mounted so the
            // NSScrollView and its scroll position survive the fetch.
            if model.isLoading && model.rows.isEmpty {
                ProgressView()
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if model.rows.isEmpty {
                MacInboxEmptyState(
                    sourceKind: model.sourceKind,
                    folderName: scopedFolder?.name,
                    onRecord: onStartRecording,
                    onUpload: openFileComposer
                )
            } else {
                MacInboxRowsList(
                    rows: model.rows,
                    rowsRevision: model.rowsRevision,
                    folders: folders,
                    language: languageManager.current,
                    selectedRowID: selectedRowID,
                    canLoadMore: model.nextCursor != nil,
                    isLoadingMore: model.isLoadingMore,
                    onSelect: { row in
                        selectedDetail = row.detail
                    },
                    onLoadMore: {
                        Task { await model.loadMore() }
                    },
                    onMove: onMoveRow
                )
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    @ViewBuilder
    private var detailPane: some View {
        if let selectedDetail {
            selectedDetailView(selectedDetail)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        } else if folderId != nil && !folderComposerActive {
            // Browsing a folder with nothing selected: keep it calm, no capture wall.
            folderDetailPlaceholder
        } else {
            createPane
        }
    }

    private var folderDetailPlaceholder: some View {
        VStack(spacing: Spacing.lg) {
            Image(systemName: "folder")
                .font(.system(size: 28, weight: .semibold))
                .foregroundStyle(Palette.accent)
                .frame(width: 60, height: 60)
                .background(Palette.accentSubtle)
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
            VStack(spacing: Spacing.xxs) {
                Text(scopedFolder?.name ?? t("Folder", "Папка"))
                    .font(Typography.displaySmall)
                Text(t(
                    "Select a recording or material on the left to open it here.",
                    "Выберите запись или материал слева, чтобы открыть здесь."
                ))
                .font(Typography.bodySmall)
                .foregroundStyle(Palette.textSecondary)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: 360)
            }
            Button {
                focusedCreateMode = .record
                folderComposerActive = true
            } label: {
                Label(t("Add to This Folder", "Добавить в эту папку"), systemImage: "plus")
            }
            .buttonStyle(.bordered)
            .accessibilityIdentifier("mac-folder-add")
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(Spacing.xl)
    }

    private func selectedDetailView(_ selectedDetail: InboxDetailRef) -> some View {
        // Equatable gate: inbox pagination flips @Published state (rows append,
        // isLoadingMore) on every page, which re-runs this body. The detail
        // subtree's closure props defeat SwiftUI's automatic skip, so without
        // the gate every page load re-diffed the open recording's whole
        // transcript List (~40ms hitch per page while flick-scrolling the
        // list). The host re-renders only when its Equatable inputs change.
        MacInboxDetailHost(
            detail: selectedDetail,
            folders: folders,
            recordingsRevision: recordingsRevision,
            foldersRevision: foldersRevision,
            apiClient: apiClient,
            onCloseDetail: {
                self.selectedDetail = nil
                Task {
                    await model.load()
                    await onLibraryChanged()
                }
            },
            onContentChanged: {
                Task {
                    await model.load()
                    await onLibraryChanged()
                }
            }
        )
        .equatable()
        .id(selectedRowID)
    }

    private var createPane: some View {
        GeometryReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: Spacing.lg) {
                    HStack(alignment: .top, spacing: Spacing.md) {
                        Image(systemName: scopedFolder != nil ? "folder" : "tray.full")
                            .font(.system(size: 24, weight: .semibold))
                            .foregroundStyle(Palette.accent)
                            .frame(width: 42, height: 42)
                            .background(Palette.accentSubtle)
                            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                        VStack(alignment: .leading, spacing: Spacing.xxs) {
                            Text(createPaneTitle)
                                .font(Typography.displaySmall)
                            Text(createPaneSubtitle)
                                .font(Typography.bodySmall)
                                .foregroundStyle(Palette.textSecondary)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        Spacer(minLength: 0)
                        if scopedFolder != nil {
                            Button {
                                folderComposerActive = false
                            } label: {
                                Image(systemName: "xmark")
                                    .font(.system(size: 13, weight: .semibold))
                            }
                            .buttonStyle(.borderless)
                            .help(t("Done", "Готово"))
                            .accessibilityLabel(t("Close add panel", "Закрыть панель добавления"))
                        }
                    }

                    if allowedCreateModes.count > 1 {
                        LazyVGrid(
                            columns: [
                                GridItem(.flexible(), spacing: Spacing.sm),
                                GridItem(.flexible(), spacing: Spacing.sm)
                            ],
                            spacing: Spacing.sm
                        ) {
                            if allowedCreateModes.contains(.record) {
                                MacInboxCreateAction(
                                    title: t("Record", "Записать"),
                                    subtitle: t("Microphone and system audio", "Микрофон и звук компьютера"),
                                    systemImage: "waveform",
                                    accent: Palette.accent,
                                    isActive: focusedCreateMode == .record,
                                    action: {
                                        // Recording needs no configuration — start immediately
                                        // instead of just switching the composer (felt like a no-op).
                                        focusCreateMode(.record)
                                        onStartRecording()
                                    }
                                )
                            }
                            if allowedCreateModes.contains(.file) {
                                MacInboxCreateAction(
                                    title: t("Upload File", "Загрузить файл"),
                                    subtitle: t("Audio, video, PDF, DOCX, TXT", "Аудио, видео, PDF, DOCX, TXT"),
                                    systemImage: "square.and.arrow.down",
                                    // Single-accent design: cards differ by glyph and
                                    // title. Raw .green/.blue/.orange collided with the
                                    // accent choices — Wai's orange rendered identical
                                    // to the default amber accent.
                                    accent: Palette.accent,
                                    isActive: focusedCreateMode == .file,
                                    // Mode switch must always succeed; picker/error
                                    // gating lives in openFileComposer.
                                    action: { openFileComposer() }
                                )
                            }
                        }
                    }

                    switch focusedCreateMode {
                    case .record:
                        MacInboxInlineActionComposer(
                            systemImage: "waveform",
                            title: scopedFolder != nil
                                ? t("Record into This Folder", "Записать в эту папку")
                                : t("Record into Inbox", "Записать в Инбокс"),
                            message: t(
                                "Start a new recording with microphone and system audio.",
                                "Начните новую запись с микрофоном и звуком компьютера."
                            ),
                            primaryTitle: t("Start Recording", "Начать запись"),
                            primaryAccessibilityIdentifier: "start-recording-button",
                            accent: Palette.accent,
                            isWorking: false,
                            action: onStartRecording
                        )
                    case .file:
                        MacInboxFileComposer(
                            selectedFile: model.selectedUploadFile,
                            phase: model.uploadPhase,
                            isAdding: model.isAdding,
                            onChoose: chooseFile,
                            onUpload: uploadPendingFile,
                            onRemove: { model.clearSelectedUploadFile() }
                        )
                    }
                }
                .padding(Spacing.xl)
                .frame(maxWidth: 720, alignment: .leading)
                .frame(maxWidth: .infinity, minHeight: proxy.size.height, alignment: .center)
            }
        }
        .dropDestination(for: URL.self) { urls, _ in
            handleDroppedFiles(urls)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }

    private var canStartInboxUpload: Bool {
        !model.isAdding && !model.uploadPhase.isWorking
    }

    /// Switch the right pane to the file composer. Navigation always succeeds —
    /// during an in-flight add this shows the upload's progress instead of an
    /// error banner; the picker only opens when a new choice can actually start.
    private func openFileComposer() {
        selectedDetail = nil
        focusCreateMode(.file)
        folderComposerActive = true
        if model.selectedUploadFile == nil, canStartInboxUpload {
            showingImporter = true
        }
    }

    /// Explicit picker request from inside the file composer ("Choose
    /// Another...", the drop-zone button).
    private func chooseFile() {
        guard canStartInboxUpload else {
            model.errorMessage = t(
                "Wait for the current Inbox action to finish.",
                "Дождитесь завершения текущего действия в Инбоксе."
            )
            return
        }
        selectedDetail = nil
        focusCreateMode(.file)
        folderComposerActive = true
        showingImporter = true
    }

    private func selectUploadFile(_ url: URL) {
        guard canStartInboxUpload else {
            model.errorMessage = t(
                "Wait for the current Inbox action to finish.",
                "Дождитесь завершения текущего действия в Инбоксе."
            )
            return
        }
        selectedDetail = nil
        focusCreateMode(.file)
        folderComposerActive = true
        model.selectUploadFile(url)
    }

    private func uploadPendingFile() {
        guard canStartInboxUpload else {
            model.errorMessage = t(
                "Wait for the current Inbox action to finish.",
                "Дождитесь завершения текущего действия в Инбоксе."
            )
            return
        }
        Task {
            if let detail = await model.submitSelectedUploadFile() {
                selectedDetail = detail
            }
            await onLibraryChanged()
        }
    }

    private func handleDroppedFiles(_ urls: [URL]) -> Bool {
        guard urls.count == 1, let url = urls.first else {
            model.errorMessage = t(
                "Drop one file at a time.",
                "Перетащите один файл за раз."
            )
            return false
        }
        selectUploadFile(url)
        return true
    }

    private func performContextualNew() {
        if model.sourceKind == .item {
            openFileComposer()
        } else {
            selectedDetail = nil
            focusCreateMode(.record)
            folderComposerActive = true
            onStartRecording()
        }
    }

    private func notifySourceKindChanged(_ sourceKind: InboxSourceKind?) {
        onSourceKindChanged(sourceKind == .item ? .item : .recording)
    }

    private func consumePendingCommandIfNeeded() {
        guard let pendingCommand else { return }
        performInboxCommand(pendingCommand)
        onPendingCommandConsumed()
    }

    private func performInboxCommand(_ command: MacInboxCommand) {
        switch command {
        case .contextualNew:
            performContextualNew()
        case .showCreatePane:
            selectedDetail = nil
            focusCreateMode(Self.defaultCreateMode(for: model.sourceKind))
            folderComposerActive = true
        case .recordNow:
            selectedDetail = nil
            focusCreateMode(.record)
            folderComposerActive = true
            onStartRecording()
        case .uploadFile:
            openFileComposer()
        }
    }

    private func consumePendingDetailIfNeeded() {
        guard let pendingDetail else { return }
        if let row = model.rows.first(where: {
            $0.detail.kind == pendingDetail.kind && $0.detail.id == pendingDetail.id
        }) {
            selectedDetail = row.detail
            onPendingDetailConsumed()
            return
        }
        selectedDetail = pendingDetail
        onPendingDetailConsumed()
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

/// Hosts the selected detail behind an Equatable wrapper so list-side state
/// churn (pagination, banners) cannot re-render it. Closures and the API
/// client are deliberately excluded from equality — they capture stable @State
/// storage and a stable client.
private struct MacInboxDetailHost: View, Equatable {
    let detail: InboxDetailRef
    let folders: [Folder]
    let recordingsRevision: Int
    let foldersRevision: Int
    let apiClient: APIClient
    let onCloseDetail: () -> Void
    let onContentChanged: () -> Void

    static func == (lhs: MacInboxDetailHost, rhs: MacInboxDetailHost) -> Bool {
        lhs.detail == rhs.detail
            && lhs.recordingsRevision == rhs.recordingsRevision
            && lhs.foldersRevision == rhs.foldersRevision
    }

    var body: some View {
        switch detail.kind {
        case .recording:
            MacRecordingDetailView(
                recordingId: detail.id,
                initialDetail: nil,
                mode: .active,
                folders: folders,
                pendingTitleEditId: .constant(nil),
                onDelete: onCloseDetail,
                onRestore: onCloseDetail,
                onMoveToFolder: { _ in onContentChanged() },
                onDidRename: onContentChanged
            )
        case .item:
            MacInboxItemDetail(
                apiClient: apiClient,
                itemId: detail.id,
                onDeleted: onCloseDetail,
                onUpdated: {}
            )
        case .chat:
            EmptyView()
        }
    }
}

private struct MacInboxFileComposer: View {
    let selectedFile: PendingInboxUploadFile?
    let phase: InboxUploadPhase
    let isAdding: Bool
    let onChoose: () -> Void
    let onUpload: () -> Void
    let onRemove: () -> Void

    @EnvironmentObject private var languageManager: LanguageManager

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            if let selectedFile {
                selectedFileRow(selectedFile)
            } else {
                emptyDropTarget
            }

            if let message = phase.message {
                HStack(spacing: Spacing.xs) {
                    if phase.isWorking {
                        ProgressView()
                            .controlSize(.small)
                    } else {
                        Image(systemName: phaseIconName)
                    }
                    Text(message)
                        .font(Typography.bodySmall)
                        .foregroundStyle(phaseColor)
                        .lineLimit(2)
                        .textSelection(.enabled)
                    Spacer(minLength: 0)
                }
                .accessibilityIdentifier("mac-inbox-upload-progress")
            }

            if selectedFile != nil {
                HStack(spacing: Spacing.sm) {
                    Button(action: onUpload) {
                        if phase.isWorking {
                            ProgressView()
                                .controlSize(.small)
                        } else {
                            Text(t("Upload", "Загрузить"))
                        }
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(phase.isWorking || isAdding)
                    .accessibilityIdentifier("mac-inbox-upload-primary-button")

                    Button(action: onChoose) {
                        Text(t("Choose Another...", "Выбрать другой..."))
                    }
                    .buttonStyle(.bordered)
                    .disabled(isAdding)

                    Spacer()
                }
            }
        }
        .padding(Spacing.lg)
        .background(Palette.surfaceSubtle)
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(Palette.border, lineWidth: 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }

    /// The drop zone doubles as the chooser button — one hero affordance
    /// instead of a title, an instruction line, and two buttons that did
    /// the same thing.
    private var emptyDropTarget: some View {
        Button(action: onChoose) {
            VStack(spacing: Spacing.xs) {
                Image(systemName: "square.and.arrow.down")
                    .font(.system(size: 22, weight: .semibold))
                    .foregroundStyle(Palette.accent)
                Text(t("Drop a file here", "Перетащите файл сюда"))
                    .font(Typography.headingMedium)
                Text(t("or click to choose one from your Mac", "или нажмите, чтобы выбрать с компьютера"))
                    .font(Typography.bodySmall)
                    .foregroundStyle(Palette.textSecondary)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, Spacing.lg)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("mac-inbox-upload-choose-button")
        .background(Palette.surfaceHover)
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(Palette.border, style: StrokeStyle(lineWidth: 1, dash: [5, 4]))
        )
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }

    private func selectedFileRow(_ file: PendingInboxUploadFile) -> some View {
        HStack(spacing: Spacing.sm) {
            Image(systemName: "doc.text")
                .foregroundStyle(Palette.accent)
                .frame(width: 28, height: 28)
                .background(Palette.accent.opacity(0.12))
                .clipShape(RoundedRectangle(cornerRadius: 7, style: .continuous))
            VStack(alignment: .leading, spacing: 2) {
                Text(file.filename)
                    .font(Typography.headingMedium)
                    .foregroundStyle(Palette.textPrimary)
                    .lineLimit(1)
                    .truncationMode(.middle)
                Text(fileMetadata(file))
                    .font(Typography.label)
                    .foregroundStyle(Palette.textSecondary)
                    .lineLimit(1)
            }
            Spacer(minLength: Spacing.sm)
            Button(action: onRemove) {
                Image(systemName: "xmark")
            }
            .buttonStyle(.plain)
            .disabled(isAdding)
            .help(t("Remove file", "Убрать файл"))
        }
        .padding(Spacing.md)
        .background(Palette.surfaceHover)
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(Palette.border, lineWidth: 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        .accessibilityIdentifier("mac-inbox-selected-file")
    }

    private func fileMetadata(_ file: PendingInboxUploadFile) -> String {
        let parts = [
            file.typeDescription,
            file.byteCount.map { Self.byteFormatter.string(fromByteCount: $0) }
        ].compactMap { $0 }.filter { !$0.isEmpty }
        return parts.isEmpty ? t("Ready to upload", "Готово к загрузке") : parts.joined(separator: " / ")
    }

    private var phaseIconName: String {
        switch phase {
        case .failed:
            return "exclamationmark.triangle.fill"
        case .added, .processing:
            return "checkmark.circle.fill"
        case .idle, .selected, .preparing, .uploading:
            return "info.circle"
        }
    }

    private var phaseColor: Color {
        switch phase {
        case .failed:
            return .red
        case .added, .processing:
            return .green
        case .idle, .selected, .preparing, .uploading:
            return Palette.textSecondary
        }
    }

    private static let byteFormatter: ByteCountFormatter = {
        let formatter = ByteCountFormatter()
        formatter.allowedUnits = [.useKB, .useMB, .useGB]
        formatter.countStyle = .file
        return formatter
    }()

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

private struct MacInboxInlineActionComposer: View {
    let systemImage: String
    let title: String
    let message: String
    let primaryTitle: String
    let primaryAccessibilityIdentifier: String?
    let accent: Color
    let isWorking: Bool
    let action: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: Spacing.md) {
            Image(systemName: systemImage)
                .font(.system(size: 18, weight: .semibold))
                .foregroundStyle(accent)
                .frame(width: 34, height: 34)
                .background(accent.opacity(0.12))
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
            VStack(alignment: .leading, spacing: Spacing.sm) {
                VStack(alignment: .leading, spacing: Spacing.xxs) {
                    Text(title)
                        .font(Typography.headingMedium)
                    Text(message)
                        .font(Typography.bodySmall)
                        .foregroundStyle(Palette.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Button(action: action) {
                    if isWorking {
                        ProgressView().controlSize(.small)
                    } else {
                        Text(primaryTitle)
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(isWorking)
                .optionalAccessibilityIdentifier(primaryAccessibilityIdentifier)
            }
            Spacer()
        }
        .padding(Spacing.lg)
        .background(Palette.surfaceSubtle)
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .stroke(Palette.border, lineWidth: 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
    }
}

private extension View {
    @ViewBuilder
    func optionalAccessibilityIdentifier(_ identifier: String?) -> some View {
        if let identifier {
            accessibilityIdentifier(identifier)
        } else {
            self
        }
    }
}

private struct MacInboxCreateAction: View {
    let title: String
    let subtitle: String
    let systemImage: String
    let accent: Color
    let isActive: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(alignment: .top, spacing: Spacing.sm) {
                Image(systemName: systemImage)
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundStyle(accent)
                    .frame(width: 32, height: 32)
                    .background(accent.opacity(0.12))
                    .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))

                VStack(alignment: .leading, spacing: Spacing.xxs) {
                    Text(title)
                        .font(Typography.headingMedium)
                        .foregroundStyle(Palette.textPrimary)
                    Text(subtitle)
                        .font(Typography.label)
                        .foregroundStyle(Palette.textSecondary)
                        .lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 0)
            }
            .padding(Spacing.md)
            .frame(maxWidth: .infinity, minHeight: 76, alignment: .topLeading)
            .background(isActive ? accent.opacity(0.12) : Palette.surfaceSubtle)
            .overlay(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .stroke(isActive ? accent.opacity(0.42) : Palette.border, lineWidth: 1)
            )
            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        }
        .buttonStyle(.plain)
        .accessibilityLabel(title)
        .accessibilityHint(subtitle)
    }
}

private struct MacInboxEmptyState: View {
    let sourceKind: InboxSourceKind?
    var folderName: String? = nil
    let onRecord: () -> Void
    let onUpload: () -> Void

    @EnvironmentObject private var languageManager: LanguageManager

    var body: some View {
        VStack(spacing: Spacing.lg) {
            Image(systemName: icon)
                .font(.system(size: 30, weight: .semibold))
                .foregroundStyle(Palette.accent)
                .frame(width: 62, height: 62)
                .background(Palette.accentSubtle)
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))

            VStack(spacing: Spacing.xs) {
                Text(title)
                    .font(Typography.displaySmall)
                Text(message)
                    .font(Typography.bodySmall)
                    .foregroundStyle(Palette.textSecondary)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
            }

            // Actions mirror the active scope — an empty Материалы list
            // offers material actions, not "Записать".
            HStack(spacing: Spacing.sm) {
                switch sourceKind {
                case .recording?:
                    Button(action: onRecord) {
                        Label(t("Record", "Записать"), systemImage: "waveform")
                    }
                    .buttonStyle(.borderedProminent)
                case .item?:
                    Button(action: onUpload) {
                        Label(t("Upload", "Загрузить"), systemImage: "square.and.arrow.down")
                    }
                    .buttonStyle(.borderedProminent)
                case .chat?, nil:
                    Button(action: onRecord) {
                        Label(t("Record", "Записать"), systemImage: "waveform")
                    }
                    .buttonStyle(.borderedProminent)
                }
            }
        }
        .padding(Spacing.xl)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var icon: String {
        switch sourceKind {
        case .recording: return "waveform"
        case .item: return "doc.text"
        case .none: return "tray.full"
        case .chat: return "tray.full"
        }
    }

    private var title: String {
        switch sourceKind {
        case .recording:
            return t("No Recordings Yet", "Записей пока нет")
        case .item:
            return t("No Materials Yet", "Материалов пока нет")
        case .none:
            return folderName != nil
                ? t("This Folder Is Empty", "Эта папка пуста")
                : t("Inbox Is Empty", "Инбокс пуст")
        case .chat:
            return folderName != nil
                ? t("This Folder Is Empty", "Эта папка пуста")
                : t("Inbox Is Empty", "Инбокс пуст")
        }
    }

    private var message: String {
        switch sourceKind {
        case .recording:
            return t("Start a new recording.", "Начните новую запись.")
        case .item:
            return t("Upload a file.", "Загрузите файл.")
        case .none:
            return t(
                "Start a new recording.",
                "Начните новую запись."
            )
        case .chat:
            return t(
                "Start a new recording.",
                "Начните новую запись."
            )
        }
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

private struct MacInboxDisplayRow: Identifiable, Equatable {
    let id: String
    let index: Int
    let detail: InboxDetailRef
    let sourceKind: InboxSourceKind
    let title: String
    let metadata: String
    let statusLabel: String?
    let statusTone: StatusTone
    let iconSystemName: String
    let accessibilityLabel: String

    enum StatusTone: Equatable {
        case neutral
        case warning
        case error
    }

    init(row: InboxRow, index: Int, language: LanguageManager.SupportedLanguage) {
        id = row.id
        self.index = index
        detail = row.detail
        sourceKind = row.sourceKind
        title = Self.title(for: row, language: language)
        metadata = Self.metadata(for: row, language: language)
        statusLabel = Self.statusLabel(for: row.status, language: language)
        statusTone = Self.statusTone(for: row.status)
        iconSystemName = Self.iconSystemName(for: row.sourceKind)
        accessibilityLabel = [title, metadata, statusLabel].compactMap { $0 }.joined(separator: ", ")
    }

    private static func title(for row: InboxRow, language: LanguageManager.SupportedLanguage) -> String {
        let trimmed = (row.title ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        if !trimmed.isEmpty { return trimmed }
        switch row.sourceKind {
        case .recording:
            return text("Untitled Recording", "Запись без названия", language: language)
        case .item:
            return text("Untitled Material", "Материал без названия", language: language)
        case .chat:
            return text("Untitled Material", "Материал без названия", language: language)
        }
    }

    private static func metadata(for row: InboxRow, language: LanguageManager.SupportedLanguage) -> String {
        var parts: [String] = [sourceLabel(for: row.sourceKind, language: language)]
        if let sublabel = displaySublabel(for: row, language: language) {
            parts.append(sublabel)
        }
        parts.append(MacDateFormatting.string(
            from: row.activityAt,
            dateStyle: .medium,
            timeStyle: .short,
            language: language
        ))
        if let duration = row.durationSeconds {
            parts.append(formatDuration(duration))
        }
        return parts.joined(separator: " / ")
    }

    private static func sourceLabel(
        for sourceKind: InboxSourceKind,
        language: LanguageManager.SupportedLanguage
    ) -> String {
        switch sourceKind {
        case .recording:
            return text("Recording", "Запись", language: language)
        case .item:
            return text("Material", "Материал", language: language)
        case .chat:
            return text("Material", "Материал", language: language)
        }
    }

    private static func displaySublabel(for row: InboxRow, language: LanguageManager.SupportedLanguage) -> String? {
        guard let sublabel = row.sublabel else { return nil }
        return sublabel
    }

    private static func statusLabel(
        for status: InboxStatus,
        language: LanguageManager.SupportedLanguage
    ) -> String? {
        switch status {
        case .ready:
            return nil
        case .processing:
            return text("Processing", "В работе", language: language)
        case .needsInput:
            return text("Needs Input", "Нужен ввод", language: language)
        case .failed:
            return text("Failed", "Ошибка", language: language)
        case .archived:
            return text("Archived", "Архив", language: language)
        }
    }

    private static func statusTone(for status: InboxStatus) -> StatusTone {
        switch status {
        case .failed, .needsInput:
            return .error
        case .processing:
            return .warning
        case .ready, .archived:
            return .neutral
        }
    }

    private static func iconSystemName(for sourceKind: InboxSourceKind) -> String {
        switch sourceKind {
        case .recording: return "waveform"
        case .item: return "doc.text"
        case .chat: return "doc.text"
        }
    }

    private static func formatDuration(_ seconds: Int) -> String {
        let mins = seconds / 60
        let secs = seconds % 60
        return String(format: "%d:%02d", mins, secs)
    }

    private static func text(
        _ english: String,
        _ russian: String,
        language: LanguageManager.SupportedLanguage
    ) -> String {
        OnboardingL10n.text(english, russian, language: language)
    }
}

/// Inbox rows in a SwiftUI `List` (NSTableView-backed, rows reused by AppKit).
///
/// This was previously a custom NSScrollView/NSTableView representable. On
/// macOS 26 its scrolling dirtied the window's layout path on every wheel
/// frame, which re-entered `NSHostingView.layout()` →
/// `invalidateSizeConstraintsIfNecessary()` → `minSize()` → a full root
/// ViewGraph re-measure: ~55–118ms of main-thread work per scroll event on a
/// months-deep inbox — felt as scrolling that freezes and sticks. A
/// SwiftUI-managed List scrolls without re-entering SwiftUI layout (measured
/// ~10× cheaper in the same window), so the representable is gone.
private struct MacInboxRowsList: View {
    let rows: [InboxRow]
    let rowsRevision: MacInboxRowsRevision
    let folders: [Folder]
    let language: LanguageManager.SupportedLanguage
    let selectedRowID: String?
    let canLoadMore: Bool
    let isLoadingMore: Bool
    let onSelect: (InboxRow) -> Void
    let onLoadMore: () -> Void
    let onMove: (InboxDragItem, String?) -> Void

    /// Memoizes the O(N) localize + date-format row mapping across
    /// re-renders, and maps only the appended tail on pagination — the same
    /// motivation as the old coordinator cache, minus the full re-map per page.
    @State private var displayCache = MacInboxDisplayRowCache()

    /// Trigger pagination when one of the last few rows appears —
    /// matches the old 256px-before-bottom threshold (4 × 64pt rows).
    private static let loadMoreLookahead = 4

    var body: some View {
        let displayRows = displayCache.displayRows(
            for: rows,
            revision: rowsRevision,
            language: language
        )
        List {
            ForEach(displayRows) { display in
                draggableRow(display, index: display.index)
                    .listRowInsets(EdgeInsets())
                    .listRowSeparator(.hidden)
                    .listRowBackground(
                        display.id == selectedRowID
                            ? Palette.accent.opacity(0.16)
                            : Color.clear
                    )
                    .onAppear {
                        if display.index >= displayRows.count - Self.loadMoreLookahead,
                           canLoadMore, !isLoadingMore {
                            onLoadMore()
                        }
                    }
            }
            if isLoadingMore {
                HStack {
                    Spacer()
                    ProgressView()
                        .controlSize(.small)
                    Spacer()
                }
                .frame(height: 44)
                .listRowInsets(EdgeInsets())
                .listRowSeparator(.hidden)
                .listRowBackground(Color.clear)
            }
        }
        .listStyle(.plain)
        .scrollContentBackground(.hidden)
        .accessibilityIdentifier("mac-inbox-rows")
    }

    private func draggableRow(_ display: MacInboxDisplayRow, index: Int) -> some View {
        // Every visible inbox kind files into folders. The context menu is the
        // same move, discoverable and keyboardable.
        MacInboxListRow(
            display: display,
            onSelect: { onSelect(rows[index]) }
        )
        .draggable(InboxDragItem(kind: display.sourceKind, id: display.detail.id))
        .contextMenu {
            Menu(Self.text("Move to Folder", "Переместить в папку", language: language)) {
                Button(Self.text("Inbox (no folder)", "Инбокс (без папки)", language: language)) {
                    onMove(InboxDragItem(kind: display.sourceKind, id: display.detail.id), nil)
                }
                if !folders.isEmpty {
                    Divider()
                    ForEach(folders) { folder in
                        Button(folder.name) {
                            onMove(InboxDragItem(kind: display.sourceKind, id: display.detail.id), folder.id)
                        }
                    }
                }
            }
        }
    }

    private static func text(
        _ english: String,
        _ russian: String,
        language: LanguageManager.SupportedLanguage
    ) -> String {
        OnboardingL10n.text(english, russian, language: language)
    }
}

/// One inbox row — mirrors the old NSTableCellView layout (icon 22pt at
/// leading 16, semibold title with trailing status, secondary metadata line,
/// fixed 64pt height).
private struct MacInboxListRow: View {
    let display: MacInboxDisplayRow
    let onSelect: () -> Void

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: display.iconSystemName)
                .font(.system(size: 15, weight: .medium))
                .foregroundStyle(iconColor)
                .frame(width: 22, height: 22)

            VStack(alignment: .leading, spacing: 3) {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text(display.title)
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundStyle(Palette.textPrimary)
                        .lineLimit(1)
                        .truncationMode(.tail)
                    Spacer(minLength: 0)
                    if let status = display.statusLabel {
                        // Label-on-tint pill: the tone color is only a 15%
                        // background tint, never the text color — 11pt
                        // orange/red text failed WCAG AA (~2.2:1).
                        Text(status)
                            .font(.system(size: 12, weight: .medium))
                            .foregroundStyle(Palette.textPrimary)
                            .lineLimit(1)
                            .padding(.horizontal, 8)
                            .padding(.vertical, 2)
                            .background(statusTint.opacity(0.15), in: Capsule())
                            .layoutPriority(1)
                    }
                }
                Text(display.metadata)
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(Palette.textSecondary)
                    .lineLimit(1)
                    .truncationMode(.tail)
            }
        }
        .padding(.horizontal, 16)
        .frame(height: 64)
        .contentShape(Rectangle())
        .onTapGesture(perform: onSelect)
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(display.accessibilityLabel)
        .accessibilityAddTraits(.isButton)
    }

    /// All kinds share the accent: modes differ by glyph + title, so the
    /// rows stay legible under any user accent choice (hardcoded green/orange
    /// collided with the amber default).
    private var iconColor: Color {
        Palette.accent
    }

    private var statusTint: Color {
        switch display.statusTone {
        case .neutral:
            return Palette.textSecondary
        case .warning:
            return .orange
        case .error:
            return .red
        }
    }
}

/// Append-aware memo for the row display mapping. Held in `@State` so the
/// cache survives re-renders; mutating it during body evaluation is fine —
/// it is plain storage, not observed state.
private final class MacInboxDisplayRowCache {
    private var lastRevision: MacInboxRowsRevision?
    private var lastLanguage: LanguageManager.SupportedLanguage?
    private var cached: [MacInboxDisplayRow] = []

    func displayRows(
        for rows: [InboxRow],
        revision: MacInboxRowsRevision,
        language: LanguageManager.SupportedLanguage
    ) -> [MacInboxDisplayRow] {
        if revision == lastRevision, language == lastLanguage {
            return cached
        }
        if language == lastLanguage,
           let appendStartIndex = revision.appendedFromIndex,
           appendStartIndex == cached.count,
           rows.count >= appendStartIndex {
            // Pagination append: map only the new tail.
            cached.append(contentsOf: rows[appendStartIndex...].enumerated().map { offset, row in
                MacInboxDisplayRow(row: row, index: appendStartIndex + offset, language: language)
            })
        } else {
            cached = rows.enumerated().map { index, row in
                MacInboxDisplayRow(row: row, index: index, language: language)
            }
        }
        lastRevision = revision
        lastLanguage = language
        return cached
    }
}

private struct MacInboxItemDetail: View {
    let apiClient: APIClient
    let itemId: String
    let onDeleted: () -> Void
    let onUpdated: () -> Void
    @EnvironmentObject private var languageManager: LanguageManager
    @State private var item: Item?
    @State private var errorMessage: String?
    @State private var isLoading = true
    @State private var isDeleting = false
    @State private var isGeneratingSummaryAudio = false
    @State private var isDownloadingSummaryAudio = false
    @State private var isPlayingSummaryAudio = false
    @State private var summaryAudioPlayer: (any MacSummaryAudioPlaying)?
    @State private var summaryAudioPlaybackToken = UUID()

    var body: some View {
        Group {
            if isLoading {
                ProgressView()
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if let item {
                MacItemDetailView(
                    item: item,
                    onDelete: {
                        Task {
                            await deleteItem()
                        }
                    },
                    isGeneratingSummaryAudio: isGeneratingSummaryAudio ||
                        item.summaryAudio?.isActive == true,
                    isDownloadingSummaryAudio: isDownloadingSummaryAudio,
                    isPlayingSummaryAudio: isPlayingSummaryAudio,
                    onGenerateSummaryAudio: {
                        Task { await startSummaryAudioGeneration() }
                    },
                    onPlaySummaryAudio: {
                        Task { await playOrStopSummaryAudio() }
                    }
                )
            } else {
                ContentUnavailableViewCompat(
                    t("Item unavailable", "Материал недоступен"),
                    systemImage: "doc.questionmark",
                    description: Text(errorMessage ?? "")
                )
            }
        }
        .task(id: itemId) {
            await load(showLoading: true)
            while !Task.isCancelled {
                guard let item, item.status == "fetching" || item.status == "summarizing" else {
                    break
                }
                try? await Task.sleep(nanoseconds: 2_000_000_000)
                guard !Task.isCancelled else { break }
                await load(showLoading: false)
            }
        }
    }

    private func load(showLoading: Bool) async {
        if showLoading {
            isLoading = true
        }
        defer {
            if showLoading {
                isLoading = false
            }
        }
        do {
            item = try await apiClient.getItem(id: itemId)
            errorMessage = nil
            onUpdated()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func deleteItem() async {
        guard !isDeleting else { return }
        isDeleting = true
        defer { isDeleting = false }
        do {
            try await apiClient.deleteItem(id: itemId)
            onDeleted()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func startSummaryAudioGeneration() async {
        guard !isGeneratingSummaryAudio else { return }
        isGeneratingSummaryAudio = true
        defer { isGeneratingSummaryAudio = false }
        do {
            let state = try await apiClient.startItemSummaryAudio(itemId: itemId)
            item = item?.withSummaryAudio(state)
            await pollSummaryAudioUntilReady()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func pollSummaryAudioUntilReady() async {
        for _ in 0..<30 {
            try? await Task.sleep(nanoseconds: 2_000_000_000)
            guard !Task.isCancelled else { return }
            do {
                let latest = try await apiClient.getItem(id: itemId)
                item = latest
                if latest.summaryAudio?.isActive != true {
                    onUpdated()
                    return
                }
            } catch {
                errorMessage = error.localizedDescription
                return
            }
        }
    }

    private func playOrStopSummaryAudio() async {
        if isPlayingSummaryAudio {
            stopSummaryAudioPlayback()
            return
        }

        isDownloadingSummaryAudio = true
        defer { isDownloadingSummaryAudio = false }
        do {
            let data = try await apiClient.downloadItemSummaryAudio(itemId: itemId)
            let player = try MacSummaryAudioPlayback.makePlayer(data: data)
            _ = player.prepareToPlay()
            guard player.play() else {
                throw NSError(
                    domain: "MacSummaryAudioPlayback",
                    code: 1,
                    userInfo: [NSLocalizedDescriptionKey: "Could not play summary audio."]
                )
            }
            summaryAudioPlayer?.stop()
            summaryAudioPlayer = player
            isPlayingSummaryAudio = true

            let token = UUID()
            summaryAudioPlaybackToken = token
            let duration = max(player.duration, 0)
            Task { @MainActor in
                if duration > 0 {
                    try? await Task.sleep(nanoseconds: UInt64((duration + 0.25) * 1_000_000_000))
                } else {
                    try? await Task.sleep(for: .seconds(1))
                }
                guard summaryAudioPlaybackToken == token else { return }
                isPlayingSummaryAudio = false
                summaryAudioPlayer = nil
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func stopSummaryAudioPlayback() {
        summaryAudioPlaybackToken = UUID()
        summaryAudioPlayer?.stop()
        summaryAudioPlayer = nil
        isPlayingSummaryAudio = false
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

private struct InlineMessageRow: View {
    @EnvironmentObject private var languageManager: LanguageManager
    let systemImage: String
    let message: String
    let color: Color
    let onDismiss: () -> Void

    var body: some View {
        HStack(spacing: Spacing.xs) {
            Image(systemName: systemImage)
                .foregroundStyle(color)
            Text(message)
                .font(Typography.bodySmall)
                .foregroundStyle(color)
                .lineLimit(3)
            Spacer()
            Button(action: onDismiss) {
                Image(systemName: "xmark")
            }
            .buttonStyle(.plain)
            .help(OnboardingL10n.text("Dismiss", "Закрыть", language: languageManager.current))
            .accessibilityLabel(OnboardingL10n.text("Dismiss", "Закрыть", language: languageManager.current))
        }
        .padding(.horizontal, Spacing.lg)
        .padding(.vertical, Spacing.sm)
        .background(Palette.surfaceSubtle)
    }
}
