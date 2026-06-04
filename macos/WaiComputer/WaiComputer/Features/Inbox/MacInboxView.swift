import SwiftUI
import UniformTypeIdentifiers
import WaiComputerKit

private enum InboxCreateMode {
    case record
    case file
    case paste
    case chat
}

struct MacInboxView: View {
    let apiClient: APIClient
    let recordings: [Recording]
    let folders: [Folder]
    let isImporting: Bool
    let initialSourceKind: InboxSourceKind?
    let folderId: String?
    let pendingDetail: InboxDetailRef?
    let onStartRecording: () -> Void
    let onImportAudio: () -> Void
    let onLibraryChanged: () async -> Void
    let onPendingDetailConsumed: () -> Void

    @EnvironmentObject private var languageManager: LanguageManager
    @StateObject private var model: MacInboxViewModel
    @State private var selectedRow: InboxRow?
    @State private var showingImporter = false
    @State private var focusedCreateMode: InboxCreateMode = .file

    init(
        apiClient: APIClient,
        recordings: [Recording],
        folders: [Folder],
        isImporting: Bool,
        initialSourceKind: InboxSourceKind? = nil,
        folderId: String? = nil,
        pendingDetail: InboxDetailRef? = nil,
        onStartRecording: @escaping () -> Void,
        onImportAudio: @escaping () -> Void,
        onLibraryChanged: @escaping () async -> Void,
        onPendingDetailConsumed: @escaping () -> Void = {}
    ) {
        self.apiClient = apiClient
        self.recordings = recordings
        self.folders = folders
        self.isImporting = isImporting
        self.initialSourceKind = initialSourceKind
        self.folderId = folderId
        self.pendingDetail = pendingDetail
        self.onStartRecording = onStartRecording
        self.onImportAudio = onImportAudio
        self.onLibraryChanged = onLibraryChanged
        self.onPendingDetailConsumed = onPendingDetailConsumed
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

    var body: some View {
        HStack(spacing: 0) {
            listPane
                .frame(minWidth: 340, idealWidth: 430, maxWidth: 520)
            Divider()
            detailPane
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .task {
            await model.configureScope(sourceKind: initialSourceKind, folderId: folderId)
            await model.load()
            consumePendingDetailIfNeeded()
        }
        .onChangeCompat(of: initialSourceKind) { _, next in
            Task {
                await model.configureScope(sourceKind: next, folderId: folderId)
            }
        }
        .onChangeCompat(of: folderId) { _, next in
            Task {
                await model.configureScope(sourceKind: initialSourceKind, folderId: next)
            }
        }
        .onChangeCompat(of: pendingDetail) { _, _ in
            consumePendingDetailIfNeeded()
        }
        .onChangeCompat(of: model.rows) { _, _ in
            consumePendingDetailIfNeeded()
        }
        .fileImporter(
            isPresented: $showingImporter,
            allowedContentTypes: importTypes,
            allowsMultipleSelection: false
        ) { result in
            if case let .success(urls) = result, let url = urls.first {
                Task {
                    if let row = await model.uploadFile(url) {
                        selectedRow = row
                    }
                    await onLibraryChanged()
                }
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
            if model.nextCursor != nil {
                Divider()
                Button {
                    Task { await model.loadMore() }
                } label: {
                    if model.isLoadingMore {
                        ProgressView().controlSize(.small)
                    } else {
                        Text(t("Load More", "Показать ещё"))
                    }
                }
                .buttonStyle(.plain)
                .padding(Spacing.md)
                .disabled(model.isLoadingMore)
            }
        }
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
                    selectedRow = nil
                    focusedCreateMode = .record
                    onStartRecording()
                } label: {
                    Label(t("Record Now", "Записать сейчас"), systemImage: "waveform")
                }
                Button {
                    focusedCreateMode = .file
                    showingImporter = true
                } label: {
                    Label(t("Upload File", "Загрузить файл"), systemImage: "square.and.arrow.down")
                }
                Button {
                    selectedRow = nil
                    focusedCreateMode = .paste
                } label: {
                    Label(t("Paste Link or Text", "Вставить ссылку или текст"), systemImage: "link")
                }
                Button {
                    Task {
                        if let row = await model.newChat() {
                            selectedRow = row
                        }
                    }
                } label: {
                    Label(t("New Wai Chat", "Новый чат Wai"), systemImage: "bubble.left.and.bubble.right")
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
                "Recordings, materials, and Wai chats in this folder",
                "Записи, материалы и чаты Wai в этой папке"
            )
        }
        return t(
            "Recordings, materials, and Wai chats in one place",
            "Записи, материалы и чаты Wai в одном месте"
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
                Text(t("Chats", "Чаты")).tag(Optional.some(InboxSourceKind.chat))
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .accessibilityLabel(t("Source", "Источник"))

            Picker(t("Status", "Статус"), selection: Binding(
                get: { model.statusFilter },
                set: { next in Task { await model.setStatusFilter(next) } }
            )) {
                Text(t("Any Status", "Любой статус")).tag(Optional<InboxStatusFilter>.none)
                Text(t("Ready", "Готово")).tag(Optional.some(InboxStatusFilter.ready))
                Text(t("Processing", "В работе")).tag(Optional.some(InboxStatusFilter.processing))
                Text(t("Needs Attention", "Нужно внимание")).tag(Optional.some(InboxStatusFilter.needsAttention))
            }
            .pickerStyle(.menu)
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
                    statusFilter: model.statusFilter,
                    onRecord: onStartRecording,
                    onUpload: { showingImporter = true },
                    onPaste: {
                        selectedRow = nil
                        focusedCreateMode = .paste
                    },
                    onChat: {
                        Task {
                            if let row = await model.newChat() {
                                selectedRow = row
                            }
                        }
                    }
                )
            } else {
                ScrollView {
                    LazyVStack(spacing: 0) {
                        ForEach(model.rows) { row in
                            Button {
                                selectedRow = row
                            } label: {
                                MacInboxRowView(
                                    row: row,
                                    isActive: selectedRow?.id == row.id
                                )
                            }
                            .buttonStyle(.plain)
                            Divider()
                        }
                    }
                }
            }
        }
    }

    @ViewBuilder
    private var detailPane: some View {
        if let selectedRow {
            switch selectedRow.sourceKind {
            case .recording:
                MacRecordingDetailView(
                    recordingId: selectedRow.sourceId,
                    initialDetail: nil,
                    mode: .active,
                    folders: folders,
                    pendingTitleEditId: .constant(nil),
                    onDelete: {
                        self.selectedRow = nil
                        Task {
                            await model.load()
                            await onLibraryChanged()
                        }
                    },
                    onRestore: {
                        self.selectedRow = nil
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
                .id(selectedRow.id)
            case .item:
                MacInboxItemDetail(
                    apiClient: apiClient,
                    itemId: selectedRow.sourceId,
                    onDeleted: {
                        self.selectedRow = nil
                        Task {
                            await model.load()
                            await onLibraryChanged()
                        }
                    },
                    onUpdated: {
                        Task {
                            await model.load()
                        }
                    }
                )
                    .id(selectedRow.id)
            case .chat:
                CompanionView(
                    apiClient: apiClient,
                    recordings: recordings,
                    initialChatId: selectedRow.sourceId
                )
                .environment(\.locale, MacDateFormatting.locale(for: languageManager.current))
                .companionAccentColor(Palette.accent)
                .id(selectedRow.id)
            }
        } else {
            createPane
        }
    }

    private var createPane: some View {
        VStack(spacing: 0) {
            Spacer(minLength: Spacing.xl)
            VStack(alignment: .leading, spacing: Spacing.lg) {
                HStack(alignment: .top, spacing: Spacing.md) {
                    Image(systemName: "tray.full")
                        .font(.system(size: 24, weight: .semibold))
                        .foregroundStyle(Palette.accent)
                        .frame(width: 42, height: 42)
                        .background(Palette.accentSubtle)
                        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                    VStack(alignment: .leading, spacing: Spacing.xxs) {
                        Text(t("Add to Inbox", "Добавить в Инбокс"))
                            .font(Typography.displaySmall)
                        Text(t(
                            "Record, upload a file, paste a link or text, or start a Wai chat.",
                            "Запишите, загрузите файл, вставьте ссылку или текст, или начните чат Wai."
                        ))
                        .font(Typography.bodySmall)
                        .foregroundStyle(Palette.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
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
                        action: onStartRecording
                    )
                    MacInboxCreateAction(
                        title: t("Upload File", "Загрузить файл"),
                        subtitle: t("Audio, video, PDF, DOCX, TXT", "Аудио, видео, PDF, DOCX, TXT"),
                        systemImage: "square.and.arrow.down",
                        accent: .green,
                        isActive: focusedCreateMode == .file,
                        action: { showingImporter = true }
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
                        title: t("Wai Chat", "Чат Wai"),
                        subtitle: t("Ask about your inbox", "Спросить по Инбоксу"),
                        systemImage: "bubble.left.and.bubble.right",
                        accent: .orange,
                        isActive: focusedCreateMode == .chat,
                        action: {
                            focusedCreateMode = .chat
                            Task {
                                if let row = await model.newChat() {
                                    selectedRow = row
                                }
                            }
                        }
                    )
                }

                VStack(alignment: .leading, spacing: Spacing.sm) {
                    Text(t("Paste link or text", "Вставить ссылку или текст"))
                        .font(Typography.headingMedium)
                    TextField(
                        t("Paste a link, note, transcript, or any text...", "Вставьте ссылку, заметку, транскрипт или любой текст..."),
                        text: $model.draft,
                        axis: .vertical
                    )
                    .textFieldStyle(.roundedBorder)
                    .lineLimit(3...7)

                    HStack(spacing: Spacing.sm) {
                        Button {
                            Task {
                                if let row = await model.addDraft() {
                                    selectedRow = row
                                }
                            }
                        } label: {
                            if model.isAdding {
                                ProgressView().controlSize(.small)
                            } else {
                                Text(t("Add to Inbox", "Добавить в Инбокс"))
                            }
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(model.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || model.isAdding)

                        Button {
                            showingImporter = true
                        } label: {
                            Label(t("Attach File", "Прикрепить файл"), systemImage: "paperclip")
                        }
                        .buttonStyle(.bordered)
                        .disabled(model.isAdding)

                        Spacer()
                    }
                }
            }
            .padding(Spacing.xl)
            .frame(maxWidth: 720)
            Spacer(minLength: Spacing.xl)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func consumePendingDetailIfNeeded() {
        guard let pendingDetail else { return }
        if let row = model.rows.first(where: {
            $0.detail.kind == pendingDetail.kind && $0.detail.id == pendingDetail.id
        }) {
            selectedRow = row
            onPendingDetailConsumed()
            return
        }
        selectedRow = InboxRow(
            id: "\(pendingDetail.kind.rawValue):\(pendingDetail.id)",
            sourceKind: pendingDetail.kind,
            sourceId: pendingDetail.id,
            detail: pendingDetail,
            title: nil,
            sourceLabel: pendingDetail.kind.rawValue,
            sublabel: nil,
            activityAt: Date(),
            createdAt: Date(),
            updatedAt: nil,
            occurredAt: nil,
            status: .processing,
            sourceStatus: "loading",
            error: nil,
            folderId: nil,
            durationSeconds: nil,
            language: nil,
            hasSummary: nil,
            isStarred: false,
            isPinned: false,
            isArchived: false,
            isTrashed: false
        )
        onPendingDetailConsumed()
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
    let statusFilter: InboxStatusFilter?
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

                Menu {
                    Button(action: onPaste) {
                        Label(t("Paste Link or Text", "Вставить ссылку или текст"), systemImage: "link")
                    }
                    Button(action: onChat) {
                        Label(t("New Wai Chat", "Новый чат Wai"), systemImage: "bubble.left.and.bubble.right")
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
        if statusFilter == .processing { return "clock" }
        if statusFilter == .needsAttention { return "checkmark.seal" }
        switch sourceKind {
        case .recording: return "waveform"
        case .item: return "doc.text"
        case .chat: return "bubble.left.and.bubble.right"
        case .none: return "tray.full"
        }
    }

    private var title: String {
        if statusFilter == .processing {
            return t("Nothing Processing", "Ничего не обрабатывается")
        }
        if statusFilter == .needsAttention {
            return t("Nothing Needs Attention", "Ничего не требует внимания")
        }
        switch sourceKind {
        case .recording:
            return t("No Recordings Yet", "Записей пока нет")
        case .item:
            return t("No Materials Yet", "Материалов пока нет")
        case .chat:
            return t("No Wai Chats Yet", "Чатов Wai пока нет")
        case .none:
            return t("Inbox Is Empty", "Инбокс пуст")
        }
    }

    private var message: String {
        switch sourceKind {
        case .recording:
            return t("Record now or import audio/video.", "Запишите сейчас или импортируйте аудио/видео.")
        case .item:
            return t("Upload a file or paste a link/text.", "Загрузите файл или вставьте ссылку/текст.")
        case .chat:
            return t("Start a Wai chat from + Add.", "Начните чат Wai через +.")
        case .none:
            return t(
                "Record, upload a file, paste a link, or start a Wai chat.",
                "Запишите, загрузите файл, вставьте ссылку или начните чат Wai."
            )
        }
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

private struct MacInboxRowView: View {
    let row: InboxRow
    let isActive: Bool
    @EnvironmentObject private var languageManager: LanguageManager

    var body: some View {
        HStack(alignment: .top, spacing: Spacing.sm) {
            Image(systemName: icon)
                .foregroundStyle(color)
                .frame(width: 22)

            VStack(alignment: .leading, spacing: Spacing.xxs) {
                HStack(alignment: .firstTextBaseline, spacing: Spacing.sm) {
                    Text(title)
                        .font(Typography.headingMedium)
                        .lineLimit(1)
                    Spacer(minLength: 0)
                    if let statusLabel {
                        Text(statusLabel)
                            .font(Typography.labelSmall)
                            .foregroundStyle(statusColor)
                    }
                }

                HStack(spacing: Spacing.xs) {
                    Text(sourceLabel)
                    if let sublabel = row.sublabel {
                        Text("/")
                        Text(sublabel)
                    }
                    Text("/")
                    Text(MacDateFormatting.string(
                        from: row.activityAt,
                        dateStyle: .medium,
                        timeStyle: .short,
                        language: languageManager.current
                    ))
                    if let duration = row.durationSeconds {
                        Text("/")
                        Text(formatDuration(duration))
                    }
                }
                .font(Typography.label)
                .foregroundStyle(Palette.textSecondary)
                .lineLimit(1)
            }
        }
        .padding(.vertical, Spacing.sm)
        .padding(.horizontal, Spacing.md)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(isActive ? Palette.accentSubtle : Color.clear)
    }

    private var title: String {
        let trimmed = (row.title ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        if !trimmed.isEmpty { return trimmed }
        switch row.sourceKind {
        case .recording:
            return t("Untitled Recording", "Запись без названия")
        case .item:
            return t("Untitled Material", "Материал без названия")
        case .chat:
            return t("New Chat", "Новый чат")
        }
    }

    private var sourceLabel: String {
        switch row.sourceKind {
        case .recording:
            return t("Recording", "Запись")
        case .item:
            return t("Material", "Материал")
        case .chat:
            return t("Chat", "Чат")
        }
    }

    private var icon: String {
        switch row.sourceKind {
        case .recording: return "waveform"
        case .item: return "doc.text"
        case .chat: return "bubble.left.and.bubble.right"
        }
    }

    private var color: Color {
        switch row.sourceKind {
        case .recording: return Palette.accent
        case .item: return .green
        case .chat: return .orange
        }
    }

    private var statusLabel: String? {
        switch row.status {
        case .ready:
            return nil
        case .processing:
            return t("Processing", "В работе")
        case .needsInput:
            return t("Needs Input", "Нужен ввод")
        case .failed:
            return t("Failed", "Ошибка")
        case .archived:
            return t("Archived", "Архив")
        }
    }

    private var statusColor: Color {
        switch row.status {
        case .failed, .needsInput:
            return .red
        case .processing:
            return .orange
        case .ready, .archived:
            return Palette.textSecondary
        }
    }

    private func formatDuration(_ seconds: Int) -> String {
        let mins = seconds / 60
        let secs = seconds % 60
        return String(format: "%d:%02d", mins, secs)
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
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
        }
        .padding(.horizontal, Spacing.lg)
        .padding(.vertical, Spacing.sm)
        .background(Palette.surfaceSubtle)
    }
}
