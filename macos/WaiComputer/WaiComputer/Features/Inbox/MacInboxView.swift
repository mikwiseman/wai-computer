import AppKit
import SwiftUI
import UniformTypeIdentifiers
import WaiComputerKit

extension UTType {
    /// In-app drag payload for moving inbox content (recordings, materials,
    /// Wai chats) between folders. Declared as an exported type in Info.plist
    /// so the identifier resolves without a runtime warning.
    static let waiInboxMove = UTType(exportedAs: "is.waiwai.computer.inbox-move")
}

/// Transferable identifier for dragging any inbox row onto a folder
/// (or onto Inbox / Trash) in the sidebar.
struct InboxDragItem: Codable, Transferable, Equatable {
    let kind: InboxSourceKind
    let id: String

    static var transferRepresentation: some TransferRepresentation {
        CodableRepresentation(contentType: .waiInboxMove)
    }
}

private enum InboxCreateMode {
    case record
    case file
    case paste
    case ask
}

private extension MacAccentChoice {
    var nsColor: NSColor {
        switch self {
        case .system:
            return .controlAccentColor
        case .amber:
            return .systemOrange
        case .blue:
            return .systemBlue
        case .green:
            return .systemGreen
        case .violet:
            return .systemPurple
        case .rose:
            return .systemPink
        case .graphite:
            return .systemGray
        }
    }
}

struct MacInboxView: View {
    let apiClient: APIClient
    let recordings: [Recording]
    let folders: [Folder]
    let initialSourceKind: InboxSourceKind?
    let folderId: String?
    let reloadToken: UUID
    let pendingDetail: InboxDetailRef?
    let pendingCommand: MacInboxCommand?
    let onStartRecording: () -> Void
    let onLibraryChanged: () async -> Void
    let onPendingDetailConsumed: () -> Void
    let onPendingCommandConsumed: () -> Void

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
    @State private var askDraft: String = ""
    @State private var pendingChatMessage: String?

