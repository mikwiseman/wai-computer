import SwiftUI
import UniformTypeIdentifiers
import WaiComputerKit

struct MacInboxView: View {
    let apiClient: APIClient
    let recordings: [Recording]
    let folders: [Folder]
    let isImporting: Bool
    let onStartRecording: () -> Void
    let onImportAudio: () -> Void
    let onLibraryChanged: () async -> Void

    @EnvironmentObject private var languageManager: LanguageManager
    @StateObject private var model: MacInboxViewModel
    @State private var selectedRow: InboxRow?
    @State private var showingImporter = false

    init(
        apiClient: APIClient,
        recordings: [Recording],
        folders: [Folder],
        isImporting: Bool,
        onStartRecording: @escaping () -> Void,
        onImportAudio: @escaping () -> Void,
        onLibraryChanged: @escaping () async -> Void
    ) {
        self.apiClient = apiClient
        self.recordings = recordings
        self.folders = folders
        self.isImporting = isImporting
        self.onStartRecording = onStartRecording
        self.onImportAudio = onImportAudio
        self.onLibraryChanged = onLibraryChanged
        _model = StateObject(wrappedValue: MacInboxViewModel(apiClient: apiClient))
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
                .frame(minWidth: 300, idealWidth: 360, maxWidth: 420)
            Divider()
            detailPane
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .task { await model.load() }
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
                Text(t("Inbox", "Инбокс"))
                    .font(Typography.displaySmall)
                Text(t("Recordings, materials, and chats", "Записи, материалы и чаты"))
                    .font(Typography.label)
                    .foregroundStyle(Palette.textSecondary)
            }
            Spacer()
            Button {
                selectedRow = nil
            } label: {
                Image(systemName: "plus")
            }
            .buttonStyle(.borderless)
            .help(t("Add to Inbox", "Добавить в Инбокс"))
        }
        .padding(Spacing.lg)
    }

    private var filters: some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            Picker("", selection: Binding(
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
                ContentUnavailableViewCompat(
                    t("Nothing here yet", "Пока пусто"),
                    systemImage: "tray",
                    description: Text(t(
                        "Add a recording, file, link, text, or chat.",
                        "Добавьте запись, файл, ссылку, текст или чат."
                    ))
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
                MacInboxItemDetail(apiClient: apiClient, itemId: selectedRow.sourceId)
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
        ScrollView {
            VStack(spacing: Spacing.xl) {
                NewRecordingView(
                    onStartRecording: onStartRecording,
                    onImportFile: onImportAudio,
                    isImporting: isImporting
                )
                .frame(minHeight: 360)

                VStack(alignment: .leading, spacing: Spacing.md) {
                    HStack {
                        Text(t("Add Material", "Добавить материал"))
                            .font(Typography.headingMedium)
                        Spacer()
                        Button {
                            showingImporter = true
                        } label: {
                            Label(t("Attach", "Прикрепить"), systemImage: "paperclip")
                        }
                        .disabled(model.isAdding)
                    }

                    TextField(
                        t("Paste a link or any text...", "Вставьте ссылку или текст..."),
                        text: $model.draft,
                        axis: .vertical
                    )
                    .textFieldStyle(.roundedBorder)
                    .lineLimit(2...5)

                    HStack {
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
                                Text(t("Add", "Добавить"))
                            }
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(model.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || model.isAdding)

                        Button {
                            Task {
                                if let row = await model.newChat() {
                                    selectedRow = row
                                }
                            }
                        } label: {
                            Label(t("New Wai Chat", "Новый чат Wai"), systemImage: "bubble.left.and.bubble.right")
                        }
                        .buttonStyle(.bordered)
                        .disabled(model.isAdding)

                        Spacer()
                    }
                }
                .padding(Spacing.xl)
                .background(Palette.surfaceSubtle)
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                .frame(maxWidth: 620)
            }
            .padding(Spacing.xl)
            .frame(maxWidth: .infinity)
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
    @EnvironmentObject private var languageManager: LanguageManager
    @State private var item: Item?
    @State private var errorMessage: String?
    @State private var isLoading = true

    var body: some View {
        Group {
            if isLoading {
                ProgressView()
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if let item {
                MacItemDetailView(item: item, onDelete: {})
            } else {
                ContentUnavailableViewCompat(
                    t("Item unavailable", "Материал недоступен"),
                    systemImage: "doc.questionmark",
                    description: Text(errorMessage ?? "")
                )
            }
        }
        .task(id: itemId) {
            await load()
        }
    }

    private func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            item = try await apiClient.getItem(id: itemId)
        } catch {
            errorMessage = error.localizedDescription
        }
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
