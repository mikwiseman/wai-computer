import AppKit
import SwiftUI
import UniformTypeIdentifiers
import WaiComputerKit

extension UTType {
    /// In-app drag payload for moving a recording between folders.
    /// Declared as an exported type in Info.plist so the identifier resolves
    /// without a runtime warning.
    static let waiRecordingMove = UTType(exportedAs: "is.waiwai.computer.recording-move")
}

/// Transferable identifier for dragging a recording row onto a folder
/// (or onto Inbox / Trash) in the sidebar. Recordings are the only items that
/// live in folders, so only recording rows vend this payload.
struct RecordingDragItem: Codable, Transferable, Equatable {
    let recordingId: String

    static var transferRepresentation: some TransferRepresentation {
        CodableRepresentation(contentType: .waiRecordingMove)
    }
}

private enum InboxCreateMode {
    case record
    case file
    case paste
    case ask
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
    @State private var focusedCreateMode: InboxCreateMode = .file
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
                    focusedCreateMode = .record
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
                    focusedCreateMode = .paste
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
        t(
            "Record, upload a file, paste a link or text, or give Wai a task.",
            "Запишите, загрузите файл, вставьте ссылку или текст, или дайте Wai задачу."
        )
    }

    private var filters: some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            Picker(t("Source", "Источник"), selection: Binding(
                get: { model.sourceKind },
                set: { next in Task { await model.setSourceKind(next) } }
            )) {
                Text(t("All", "Все")).tag(Optional<InboxSourceKind>.none)
                Text(t("Recordings", "Записи")).tag(Optional.some(InboxSourceKind.recording))
                Text(t("Materials", "Материалы")).tag(Optional.some(InboxSourceKind.item))
                Text(t("Wai", "Wai")).tag(Optional.some(InboxSourceKind.chat))
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
                        focusedCreateMode = .paste
                        folderComposerActive = true
                    },
                    onChat: {
                        selectedDetail = nil
                        startAskThread()
                    }
                )
            } else {
                MacInboxRowsList(
                    rows: model.rows,
                    language: languageManager.current,
                    selectedRowID: selectedRowID,
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

    private func selectedDetailView(_ selectedDetail: InboxDetailRef) -> some View {
        // Equatable gate: inbox pagination flips @Published state (rows append,
        // isLoadingMore) on every page, which re-runs this body. The detail
        // subtree's closure props defeat SwiftUI's automatic skip, so without
        // the gate every page load re-diffed the open recording's whole
        // transcript List (~40ms hitch per page while flick-scrolling the
        // list). The host re-renders only when its Equatable inputs change.
        MacInboxDetailHost(
            detail: selectedDetail,
            recordings: recordings,
            folders: folders,
            viewingFolderId: folderId,
            pendingChatMessage: pendingChatMessage,
            language: languageManager.current,
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
            },
            onPendingChatMessageConsumed: { pendingChatMessage = nil }
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

                    LazyVGrid(
                        columns: [
                            GridItem(.flexible(), spacing: Spacing.sm),
                            GridItem(.flexible(), spacing: Spacing.sm)
                        ],
                        spacing: Spacing.sm
                    ) {
                        MacInboxCreateAction(
                            title: t("Record", "Записать"),
                            subtitle: t("Microphone and system audio", "Микрофон и звук компьютера"),
                            systemImage: "waveform",
                            accent: Palette.accent,
                            isActive: focusedCreateMode == .record,
                            action: {
                                // Recording needs no configuration — start immediately
                                // instead of just switching the composer (felt like a no-op).
                                focusedCreateMode = .record
                                onStartRecording()
                            }
                        )
                        MacInboxCreateAction(
                            title: t("Upload File", "Загрузить файл"),
                            subtitle: t("Audio, video, PDF, DOCX, TXT", "Аудио, видео, PDF, DOCX, TXT"),
                            systemImage: "square.and.arrow.down",
                            accent: .green,
                            isActive: focusedCreateMode == .file,
                            action: { chooseFile() }
                        )
                        MacInboxCreateAction(
                            title: t("Paste", "Вставить"),
                            subtitle: t("Link, note, or long text", "Ссылка, заметка или длинный текст"),
                            systemImage: "link",
                            accent: .blue,
                            isActive: focusedCreateMode == .paste,
                            action: { focusedCreateMode = .paste }
                        )
                        MacInboxCreateAction(
                            title: t("Wai", "Wai"),
                            subtitle: t("Search, remember, plan, or act", "Искать, помнить, планировать или действовать"),
                            systemImage: "sparkles",
                            accent: .orange,
                            isActive: focusedCreateMode == .ask,
                            action: {
                                focusedCreateMode = .ask
                            }
                        )
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
        focusedCreateMode = .file
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
        focusedCreateMode = .file
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
        focusedCreateMode = .ask
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
            focusedCreateMode = .file
        case .recordNow:
            selectedDetail = nil
            focusedCreateMode = .record
            onStartRecording()
        case .uploadFile:
            chooseFile()
        case .pasteLinkOrText:
            selectedDetail = nil
            focusedCreateMode = .paste
        case .askWai:
            selectedDetail = nil
            focusedCreateMode = .ask
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

/// Hosts the selected detail (recording / material / Wai chat) behind an
/// Equatable wrapper so list-side state churn (pagination, banners) cannot
/// re-render it. Closures and the API client are deliberately excluded from
/// equality — they capture stable @State storage and a stable client.
private struct MacInboxDetailHost: View, Equatable {
    let detail: InboxDetailRef
    let recordings: [Recording]
    let folders: [Folder]
    let viewingFolderId: String?
    let pendingChatMessage: String?
    let language: LanguageManager.SupportedLanguage
    let apiClient: APIClient
    let onCloseDetail: () -> Void
    let onContentChanged: () -> Void
    let onPendingChatMessageConsumed: () -> Void

    static func == (lhs: MacInboxDetailHost, rhs: MacInboxDetailHost) -> Bool {
        lhs.detail == rhs.detail
            && lhs.recordings == rhs.recordings
            && lhs.folders == rhs.folders
            && lhs.viewingFolderId == rhs.viewingFolderId
            && lhs.pendingChatMessage == rhs.pendingChatMessage
            && lhs.language == rhs.language
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
            CompanionView(
                apiClient: apiClient,
                recordings: recordings,
                initialChatId: detail.id,
                initialMessage: pendingChatMessage,
                onInitialMessageConsumed: onPendingChatMessageConsumed,
                showsConversationSwitcher: false,
                viewingFolderId: viewingFolderId,
                onTurnCompleted: { completion in
                    MacWaiTaskNotificationCenter.shared.notifyTaskFinished(
                        title: OnboardingL10n.text("Wai finished", "Wai закончил", language: language),
                        body: completion.preview ?? OnboardingL10n.text(
                            "Your Wai task is ready.", "Задача Wai готова.", language: language
                        ),
                        chatId: completion.chatId
                    )
                }
            )
            .environment(\.locale, MacDateFormatting.locale(for: language))
            .companionAccentColor(Palette.accent)
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
            HStack(alignment: .top, spacing: Spacing.sm) {
                Image(systemName: "square.and.arrow.down")
                    .font(.system(size: 18, weight: .semibold))
                    .foregroundStyle(.green)
                    .frame(width: 34, height: 34)
                    .background(Color.green.opacity(0.12))
                    .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                VStack(alignment: .leading, spacing: Spacing.xxs) {
                    Text(t("Upload a file", "Загрузить файл"))
                        .font(Typography.headingMedium)
                    Text(t(
                        "Choose a file first. Then upload it to Inbox from this panel.",
                        "Сначала выберите файл. Затем загрузите его в Инбокс из этой панели."
                    ))
                    .font(Typography.bodySmall)
                    .foregroundStyle(Palette.textSecondary)
                }
            }

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

            HStack(spacing: Spacing.sm) {
                Button(action: selectedFile == nil ? onChoose : onUpload) {
                    if phase.isWorking {
                        ProgressView()
                            .controlSize(.small)
                    } else {
                        Text(selectedFile == nil
                             ? t("Choose File...", "Выбрать файл...")
                             : t("Upload File to Inbox", "Загрузить файл в Инбокс"))
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled((selectedFile != nil && phase.isWorking) || isAdding)
                .accessibilityIdentifier("mac-inbox-upload-primary-button")

                Button(action: onChoose) {
                    Text(selectedFile == nil
                         ? t("Browse...", "Обзор...")
                         : t("Choose Another...", "Выбрать другой..."))
                }
                .buttonStyle(.bordered)
                .disabled(isAdding)

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

    private var emptyDropTarget: some View {
        HStack(spacing: Spacing.sm) {
            Image(systemName: "doc.badge.plus")
                .foregroundStyle(.green)
            Text(t("Drop a file here, or choose one below.", "Перетащите файл сюда или выберите ниже."))
                .font(Typography.bodySmall)
                .foregroundStyle(Palette.textSecondary)
            Spacer()
        }
        .padding(Spacing.md)
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

            HStack(spacing: Spacing.sm) {
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
    let language: LanguageManager.SupportedLanguage
    let selectedRowID: String?
    let canLoadMore: Bool
    let isLoadingMore: Bool
    let onSelect: (InboxRow) -> Void
    let onLoadMore: () -> Void

    /// Memoizes the O(N) localize + date-format row mapping across
    /// re-renders, and maps only the appended tail on pagination — the same
    /// motivation as the old coordinator cache, minus the full re-map per page.
    @State private var displayCache = MacInboxDisplayRowCache()

    /// Trigger pagination when one of the last few rows appears —
    /// matches the old 256px-before-bottom threshold (4 × 64pt rows).
    private static let loadMoreLookahead = 4

    var body: some View {
        let displayRows = displayCache.displayRows(for: rows, language: language)
        List {
            ForEach(Array(displayRows.enumerated()), id: \.element.id) { index, display in
                draggableRow(display, index: index)
                    .listRowInsets(EdgeInsets())
                    .listRowSeparator(.hidden)
                    .listRowBackground(
                        display.id == selectedRowID
                            ? Palette.accent.opacity(0.16)
                            : Color.clear
                    )
                    .onAppear {
                        if index >= displayRows.count - Self.loadMoreLookahead,
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

    @ViewBuilder
    private func draggableRow(_ display: MacInboxDisplayRow, index: Int) -> some View {
        let row = MacInboxListRow(
            display: display,
            onSelect: { onSelect(rows[index]) }
        )
        if display.sourceKind == .recording {
            // Only recordings live in folders, so only they drag to the sidebar.
            row.draggable(RecordingDragItem(recordingId: display.detail.id))
        } else {
            row
        }
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
                        Text(status)
                            .font(.system(size: 11, weight: .medium))
                            .foregroundStyle(statusColor)
                            .lineLimit(1)
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

    private var iconColor: Color {
        switch display.sourceKind {
        case .recording:
            return Palette.accent
        case .item:
            return .green
        case .chat:
            return .orange
        }
    }

    private var statusColor: Color {
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
    private var lastRows: [InboxRow] = []
    private var lastLanguage: LanguageManager.SupportedLanguage?
    private var cached: [MacInboxDisplayRow] = []

    func displayRows(
        for rows: [InboxRow],
        language: LanguageManager.SupportedLanguage
    ) -> [MacInboxDisplayRow] {
        if rows == lastRows, language == lastLanguage {
            return cached
        }
        if language == lastLanguage,
           rows.count > lastRows.count,
           Array(rows.prefix(lastRows.count)) == lastRows {
            // Pagination append: map only the new tail.
            cached.append(contentsOf: rows[lastRows.count...].map {
                MacInboxDisplayRow(row: $0, language: language)
            })
        } else {
            cached = rows.map { MacInboxDisplayRow(row: $0, language: language) }
        }
        lastRows = rows
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