    init(
        apiClient: APIClient,
        recordings: [Recording],
        folders: [Folder],
        initialSourceKind: InboxSourceKind? = nil,
        folderId: String? = nil,
        reloadToken: UUID = UUID(),
        pendingDetail: InboxDetailRef? = nil,
        pendingCommand: MacInboxCommand? = nil,
        onStartRecording: @escaping () -> Void,
        onLibraryChanged: @escaping () async -> Void,
        onPendingDetailConsumed: @escaping () -> Void = {},
        onPendingCommandConsumed: @escaping () -> Void = {}
    ) {
        self.apiClient = apiClient
        self.recordings = recordings
        self.folders = folders
        self.initialSourceKind = initialSourceKind
        self.folderId = folderId
        self.reloadToken = reloadToken
        self.pendingDetail = pendingDetail
        self.pendingCommand = pendingCommand
        self.onStartRecording = onStartRecording
        self.onLibraryChanged = onLibraryChanged
        self.onPendingDetailConsumed = onPendingDetailConsumed
        self.onPendingCommandConsumed = onPendingCommandConsumed
        _model = StateObject(wrappedValue: MacInboxViewModel(
            apiClient: apiClient,
            sourceKind: initialSourceKind,
            folderId: folderId
        ))
        _focusedCreateMode = State(initialValue: Self.defaultCreateMode(for: initialSourceKind))
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
        .onChangeCompat(of: selectedRowID) { _, _ in
            // Picking or clearing a selection returns a folder to its calm placeholder.
            folderComposerActive = false
        }
        .onChangeCompat(of: model.sourceKind) { _, next in
            // The composer only offers actions that match the current scope —
            // snap focus to that scope's default when it falls outside.
            if !allowedCreateModes.contains(focusedCreateMode) {
                focusedCreateMode = Self.defaultCreateMode(for: next)
            }
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
            Menu {
                Button {
                    selectedDetail = nil
                    focusCreateMode(.record)
                    onStartRecording()
                } label: {
                    Label(t("Record Now", "Записать сейчас"), systemImage: "waveform")
                }
                Button {
                    chooseFile()
                } label: {
                    Label(t("Upload File", "Загрузить файл"), systemImage: "square.and.arrow.down")
                }
                Button {
                    selectedDetail = nil
                    focusCreateMode(.paste)
                    folderComposerActive = true
                } label: {
                    Label(t("Paste Link or Text", "Вставить ссылку или текст"), systemImage: "link")
                }
                Button {
                    selectedDetail = nil
                    startAskThread()
                } label: {
                    Label(t("Wai", "Wai"), systemImage: "sparkles")
                }
            } label: {
                Image(systemName: "plus")
                    .font(.system(size: 15, weight: .semibold))
                    .frame(width: 30, height: 30)
            }
            .buttonStyle(.borderless)
            .menuStyle(.borderlessButton)
            .help(t("Add to Inbox", "Добавить в Инбокс"))
            .accessibilityLabel(t("New inbox item", "Новый объект в Инбоксе"))
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
                "Recordings, materials, and Wai agent threads in this folder",
                "Записи, материалы и агентские диалоги Wai в этой папке"
            )
        }
        return t(
            "Recordings, materials, and Wai agent threads in one place",
            "Записи, материалы и агентские диалоги Wai в одном месте"
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
                "Record now or upload an audio or video file.",
                "Запишите сейчас или загрузите аудио- или видеофайл."
            )
        case .item?:
            return t(
                "Upload a file or paste a link, note, or text.",
                "Загрузите файл или вставьте ссылку, заметку или текст."
            )
        case .chat?:
            return t(
                "Give Wai a task — search, remember, plan, or act.",
                "Дайте Wai задачу — искать, помнить, планировать или действовать."
            )
        case nil:
            return t(
                "Record, upload a file, paste a link or text, or give Wai a task.",
                "Запишите, загрузите файл, вставьте ссылку или текст, или дайте Wai задачу."
            )
        }
    }

    /// The create actions that match the current source scope. Being offered
    /// "Записать" while filtered to Материалы felt wrong — the composer
    /// mirrors what the user is looking at.
    private var allowedCreateModes: [InboxCreateMode] {
        switch model.sourceKind {
        case .recording?: return [.record, .file]
        case .item?: return [.file, .paste]
        case .chat?: return [.ask]
        case nil: return [.record, .file, .paste, .ask]
        }
    }

    private static func defaultCreateMode(for scope: InboxSourceKind?) -> InboxCreateMode {
        switch scope {
        case .recording?, nil: return .record
        case .item?: return .paste
        case .chat?: return .ask
        }
    }

    /// Focus a composer mode requested explicitly (menu bar, shortcuts,
    /// empty-state buttons). If the current scope hides that composer,
    /// widen the scope so the user sees what they asked for.
    private func focusCreateMode(_ mode: InboxCreateMode) {
        if !allowedCreateModes.contains(mode) {
            let scope: InboxSourceKind? = {
                switch mode {
                case .record: return .recording
                case .paste: return .item
                case .ask: return .chat
                case .file: return nil
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
                Text(t("Wai", "Wai")).tag(Optional.some(InboxSourceKind.chat))
                Text(t("All", "Все")).tag(Optional<InboxSourceKind>.none)
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
            if model.isLoading {
                ProgressView()
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if model.rows.isEmpty {
                MacInboxEmptyState(
                    sourceKind: model.sourceKind,
                    folderName: scopedFolder?.name,
                    onRecord: onStartRecording,
                    onUpload: chooseFile,
                    onPaste: {
                        selectedDetail = nil
                        focusCreateMode(.paste)
                        folderComposerActive = true
                    },
                    onChat: {
                        selectedDetail = nil
                        startAskThread()
                    }
                )
            } else {
                MacInboxRowsTable(
                    rows: model.rows,
                    language: languageManager.current,
                    selectedRowID: selectedRowID,
                    accentChoice: MacThemePreferences.currentAccent,
                    canLoadMore: model.nextCursor != nil,
                    isLoadingMore: model.isLoadingMore,
                    onSelect: { row in
                        selectedDetail = row.detail
                    },
                    onLoadMore: {
                        Task { await model.loadMore() }
                    }
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

    @ViewBuilder
    private func selectedDetailView(_ selectedDetail: InboxDetailRef) -> some View {
        switch selectedDetail.kind {
        case .recording:
            MacRecordingDetailView(
                recordingId: selectedDetail.id,
                initialDetail: nil,
                mode: .active,
                folders: folders,
                pendingTitleEditId: .constant(nil),
                onDelete: {
                    self.selectedDetail = nil
                    Task {
                        await model.load()
                        await onLibraryChanged()
                    }
                },
                onRestore: {
                    self.selectedDetail = nil
                    Task {
                        await model.load()
                        await onLibraryChanged()
                    }
                },
                onMoveToFolder: { _ in
                    Task {
                        await model.load()
                        await onLibraryChanged()
                    }
                },
                onDidRename: {
                    Task {
                        await model.load()
                        await onLibraryChanged()
                    }
                }
            )
            .id(selectedRowID)
        case .item:
            MacInboxItemDetail(
                apiClient: apiClient,
                itemId: selectedDetail.id,
                onDeleted: {
                    self.selectedDetail = nil
                    Task {
                        await model.load()
                        await onLibraryChanged()
                    }
                },
                onUpdated: {}
            )
            .id(selectedRowID)
        case .chat:
            CompanionView(
                apiClient: apiClient,
                recordings: recordings,
                initialChatId: selectedDetail.id,
                initialMessage: pendingChatMessage,
                onInitialMessageConsumed: { pendingChatMessage = nil },
                showsConversationSwitcher: false,
                viewingFolderId: folderId,
                onTurnCompleted: { completion in
                    MacWaiTaskNotificationCenter.shared.notifyTaskFinished(
                        title: t("Wai finished", "Wai закончил"),
                        body: completion.preview ?? t("Your Wai task is ready.", "Задача Wai готова."),
                        chatId: completion.chatId
                    )
                }
            )
            .environment(\.locale, MacDateFormatting.locale(for: languageManager.current))
            .companionAccentColor(Palette.accent)
            .id(selectedRowID)
        }
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
                                    accent: .green,
                                    isActive: focusedCreateMode == .file,
                                    action: { chooseFile() }
                                )
                            }
                            if allowedCreateModes.contains(.paste) {
                                MacInboxCreateAction(
                                    title: t("Paste", "Вставить"),
                                    subtitle: t("Link, note, or long text", "Ссылка, заметка или длинный текст"),
                                    systemImage: "link",
                                    accent: .blue,
                                    isActive: focusedCreateMode == .paste,
                                    action: { focusCreateMode(.paste) }
                                )
                            }
                            if allowedCreateModes.contains(.ask) {
                                MacInboxCreateAction(
                                    title: t("Wai", "Wai"),
                                    subtitle: t("Search, remember, plan, or act", "Искать, помнить, планировать или действовать"),
                                    systemImage: "sparkles",
                                    accent: .orange,
                                    isActive: focusedCreateMode == .ask,
                                    action: { focusCreateMode(.ask) }
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
                    case .paste:
                        MacInboxPasteComposer(
                            draft: $model.draft,
                            isAdding: model.isAdding,
                            submitTitle: pasteSubmitTitle,
                            onSubmit: addDraft
                        )
                    case .ask:
                        MacInboxAskComposer(
                            draft: $askDraft,
                            isWorking: model.isAdding,
                            onSubmit: { startAskThread(message: askDraft) },
                            onBlank: { startAskThread() }
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

    private var pasteSubmitTitle: String {
        let trimmed = model.draft.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if trimmed.hasPrefix("http://") || trimmed.hasPrefix("https://") {
            return t("Save Link", "Сохранить ссылку")
        }
        return t("Save Text", "Сохранить текст")
    }

    private var canStartInboxUpload: Bool {
        !model.isAdding && !model.uploadPhase.isWorking
    }

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

    private func addDraft() {
        Task {
            if let detail = await model.addDraft() {
                selectedDetail = detail
            }
            await onLibraryChanged()
        }
    }

    private func startAskThread(message: String? = nil) {
        let trimmed = message?.trimmingCharacters(in: .whitespacesAndNewlines)
        focusCreateMode(.ask)
        Task {
            if let detail = await model.newChat() {
                if let trimmed, !trimmed.isEmpty {
                    pendingChatMessage = trimmed
                }
                askDraft = ""
                selectedDetail = detail
            }
        }
    }

    private func consumePendingCommandIfNeeded() {
        guard let pendingCommand else { return }
        performInboxCommand(pendingCommand)
        onPendingCommandConsumed()
    }

    private func performInboxCommand(_ command: MacInboxCommand) {
        switch command {
        case .showCreatePane:
            selectedDetail = nil
            focusCreateMode(Self.defaultCreateMode(for: model.sourceKind))
        case .recordNow:
            selectedDetail = nil
            focusCreateMode(.record)
            onStartRecording()
        case .uploadFile:
            chooseFile()
        case .pasteLinkOrText:
            selectedDetail = nil
            focusCreateMode(.paste)
        case .askWai:
            selectedDetail = nil
            startAskThread()
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
                    .foregroundStyle(.green)
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
                .foregroundStyle(.green)
                .frame(width: 28, height: 28)
                .background(Color.green.opacity(0.12))
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

private struct MacInboxPasteComposer: View {
    @Binding var draft: String
    let isAdding: Bool
    let submitTitle: String
    let onSubmit: () -> Void

    @EnvironmentObject private var languageManager: LanguageManager

    private var trimmedDraft: String {
        draft.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            Text(t("Paste link or text", "Вставить ссылку или текст"))
                .font(Typography.headingMedium)
            TextField(
                t("Paste a link, note, transcript, or any text...", "Вставьте ссылку, заметку, транскрипт или любой текст..."),
                text: $draft,
                axis: .vertical
            )
            .textFieldStyle(.roundedBorder)
            .lineLimit(4...8)
            .onSubmit(onSubmit)
            .accessibilityIdentifier("mac-inbox-paste-field")

            HStack(spacing: Spacing.sm) {
                Button(action: onSubmit) {
                    if isAdding {
                        ProgressView().controlSize(.small)
                    } else {
                        Text(submitTitle)
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(trimmedDraft.isEmpty || isAdding)
                .accessibilityIdentifier("mac-inbox-paste-primary-button")

                if trimmedDraft.isEmpty {
                    Text(t("Paste text or a link to continue.", "Вставьте текст или ссылку, чтобы продолжить."))
                        .font(Typography.label)
                        .foregroundStyle(Palette.textSecondary)
                }
                Spacer()
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

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

private struct MacInboxInlineActionComposer: View {
    let systemImage: String
    let title: String
    let message: String
    let primaryTitle: String
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

private struct MacInboxAskComposer: View {
    @Binding var draft: String
    let isWorking: Bool
    let onSubmit: () -> Void
    let onBlank: () -> Void

    @EnvironmentObject private var languageManager: LanguageManager

    private var trimmed: String {
        draft.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            Text(t("New Wai Session", "Новая сессия Wai"))
                .font(Typography.headingMedium)
            TextField(
                t(
                    "Give Wai a task to search, remember, plan, or act...",
                    "Дайте Wai задачу: искать, помнить, планировать или действовать..."
                ),
                text: $draft,
                axis: .vertical
            )
            .textFieldStyle(.roundedBorder)
            .lineLimit(3...8)
            .onSubmit { if !trimmed.isEmpty { onSubmit() } }
            .accessibilityIdentifier("mac-inbox-ask-field")

            HStack(spacing: Spacing.sm) {
                Button(action: onSubmit) {
                    if isWorking {
                        ProgressView().controlSize(.small)
                    } else {
                        Text(t("Start", "Начать"))
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(trimmed.isEmpty || isWorking)
                .accessibilityIdentifier("mac-inbox-ask-primary-button")

                Button(t("Blank thread", "Пустой диалог"), action: onBlank)
                    .buttonStyle(.bordered)
                    .disabled(isWorking)
                Spacer()
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

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
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
    let onPaste: () -> Void
    let onChat: () -> Void

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

                    Button(action: onUpload) {
                        Label(t("Upload", "Загрузить"), systemImage: "square.and.arrow.down")
                    }
                    .buttonStyle(.bordered)
                case .item?:
                    Button(action: onUpload) {
                        Label(t("Upload", "Загрузить"), systemImage: "square.and.arrow.down")
                    }
                    .buttonStyle(.borderedProminent)

                    Button(action: onPaste) {
                        Label(t("Paste Link or Text", "Вставить ссылку или текст"), systemImage: "link")
                    }
                    .buttonStyle(.bordered)
                case .chat?:
                    Button(action: onChat) {
                        Label(t("New Wai Thread", "Новый диалог Wai"), systemImage: "sparkles")
                    }
                    .buttonStyle(.borderedProminent)
                case nil:
                    Button(action: onRecord) {
                        Label(t("Record", "Записать"), systemImage: "waveform")
                    }
                    .buttonStyle(.borderedProminent)

                    Button(action: onUpload) {
                        Label(t("Upload", "Загрузить"), systemImage: "square.and.arrow.down")
                    }
                    .buttonStyle(.bordered)

                    Button(action: onChat) {
                        Label(t("Wai", "Wai"), systemImage: "sparkles")
                    }
                    .buttonStyle(.bordered)

                    Menu {
                        Button(action: onPaste) {
                            Label(t("Paste Link or Text", "Вставить ссылку или текст"), systemImage: "link")
                        }
                    } label: {
                        Label(t("More", "Ещё"), systemImage: "ellipsis")
                    }
                    .buttonStyle(.bordered)
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
        case .chat: return "sparkles"
        case .none: return "tray.full"
        }
    }

    private var title: String {
        switch sourceKind {
        case .recording:
            return t("No Recordings Yet", "Записей пока нет")
        case .item:
            return t("No Materials Yet", "Материалов пока нет")
        case .chat:
            return t("No Wai Threads Yet", "Диалогов Wai пока нет")
        case .none:
            return folderName != nil
                ? t("This Folder Is Empty", "Эта папка пуста")
                : t("Inbox Is Empty", "Инбокс пуст")
        }
    }

    private var message: String {
        switch sourceKind {
        case .recording:
            return t("Record now or import audio/video.", "Запишите сейчас или импортируйте аудио/видео.")
        case .item:
            return t("Upload a file or paste a link/text.", "Загрузите файл или вставьте ссылку/текст.")
        case .chat:
            return t("Give Wai a task to search, remember, plan, or act.", "Дайте Wai задачу: искать, помнить, планировать или действовать.")
        case .none:
            return t(
                "Record, upload a file, paste a link, or give Wai a task.",
                "Запишите, загрузите файл, вставьте ссылку или дайте Wai задачу."
            )
        }
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

private struct MacInboxDisplayRow: Identifiable, Equatable {
    let id: String
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

    init(row: InboxRow, language: LanguageManager.SupportedLanguage) {
        id = row.id
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
            return text("Wai", "Wai", language: language)
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
            return "Wai"
        }
    }

    private static func displaySublabel(for row: InboxRow, language: LanguageManager.SupportedLanguage) -> String? {
        guard let sublabel = row.sublabel else { return nil }
        if row.sourceKind == .chat && sublabel == "Agent thread" {
            return text("Agent thread", "Агентский диалог", language: language)
        }
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
        case .chat: return "sparkles"
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

private struct MacInboxRowsTable: NSViewRepresentable {
    let rows: [InboxRow]
    let language: LanguageManager.SupportedLanguage
    let selectedRowID: String?
    let accentChoice: MacAccentChoice
    let canLoadMore: Bool
    let isLoadingMore: Bool
    let onSelect: (InboxRow) -> Void
    let onLoadMore: () -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(onSelect: onSelect, onLoadMore: onLoadMore)
    }

    func makeNSView(context: Context) -> NSScrollView {
        let tableView = NSTableView()
        tableView.identifier = NSUserInterfaceItemIdentifier("mac-inbox-rows")
        tableView.setAccessibilityIdentifier("mac-inbox-rows")
        tableView.headerView = nil
        tableView.backgroundColor = .clear
        tableView.usesAlternatingRowBackgroundColors = false
        tableView.usesAutomaticRowHeights = false
        tableView.rowHeight = MacInboxTableMetrics.rowHeight
        tableView.intercellSpacing = .zero
        tableView.gridStyleMask = []
        tableView.columnAutoresizingStyle = .uniformColumnAutoresizingStyle
        tableView.allowsMultipleSelection = false
        tableView.allowsEmptySelection = true
        tableView.selectionHighlightStyle = .none
        tableView.focusRingType = .none
        tableView.autoresizingMask = [.width]
        tableView.dataSource = context.coordinator
        tableView.delegate = context.coordinator
        tableView.target = context.coordinator
        tableView.action = #selector(Coordinator.rowClicked(_:))
        // Let recording rows be dragged onto sidebar folders (move-to-folder).
        tableView.setDraggingSourceOperationMask([.move, .copy], forLocal: true)

        let column = NSTableColumn(identifier: MacInboxTableMetrics.columnIdentifier)
        column.minWidth = 0
        column.resizingMask = .autoresizingMask
        tableView.addTableColumn(column)

        let scrollView = NSScrollView()
        scrollView.identifier = NSUserInterfaceItemIdentifier("mac-inbox-rows-scroll")
        scrollView.setAccessibilityIdentifier("mac-inbox-rows-scroll")
        scrollView.drawsBackground = false
        scrollView.hasVerticalScroller = true
        scrollView.hasHorizontalScroller = false
        scrollView.autohidesScrollers = true
        scrollView.borderType = .noBorder
        scrollView.contentView.postsBoundsChangedNotifications = true
        scrollView.documentView = tableView

        context.coordinator.tableView = tableView
        context.coordinator.scrollView = scrollView
        context.coordinator.observeScrollView(scrollView)
        return scrollView
    }

    func updateNSView(_ scrollView: NSScrollView, context: Context) {
        guard let tableView = scrollView.documentView as? NSTableView else { return }
        context.coordinator.onSelect = onSelect
        context.coordinator.onLoadMore = onLoadMore
        context.coordinator.update(
            rows: rows,
            language: language,
            selectedRowID: selectedRowID,
            accentChoice: accentChoice,
            canLoadMore: canLoadMore,
            isLoadingMore: isLoadingMore
        )
        if scrollView.contentView.bounds.width > 0, let column = tableView.tableColumns.first {
            column.width = scrollView.contentView.bounds.width
            tableView.frame.size.width = scrollView.contentView.bounds.width
        }
        if scrollView.contentView.bounds.origin.x != 0 {
            var origin = scrollView.contentView.bounds.origin
            origin.x = 0
            scrollView.contentView.scroll(to: origin)
            scrollView.reflectScrolledClipView(scrollView.contentView)
        }
        context.coordinator.maybeLoadMoreIfNeeded()
    }

    final class Coordinator: NSObject, NSTableViewDataSource, NSTableViewDelegate {
        var onSelect: (InboxRow) -> Void
        var onLoadMore: () -> Void
        weak var tableView: NSTableView?
        weak var scrollView: NSScrollView?
        private var rows: [InboxRow] = []
        private var displayRows: [MacInboxDisplayRow] = []
        private var lastInputRows: [InboxRow] = []
        private var lastLanguage: LanguageManager.SupportedLanguage?
        private var selectedRowID: String?
        private var accentChoice: MacAccentChoice = .system
        private var canLoadMore = false
        private var isLoadingMore = false
        private var didRequestLoadMore = false
        private var isApplyingSelection = false
        private var boundsObserver: NSObjectProtocol?

        init(onSelect: @escaping (InboxRow) -> Void, onLoadMore: @escaping () -> Void) {
            self.onSelect = onSelect
            self.onLoadMore = onLoadMore
        }

        deinit {
            if let boundsObserver {
                NotificationCenter.default.removeObserver(boundsObserver)
            }
        }

        func observeScrollView(_ scrollView: NSScrollView) {
            if let boundsObserver {
                NotificationCenter.default.removeObserver(boundsObserver)
            }
            boundsObserver = NotificationCenter.default.addObserver(
                forName: NSView.boundsDidChangeNotification,
                object: scrollView.contentView,
                queue: .main
            ) { [weak self] _ in
                self?.maybeLoadMoreIfNeeded()
            }
        }

        func update(
            rows: [InboxRow],
            language: LanguageManager.SupportedLanguage,
            selectedRowID: String?,
            accentChoice: MacAccentChoice,
            canLoadMore: Bool,
            isLoadingMore: Bool
        ) {
            // Memoize the (localize + date-format) row mapping. It is O(N) and
            // previously ran on every SwiftUI invalidation — selection changes,
            // the 2s status poll, any parent re-render — even when the underlying
            // rows were byte-identical, which showed up as scroll jank.
            let displayRows: [MacInboxDisplayRow]
            if rows == lastInputRows, language == lastLanguage {
                displayRows = self.displayRows
            } else {
                displayRows = rows.map { MacInboxDisplayRow(row: $0, language: language) }
                lastInputRows = rows
                lastLanguage = language
            }

            let accentChanged = self.accentChoice != accentChoice
            let oldDisplayRows = self.displayRows
            let rowsChanged = oldDisplayRows != displayRows

            self.rows = rows
            self.displayRows = displayRows
            self.selectedRowID = selectedRowID
            self.accentChoice = accentChoice
            self.canLoadMore = canLoadMore
            self.isLoadingMore = isLoadingMore
            if !isLoadingMore {
                didRequestLoadMore = false
            }

            if accentChanged {
                // Theme change re-tints every cell — full reload is correct and rare.
                tableView?.reloadData()
            } else if rowsChanged, let tableView {
                applyRowChanges(from: oldDisplayRows, to: displayRows, in: tableView)
            }
            applySelection()
        }

        /// Apply row changes incrementally so loading more pages keeps scroll
        /// position and a single status change doesn't relayout the whole list.
        private func applyRowChanges(
            from old: [MacInboxDisplayRow],
            to new: [MacInboxDisplayRow],
            in tableView: NSTableView
        ) {
            // Pure append (pagination): insert only the new tail.
            if new.count > old.count, Array(new.prefix(old.count)) == old {
                tableView.insertRows(
                    at: IndexSet(integersIn: old.count..<new.count),
                    withAnimation: []
                )
                return
            }
            // Same length: reload only the rows that actually changed.
            if new.count == old.count {
                var changed = IndexSet()
                for index in new.indices where new[index] != old[index] {
                    changed.insert(index)
                }
                if changed.isEmpty { return }
                if changed.count < new.count {
                    tableView.reloadData(forRowIndexes: changed, columnIndexes: IndexSet(integer: 0))
                    return
                }
            }
            // Wholesale change (scope/source switch, deletions, reorder).
            tableView.reloadData()
        }

        func numberOfRows(in tableView: NSTableView) -> Int {
            displayRows.count
        }

        func tableView(_ tableView: NSTableView, pasteboardWriterForRow row: Int) -> NSPasteboardWriting? {
            guard rows.indices.contains(row) else { return nil }
            let source = rows[row]
            let payload = InboxDragItem(kind: source.sourceKind, id: source.detail.id)
            guard let data = try? JSONEncoder().encode(payload) else {
                return nil
            }
            let item = NSPasteboardItem()
            item.setData(data, forType: NSPasteboard.PasteboardType(UTType.waiInboxMove.identifier))
            return item
        }

        func tableView(
            _ tableView: NSTableView,
            viewFor tableColumn: NSTableColumn?,
            row: Int
        ) -> NSView? {
            guard displayRows.indices.contains(row) else { return nil }
            let cell = tableView.makeView(
                withIdentifier: MacInboxTableMetrics.cellIdentifier,
                owner: self
            ) as? MacInboxTableCellView ?? MacInboxTableCellView(
                identifier: MacInboxTableMetrics.cellIdentifier
            )
            cell.configure(with: displayRows[row], accentColor: accentChoice.nsColor)
            return cell
        }

        func tableView(_ tableView: NSTableView, heightOfRow row: Int) -> CGFloat {
            MacInboxTableMetrics.rowHeight
        }

        func tableView(_ tableView: NSTableView, rowViewForRow row: Int) -> NSTableRowView? {
            let rowView = tableView.makeView(
                withIdentifier: MacInboxTableMetrics.rowIdentifier,
                owner: self
            ) as? MacInboxTableRowView ?? MacInboxTableRowView()
            rowView.identifier = MacInboxTableMetrics.rowIdentifier
            rowView.accentColor = accentChoice.nsColor
            return rowView
        }

        func tableViewSelectionDidChange(_ notification: Notification) {
            guard !isApplyingSelection, let tableView else { return }
            let selectedRow = tableView.selectedRow
            guard rows.indices.contains(selectedRow) else { return }
            guard selectedRowID != rows[selectedRow].id else { return }
            selectedRowID = rows[selectedRow].id
            onSelect(rows[selectedRow])
        }

        @objc
        func rowClicked(_ sender: NSTableView) {
            let clickedRow = sender.clickedRow
            guard rows.indices.contains(clickedRow) else { return }
            guard selectedRowID != rows[clickedRow].id else { return }
            selectedRowID = rows[clickedRow].id
            onSelect(rows[clickedRow])
        }

        private func applySelection() {
            guard let tableView else { return }
            let nextIndex: Int? = selectedRowID.flatMap { id in
                displayRows.firstIndex { $0.id == id }
            }
            if tableView.selectedRow == (nextIndex ?? -1) {
                return
            }
            isApplyingSelection = true
            defer { isApplyingSelection = false }
            if let nextIndex {
                tableView.selectRowIndexes(IndexSet(integer: nextIndex), byExtendingSelection: false)
            } else {
                tableView.deselectAll(nil)
            }
        }

        func maybeLoadMoreIfNeeded() {
            guard canLoadMore, !isLoadingMore, !didRequestLoadMore else { return }
            guard let tableView, !displayRows.isEmpty else { return }
            let visibleMaxY = tableView.visibleRect.maxY
            let contentHeight = tableView.rect(ofRow: displayRows.count - 1).maxY
            guard contentHeight > 0 else { return }
            let distanceToBottom = contentHeight - visibleMaxY
            guard distanceToBottom <= MacInboxTableMetrics.loadMoreThreshold else { return }
            didRequestLoadMore = true
            onLoadMore()
        }
    }
}

private enum MacInboxTableMetrics {
    static let rowHeight: CGFloat = 64
    static let loadMoreThreshold: CGFloat = 256
    static let columnIdentifier = NSUserInterfaceItemIdentifier("MacInboxRowsColumn")
    static let cellIdentifier = NSUserInterfaceItemIdentifier("MacInboxRowCell")
    static let rowIdentifier = NSUserInterfaceItemIdentifier("MacInboxTableRow")
}

private final class MacInboxTableRowView: NSTableRowView {
    var accentColor: NSColor = .controlAccentColor {
        didSet { needsDisplay = true }
    }

    override var isSelected: Bool {
        didSet { needsDisplay = true }
    }

    override func drawBackground(in dirtyRect: NSRect) {
        if isSelected {
            accentColor.withAlphaComponent(0.16).setFill()
            dirtyRect.fill()
        } else {
            NSColor.clear.setFill()
            dirtyRect.fill()
        }
    }

    override func drawSelection(in dirtyRect: NSRect) {
        drawBackground(in: dirtyRect)
    }
}

private final class MacInboxTableCellView: NSTableCellView {
    private let iconView = NSImageView()
    private let titleLabel = NSTextField(labelWithString: "")
    private let metadataLabel = NSTextField(labelWithString: "")
    private let statusLabel = NSTextField(labelWithString: "")

    init(identifier: NSUserInterfaceItemIdentifier) {
        super.init(frame: .zero)
        self.identifier = identifier
        setup()
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    func configure(with row: MacInboxDisplayRow, accentColor: NSColor) {
        iconView.image = NSImage(systemSymbolName: row.iconSystemName, accessibilityDescription: nil)?
            .withSymbolConfiguration(Self.iconSymbolConfiguration)
        iconView.contentTintColor = iconColor(for: row.sourceKind, accentColor: accentColor)
        titleLabel.stringValue = row.title
        metadataLabel.stringValue = row.metadata
        statusLabel.stringValue = row.statusLabel ?? ""
        statusLabel.isHidden = row.statusLabel == nil
        statusLabel.textColor = statusColor(for: row.statusTone)
        setAccessibilityLabel(row.accessibilityLabel)
    }

    private func setup() {
        wantsLayer = true
        layer?.backgroundColor = NSColor.clear.cgColor

        iconView.translatesAutoresizingMaskIntoConstraints = false
        iconView.imageScaling = .scaleProportionallyDown

        titleLabel.font = .systemFont(ofSize: 15, weight: .semibold)
        titleLabel.textColor = .labelColor
        titleLabel.lineBreakMode = .byTruncatingTail
        titleLabel.maximumNumberOfLines = 1
        titleLabel.translatesAutoresizingMaskIntoConstraints = false

        metadataLabel.font = .systemFont(ofSize: 12, weight: .medium)
        metadataLabel.textColor = .secondaryLabelColor
        metadataLabel.lineBreakMode = .byTruncatingTail
        metadataLabel.maximumNumberOfLines = 1
        metadataLabel.translatesAutoresizingMaskIntoConstraints = false

        statusLabel.font = .systemFont(ofSize: 11, weight: .medium)
        statusLabel.alignment = .right
        statusLabel.lineBreakMode = .byTruncatingTail
        statusLabel.maximumNumberOfLines = 1
        statusLabel.translatesAutoresizingMaskIntoConstraints = false
        statusLabel.setContentHuggingPriority(.required, for: .horizontal)
        statusLabel.setContentCompressionResistancePriority(.required, for: .horizontal)

        addSubview(iconView)
        addSubview(titleLabel)
        addSubview(metadataLabel)
        addSubview(statusLabel)
        imageView = iconView
        textField = titleLabel

        NSLayoutConstraint.activate([
            iconView.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 16),
            iconView.centerYAnchor.constraint(equalTo: centerYAnchor),
            iconView.widthAnchor.constraint(equalToConstant: 22),
            iconView.heightAnchor.constraint(equalToConstant: 22),

            titleLabel.leadingAnchor.constraint(equalTo: iconView.trailingAnchor, constant: 8),
            titleLabel.topAnchor.constraint(equalTo: topAnchor, constant: 11),
            titleLabel.trailingAnchor.constraint(lessThanOrEqualTo: statusLabel.leadingAnchor, constant: -8),

            statusLabel.centerYAnchor.constraint(equalTo: titleLabel.centerYAnchor),
            statusLabel.trailingAnchor.constraint(equalTo: trailingAnchor, constant: -16),
            statusLabel.widthAnchor.constraint(lessThanOrEqualToConstant: 96),

            metadataLabel.leadingAnchor.constraint(equalTo: titleLabel.leadingAnchor),
            metadataLabel.topAnchor.constraint(equalTo: titleLabel.bottomAnchor, constant: 3),
            metadataLabel.trailingAnchor.constraint(equalTo: trailingAnchor, constant: -16)
        ])
    }

    private func iconColor(for sourceKind: InboxSourceKind, accentColor: NSColor) -> NSColor {
        switch sourceKind {
        case .recording:
            return accentColor
        case .item:
            return .systemGreen
        case .chat:
            return .systemOrange
        }
    }

    private static let iconSymbolConfiguration = NSImage.SymbolConfiguration(pointSize: 15, weight: .medium)

    private func statusColor(for tone: MacInboxDisplayRow.StatusTone) -> NSColor {
        switch tone {
        case .neutral:
            return .secondaryLabelColor
        case .warning:
            return .systemOrange
        case .error:
            return .systemRed
        }
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
