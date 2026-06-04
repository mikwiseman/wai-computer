import AppKit
import SwiftUI
import UniformTypeIdentifiers
import WaiComputerKit

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
    @State private var selectedDetail: InboxDetailRef?
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
                        selectedDetail = row.detail
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
                    focusedCreateMode = .file
                    showingImporter = true
                } label: {
                    Label(t("Upload File", "Загрузить файл"), systemImage: "square.and.arrow.down")
                }
                Button {
                    selectedDetail = nil
                    focusedCreateMode = .paste
                } label: {
                    Label(t("Paste Link or Text", "Вставить ссылку или текст"), systemImage: "link")
                }
                Button {
                    Task {
                        if let row = await model.newChat() {
                            selectedDetail = row.detail
                        }
                    }
                } label: {
                    Label(t("Ask Wai", "Спросить Wai"), systemImage: "sparkles")
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

    private var filters: some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            Picker(t("Source", "Источник"), selection: Binding(
                get: { model.sourceKind },
                set: { next in Task { await model.setSourceKind(next) } }
            )) {
                Text(t("All", "Все")).tag(Optional<InboxSourceKind>.none)
                Text(t("Recordings", "Записи")).tag(Optional.some(InboxSourceKind.recording))
                Text(t("Materials", "Материалы")).tag(Optional.some(InboxSourceKind.item))
                Text(t("Ask Wai", "Wai")).tag(Optional.some(InboxSourceKind.chat))
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
                    onRecord: onStartRecording,
                    onUpload: { showingImporter = true },
                    onPaste: {
                        selectedDetail = nil
                        focusedCreateMode = .paste
                    },
                    onChat: {
                        Task {
                            if let row = await model.newChat() {
                                selectedDetail = row.detail
                            }
                        }
                    }
                )
            } else {
                MacInboxRowsTable(
                    rows: model.rows,
                    language: languageManager.current,
                    selectedRowID: selectedRowID,
                    accentColor: MacThemePreferences.currentAccent.nsColor,
                    onSelect: { row in
                        selectedDetail = row.detail
                    }
                )
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    @ViewBuilder
    private var detailPane: some View {
        if let selectedDetail {
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
                    showsConversationSwitcher: false
                )
                .environment(\.locale, MacDateFormatting.locale(for: languageManager.current))
                .companionAccentColor(Palette.accent)
                .id(selectedRowID)
            }
        } else {
            createPane
        }
    }

    private var createPane: some View {
        GeometryReader { proxy in
            ScrollView {
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
                                "Record, upload a file, paste a link or text, or ask Wai to work.",
                                "Запишите, загрузите файл, вставьте ссылку или текст, или попросите Wai выполнить задачу."
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
                            title: t("Ask Wai", "Спросить Wai"),
                            subtitle: t("Search, remember, plan, or act", "Искать, помнить, планировать или действовать"),
                            systemImage: "sparkles",
                            accent: .orange,
                            isActive: focusedCreateMode == .ask,
                            action: {
                                focusedCreateMode = .ask
                                Task {
                                    if let row = await model.newChat() {
                                        selectedDetail = row.detail
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
                                        selectedDetail = row.detail
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
                .frame(maxWidth: 720, alignment: .leading)
                .frame(maxWidth: .infinity, minHeight: proxy.size.height, alignment: .center)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
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
                    Label(t("Ask Wai", "Спросить Wai"), systemImage: "sparkles")
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
            return t("Ask Wai to search, remember, plan, or act.", "Попросите Wai искать, помнить, планировать или действовать.")
        case .none:
            return t(
                "Record, upload a file, paste a link, or ask Wai to work.",
                "Запишите, загрузите файл, вставьте ссылку или попросите Wai выполнить задачу."
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
            return text("Ask Wai", "Спросить Wai", language: language)
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
    let accentColor: NSColor
    let onSelect: (InboxRow) -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(onSelect: onSelect)
    }

    func makeNSView(context: Context) -> NSScrollView {
        let tableView = NSTableView()
        tableView.identifier = NSUserInterfaceItemIdentifier("mac-inbox-rows")
        tableView.setAccessibilityIdentifier("mac-inbox-rows")
        tableView.headerView = nil
        tableView.backgroundColor = .clear
        tableView.enclosingScrollView?.drawsBackground = false
        tableView.usesAlternatingRowBackgroundColors = false
        tableView.usesAutomaticRowHeights = false
        tableView.rowHeight = MacInboxTableMetrics.rowHeight
        tableView.intercellSpacing = .zero
        tableView.gridStyleMask = [.solidHorizontalGridLineMask]
        tableView.gridColor = NSColor.separatorColor.withAlphaComponent(0.45)
        tableView.allowsMultipleSelection = false
        tableView.allowsEmptySelection = true
        tableView.selectionHighlightStyle = .none
        tableView.focusRingType = .none
        tableView.dataSource = context.coordinator
        tableView.delegate = context.coordinator
        tableView.target = context.coordinator
        tableView.action = #selector(Coordinator.rowClicked(_:))

        let column = NSTableColumn(identifier: MacInboxTableMetrics.columnIdentifier)
        column.minWidth = 180
        column.resizingMask = .autoresizingMask
        tableView.addTableColumn(column)

        let scrollView = NSScrollView()
        scrollView.identifier = NSUserInterfaceItemIdentifier("mac-inbox-rows-scroll")
        scrollView.setAccessibilityIdentifier("mac-inbox-rows-scroll")
        scrollView.drawsBackground = false
        scrollView.hasVerticalScroller = true
        scrollView.autohidesScrollers = true
        scrollView.borderType = .noBorder
        scrollView.documentView = tableView

        context.coordinator.tableView = tableView
        return scrollView
    }

    func updateNSView(_ scrollView: NSScrollView, context: Context) {
        guard let tableView = scrollView.documentView as? NSTableView else { return }
        context.coordinator.onSelect = onSelect
        context.coordinator.update(
            rows: rows,
            displayRows: rows.map { MacInboxDisplayRow(row: $0, language: language) },
            selectedRowID: selectedRowID,
            accentColor: accentColor
        )
        if tableView.bounds.width > 0, let column = tableView.tableColumns.first {
            column.width = max(0, tableView.bounds.width)
        }
    }

    final class Coordinator: NSObject, NSTableViewDataSource, NSTableViewDelegate {
        var onSelect: (InboxRow) -> Void
        weak var tableView: NSTableView?
        private var rows: [InboxRow] = []
        private var displayRows: [MacInboxDisplayRow] = []
        private var selectedRowID: String?
        private var accentColor: NSColor = .controlAccentColor
        private var isApplyingSelection = false

        init(onSelect: @escaping (InboxRow) -> Void) {
            self.onSelect = onSelect
        }

        func update(
            rows: [InboxRow],
            displayRows: [MacInboxDisplayRow],
            selectedRowID: String?,
            accentColor: NSColor
        ) {
            let needsReload = self.displayRows != displayRows || !self.accentColor.isEqual(accentColor)
            self.rows = rows
            self.displayRows = displayRows
            self.selectedRowID = selectedRowID
            self.accentColor = accentColor

            if needsReload {
                tableView?.reloadData()
            }
            applySelection()
        }

        func numberOfRows(in tableView: NSTableView) -> Int {
            displayRows.count
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
            cell.configure(with: displayRows[row], accentColor: accentColor)
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
            rowView.accentColor = accentColor
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
            isApplyingSelection = true
            defer { isApplyingSelection = false }
            if let nextIndex {
                tableView.selectRowIndexes(IndexSet(integer: nextIndex), byExtendingSelection: false)
            } else {
                tableView.deselectAll(nil)
            }
        }
    }
}

private enum MacInboxTableMetrics {
    static let rowHeight: CGFloat = 64
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
