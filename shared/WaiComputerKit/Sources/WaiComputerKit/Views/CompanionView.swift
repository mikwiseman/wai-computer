import Foundation
import SwiftUI

private struct CompanionAccentColorKey: EnvironmentKey {
    static let defaultValue: Color = .accentColor
}

extension EnvironmentValues {
    var companionAccentColor: Color {
        get { self[CompanionAccentColorKey.self] }
        set { self[CompanionAccentColorKey.self] = newValue }
    }
}

public extension View {
    func companionAccentColor(_ color: Color) -> some View {
        environment(\.companionAccentColor, color)
    }
}

struct CompanionComposerInsets: Equatable {
    let horizontal: CGFloat
    let vertical: CGFloat

    var edgeInsets: EdgeInsets {
        EdgeInsets(
            top: vertical,
            leading: horizontal,
            bottom: vertical,
            trailing: horizontal
        )
    }
}

enum CompanionComposerMetrics {
    static let textInsets = CompanionComposerInsets(horizontal: 12, vertical: 10)
    static let placeholderInsets = textInsets
    static let minHeight: CGFloat = 48
    static let maxHeight: CGFloat = 112
}

enum CompanionChatPresentation {
    static func chatLabel(
        title: String?,
        createdAt: Date,
        lastMessageAt: Date?,
        locale: Locale
    ) -> String {
        let trimmedTitle = (title ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        if !trimmedTitle.isEmpty { return trimmedTitle }

        let formatter = DateFormatter()
        formatter.locale = locale
        formatter.dateStyle = .short
        formatter.timeStyle = .short
        let fallbackPrefix = locale.identifier.lowercased().hasPrefix("ru") ? "Диалог" : "Thread"
        return "\(fallbackPrefix) · \(formatter.string(from: lastMessageAt ?? createdAt))"
    }

    /// Compact token count for the status badge (e.g. 1234 -> "1.2k").
    static func formatTokenCount(_ count: Int) -> String {
        if count >= 1000 {
            return String(format: "%.1fk", Double(count) / 1000.0)
        }
        return "\(count)"
    }
}

/// Cross-platform Wai agent session view used by both the macOS sidebar `.wai` section
/// and the iOS `WaiHomeView`. Takes an `APIClient` (kept in environment by the
/// host app's auth flow) and a list of recordings used to resolve citation
/// chip titles. Persists chats server-side and streams turns via SSE.
public struct CompanionTurnCompletion: Equatable, Sendable {
    public let chatId: String
    public let messageId: String
    public let preview: String?

    public init(chatId: String, messageId: String, preview: String?) {
        self.chatId = chatId
        self.messageId = messageId
        self.preview = preview
    }
}

public struct CompanionView: View {
    public let apiClient: APIClient
    public let recordings: [Recording]
    /// Optional voice-input hook (macOS): starts the host's dictation, which
    /// transcribes speech into the focused composer field. nil hides the mic.
    private let onVoiceInput: (() -> Void)?
    private let initialChatId: String?
    /// Type-and-go: a first message to auto-send once the thread is active.
    private let initialMessage: String?
    private let onInitialMessageConsumed: (() -> Void)?
    private let showsConversationSwitcher: Bool
    private let viewingRecordingId: String?
    private let viewingFolderId: String?
    private let onTurnCompleted: ((CompanionTurnCompletion) -> Void)?
    /// Optional citation-chip tap hook: (recordingId, startMs). The host routes
    /// it to its recording detail surface; nil leaves chips as inert labels.
    private let onOpenCitation: ((String, Int?) -> Void)?
    @Environment(\.locale) private var locale
    @Environment(\.companionAccentColor) private var companionAccentColor

    @State private var chats: [CompanionConversation] = []
    @State private var activeChatId: String?
    @State private var messages: [CompanionMessage] = []
    /// The in-progress assistant turn, folded from the SSE event stream into
    /// structured timeline cards (thinking / tool actions / plan / text).
    @State private var liveTurn = CompanionTurnReducer()
    /// Completed rich turns kept for the session, keyed by assistant message id,
    /// so thinking/tool/plan cards persist after the turn ends (the server stores
    /// only the final text). Cleared when switching chats.
    @State private var completedTurns: [String: CompanionTurnReducer] = [:]
    /// Bumped on every streamed event so the list auto-scrolls while text grows
    /// within a single block.
    @State private var streamTick: Int = 0
    // Whether the chat is scrolled near the bottom. While streaming we only
    // auto-scroll when this is true, so scrolling up mid-answer is not fought (107).
    @State private var isNearBottom: Bool = true
    @State private var stage: TurnStage = .idle
    /// True while a chat's history is being fetched. Gates the "What should
    /// Wai do?" hero so opening an existing thread shows progress instead of
    /// flashing the new-thread empty state (the inbox remounts per chat).
    @State private var isLoadingChat = false
    @State private var input: String = ""
    @FocusState private var inputFocused: Bool
    @State private var errorMessage: String?
    @State private var showChats: Bool = false
    @State private var turnTask: Task<Void, Never>?
    @State private var renamingChat: CompanionConversation?
    @State private var renameDraft: String = ""
    @State private var isRenamingChat = false
    @State private var deletingChat: CompanionConversation?
    @State private var didAutoSendInitial = false
    private let contentMaxWidth: CGFloat = 880

    private enum TurnStage {
        case idle
        case searching
        case composing
    }

    public init(
        apiClient: APIClient,
        recordings: [Recording],
        initialChatId: String? = nil,
        initialMessage: String? = nil,
        onInitialMessageConsumed: (() -> Void)? = nil,
        showsConversationSwitcher: Bool = true,
        viewingRecordingId: String? = nil,
        viewingFolderId: String? = nil,
        onTurnCompleted: ((CompanionTurnCompletion) -> Void)? = nil,
        onOpenCitation: ((String, Int?) -> Void)? = nil,
        onVoiceInput: (() -> Void)? = nil
    ) {
        self.apiClient = apiClient
        self.recordings = recordings
        self.initialChatId = initialChatId
        self.initialMessage = initialMessage
        self.onInitialMessageConsumed = onInitialMessageConsumed
        self.showsConversationSwitcher = showsConversationSwitcher
        self.viewingRecordingId = viewingRecordingId
        self.viewingFolderId = viewingFolderId
        self.onTurnCompleted = onTurnCompleted
        self.onOpenCitation = onOpenCitation
        self.onVoiceInput = onVoiceInput
    }

    public var body: some View {
        VStack(spacing: 0) {
            header
            CompanionDivider()
            content
        }
        .background(Color.primary.opacity(0.025))
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .task { await initialLoad() }
        .onChange(of: initialChatId) { chatId in
            guard let chatId else { return }
            Task { await loadChat(chatId) }
        }
        .onDisappear { turnTask?.cancel() }
        .sheet(item: $renamingChat) { chat in
            renameSheet(for: chat)
        }
        .confirmationDialog(
            t("Delete thread?", "Удалить диалог?"),
            isPresented: Binding(
                get: { deletingChat != nil },
                set: { if !$0 { deletingChat = nil } }
            ),
            titleVisibility: .visible
        ) {
            if let deletingChat {
                Button(t("Delete", "Удалить"), role: .destructive) {
                    Task { await deleteChat(deletingChat) }
                }
            }
            Button(t("Cancel", "Отмена"), role: .cancel) {}
        } message: {
            if let deletingChat {
                Text(
                    t(
                        "This removes “\(chatLabel(deletingChat))” from Wai.",
                        "Диалог «\(chatLabel(deletingChat))» будет удален из Wai."
                    )
                )
            }
        }
    }

    // MARK: - Sections

    @ViewBuilder
    private var content: some View {
        #if os(macOS)
        HStack(spacing: 0) {
            if showsConversationSwitcher && showChats {
                chatList
                    .frame(width: 280)
                Color.primary.opacity(0.08)
                    .frame(width: 1)
            }
            VStack(spacing: 0) {
                messageList
                composer
            }
        }
        #else
        VStack(spacing: 0) {
            if showsConversationSwitcher && showChats {
                chatList
                CompanionDivider()
            }
            messageList
            composer
        }
        #endif
    }

    private var header: some View {
        HStack(spacing: 12) {
            Image(systemName: "sparkles")
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(companionAccentColor)
                .frame(width: 28, height: 28)
                .background(companionAccentColor.opacity(0.12))
                .clipShape(RoundedRectangle(cornerRadius: 7))

            Text("Wai")
                .font(.system(size: 18, weight: .semibold))
                .lineLimit(1)
            .layoutPriority(1)

            Spacer(minLength: 12)

            statusBadge

            if showsConversationSwitcher {
                Button {
                    Task { await newChat() }
                } label: {
                    Label(t("New thread", "Новый диалог"), systemImage: "square.and.pencil")
                        .labelStyle(.iconOnly)
                }
                .buttonStyle(.bordered)
                .help(t("New thread", "Новый диалог"))
                .accessibilityIdentifier("wai-new-thread-button")

                Button {
                    showChats.toggle()
                } label: {
                    Label(showChats ? t("Hide threads", "Скрыть диалоги") : t("Show threads", "Показать диалоги"), systemImage: "bubble.left.and.bubble.right")
                        .labelStyle(.titleAndIcon)
                }
                .buttonStyle(.bordered)
                .help(showChats ? t("Hide threads", "Скрыть диалоги") : t("Show threads", "Показать диалоги"))
                .accessibilityIdentifier("wai-toggle-chats-button")
            }
        }
        .frame(maxWidth: contentMaxWidth, alignment: .leading)
        .padding(.horizontal, 24)
        .padding(.vertical, 16)
        .frame(maxWidth: .infinity, alignment: .center)
    }

    private var chatList: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 0) {
                if chats.isEmpty {
                    Text(t("No threads yet", "Диалогов пока нет"))
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.horizontal, 12)
                        .padding(.vertical, 10)
                } else {
                    ForEach(chats) { chat in
                        chatRow(chat)
                    }
                }
            }
            .frame(maxWidth: contentMaxWidth, alignment: .leading)
            .padding(.horizontal, showChats ? 12 : 24)
            .padding(.vertical, 10)
            .frame(maxWidth: .infinity, alignment: .center)
        }
        #if os(macOS)
        .background(Color.primary.opacity(0.018))
        #else
        .frame(maxHeight: 220)
        #endif
    }

    private func chatRow(_ chat: CompanionConversation) -> some View {
        let isActive = chat.id == activeChatId
        return HStack(spacing: 6) {
            Button {
                Task { await loadChat(chat.id) }
            } label: {
                HStack(spacing: 10) {
                    Image(systemName: "bubble.left")
                        .foregroundStyle(isActive ? companionAccentColor : .secondary)
                        .frame(width: 18)

                    VStack(alignment: .leading, spacing: 2) {
                        Text(chatLabel(chat))
                            .font(.system(size: 14, weight: .semibold))
                            .foregroundStyle(.primary)
                            .lineLimit(1)
                        Text(relativeDate(chat.lastMessageAt ?? chat.createdAt))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }

                    Spacer(minLength: 4)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)

            Menu {
                Button(t("Rename…", "Переименовать…")) {
                    beginRename(chat)
                }
                Button(t("Delete", "Удалить"), role: .destructive) {
                    deletingChat = chat
                }
            } label: {
                Image(systemName: "ellipsis")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(.secondary)
                    .frame(width: 24, height: 24)
            }
            .menuStyle(.borderlessButton)
            .menuIndicator(.hidden)
            .fixedSize()
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
        .background(isActive ? companionAccentColor.opacity(0.14) : Color.clear)
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .contextMenu {
            Button(t("Rename…", "Переименовать…")) {
                beginRename(chat)
            }
            Button(t("Delete", "Удалить"), role: .destructive) {
                deletingChat = chat
            }
        }
        .accessibilityIdentifier("wai-chat-row")
    }

    private struct ChatBottomOffsetKey: PreferenceKey {
        static var defaultValue: CGFloat = 0
        static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) {
            value = nextValue()
        }
    }

    private var messageList: some View {
        GeometryReader { viewport in
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 0) {
                        if messages.isEmpty && liveTurn.isEmpty {
                            if isLoadingChat {
                                loadingState
                            } else {
                                emptyState
                            }
                        }
                        ForEach(messages) { message in
                            bubble(for: message)
                                .id(message.id)
                        }
                        if isStreaming || !liveTurn.isEmpty {
                            streamingBubble
                                .id("streaming")
                        }
                        if let errorMessage {
                            Text(errorMessage)
                                .foregroundStyle(.red)
                                .font(.callout)
                                .padding(.vertical, 12)
                        }
                        // Invisible bottom anchor: its position in the scroll
                        // viewport tells us whether the user is at the bottom.
                        Color.clear
                            .frame(height: 1)
                            .id("bottomAnchor")
                            .background(
                                GeometryReader { geo in
                                    Color.clear.preference(
                                        key: ChatBottomOffsetKey.self,
                                        value: geo.frame(in: .named("chatScroll")).minY
                                    )
                                }
                            )
                    }
                    .frame(maxWidth: contentMaxWidth, alignment: .leading)
                    .padding(.horizontal, 24)
                    .padding(.vertical, 16)
                    .frame(maxWidth: .infinity, alignment: .center)
                }
                .coordinateSpace(name: "chatScroll")
                .onPreferenceChange(ChatBottomOffsetKey.self) { bottomMinY in
                    // The anchor sits within the viewport (plus a small slack) only
                    // when the latest content is visible — i.e. the user is at the
                    // bottom and auto-scroll should follow the stream.
                    isNearBottom = bottomMinY <= viewport.size.height + 80
                }
                .onChangeCompat(of: messages.count) {
                    guard isNearBottom else { return }
                    withAnimation {
                        proxy.scrollTo("bottomAnchor", anchor: .bottom)
                    }
                }
                .onChangeCompat(of: streamTick) {
                    guard isNearBottom else { return }
                    proxy.scrollTo("bottomAnchor", anchor: .bottom)
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    /// Copy-free progress shown while a thread's history loads, in place of
    /// the new-thread hero.
    private var loadingState: some View {
        ProgressView()
            .controlSize(.small)
            .padding(.vertical, 24)
            .frame(maxWidth: .infinity, alignment: .leading)
            .accessibilityIdentifier("wai-chat-loading")
    }

    private var emptyState: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(t("What should Wai do?", "Что Wai должен сделать?"))
                .font(.system(size: 22, weight: .semibold, design: .serif))
            Text(t("Search, remember, plan, or act across your Inbox.", "Искать, помнить, планировать или действовать по Инбоксу."))
                .font(.callout)
                .foregroundStyle(.secondary)

            FlowLayoutCompat {
                ForEach(starterPrompts, id: \.self) { prompt in
                    Button(prompt) { input = prompt }
                        .buttonStyle(.bordered)
                        .controlSize(.small)
                }
            }
        }
        .padding(.vertical, 24)
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityIdentifier("wai-empty-state")
    }

    @ViewBuilder
    private func bubble(for message: CompanionMessage) -> some View {
        if message.role == .user {
            MessageRow(
                role: t("You", "Ты"),
                text: message.plainText,
                dateText: relativeDate(message.createdAt),
                isUser: true,
                accentColor: companionAccentColor,
                citations: [],
                formattedCitation: formattedCitation,
                onOpenCitation: onOpenCitation
            )
        } else {
            assistantTurnView(
                items: timelineItems(for: message),
                isLive: false,
                dateText: relativeDate(message.createdAt),
                citations: message.citations.map { cit in
                    CitationDisplay(
                        index: cit.citationIndex,
                        segmentId: cit.segmentId ?? "",
                        recordingId: cit.recordingId ?? "",
                        startMs: nil
                    )
                }
            )
        }
    }

    /// The rich timeline for a finished message if we kept it this session,
    /// else a single markdown block from the stored final text.
    private func timelineItems(for message: CompanionMessage) -> [CompanionTurnItem] {
        if let reducer = completedTurns[message.id] {
            return reducer.items
        }
        let storedItems = CompanionTurnReducer.storedItems(from: message.toolCalls)
        if !storedItems.isEmpty {
            let text = message.plainText.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !text.isEmpty else { return storedItems }
            return storedItems + [.text(id: "stored-text-\(message.id)", markdown: message.plainText)]
        }
        return [.text(id: message.id, markdown: message.plainText)]
    }

    @ViewBuilder
    private var streamingBubble: some View {
        if liveTurn.isEmpty {
            assistantPlaceholder
        } else {
            assistantTurnView(
                items: liveTurn.items,
                isLive: isStreaming,
                dateText: t("Now", "Сейчас"),
                citations: liveTurn.citations.map {
                    CitationDisplay(
                        index: $0.index,
                        segmentId: $0.segmentId,
                        recordingId: $0.recordingId,
                        startMs: $0.startMs
                    )
                }
            )
        }
    }

    private var assistantPlaceholder: some View {
        HStack(alignment: .top, spacing: 0) {
            VStack(alignment: .leading, spacing: 8) {
                assistantHeader(dateText: t("Now", "Сейчас"))
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text(stage == .searching ? t("Thinking…", "Думаю…") : t("Working…", "Работаю…"))
                        .font(.system(size: 14))
                        .foregroundStyle(.secondary)
                }
            }
            Spacer(minLength: 80)
        }
        .padding(.vertical, 6)
    }

    private func assistantHeader(dateText: String) -> some View {
        HStack(spacing: 8) {
            Text("Wai")
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
            Text(dateText)
                .font(.caption)
                .foregroundStyle(.secondary.opacity(0.8))
            Spacer()
        }
    }

    private func assistantTurnView(
        items: [CompanionTurnItem],
        isLive: Bool,
        dateText: String,
        citations: [CitationDisplay]
    ) -> some View {
        let resolver: ((String, CompanionActionDecision) -> Void)? = activeChatId.map { cid in
            { actionId, decision in resolveAction(chatId: cid, actionId: actionId, decision: decision) }
        }
        return HStack(alignment: .top, spacing: 0) {
            VStack(alignment: .leading, spacing: 10) {
                assistantHeader(dateText: dateText)
                CompanionTimelineView(
                    items: items,
                    isLive: isLive,
                    accent: companionAccentColor,
                    onResolve: resolver
                )
                if !citations.isEmpty {
                    FlowLayoutCompat {
                        ForEach(citations.sorted(by: { $0.index < $1.index })) { citation in
                            citationChip(citation)
                        }
                    }
                }
            }
            .frame(maxWidth: 660, alignment: .leading)
            Spacer(minLength: 40)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.vertical, 6)
    }

    /// A citation chip opens the cited recording when the host provides the
    /// hook and the citation carries a recording id (restored citations may
    /// not); otherwise it stays an inert label rather than a dead button.
    @ViewBuilder
    private func citationChip(_ citation: CitationDisplay) -> some View {
        let label = Text(formattedCitation(citation))
            .font(.caption)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(companionAccentColor.opacity(0.12))
            .clipShape(Capsule())
        if let onOpenCitation, !citation.recordingId.isEmpty {
            Button {
                onOpenCitation(citation.recordingId, citation.startMs)
            } label: {
                label.contentShape(Capsule())
            }
            .buttonStyle(.plain)
            .help(t("Open the cited recording", "Открыть цитируемую запись"))
            .accessibilityIdentifier("wai-citation-chip")
        } else {
            label
        }
    }

    @MainActor
    private func resolveAction(
        chatId: String,
        actionId: String,
        decision: CompanionActionDecision
    ) {
        setActionResolution(actionId: actionId, resolution: .executing)
        Task { @MainActor in
            do {
                let response = try await apiClient.resolveCompanionAction(
                    chatId: chatId,
                    actionId: actionId,
                    decision: decision
                )
                setActionResolution(
                    actionId: actionId,
                    resolution: .resolved(status: response.status, detail: response.recipient ?? "")
                )
            } catch {
                setActionResolution(
                    actionId: actionId,
                    resolution: .resolved(status: "failed", detail: error.localizedDescription)
                )
            }
        }
    }

    @MainActor
    private func setActionResolution(actionId: String, resolution: CompanionActionResolution) {
        if liveTurn.setActionResolution(actionId: actionId, resolution: resolution) {
            return
        }
        for key in completedTurns.keys {
            if var reducer = completedTurns[key],
                reducer.setActionResolution(actionId: actionId, resolution: resolution) {
                completedTurns[key] = reducer
                return
            }
        }
        messages = messages.map { message in
            let nextToolCalls = CompanionTurnReducer.toolCalls(
                message.toolCalls,
                settingActionResolution: actionId,
                resolution: resolution
            )
            return nextToolCalls == message.toolCalls
                ? message
                : message.replacingToolCalls(nextToolCalls)
        }
    }

    private struct MessageRow: View {
        let role: String
        let text: String
        let dateText: String
        var isMuted = false
        let isUser: Bool
        let accentColor: Color
        let citations: [CitationDisplay]
        let formattedCitation: (CitationDisplay) -> String
        var onOpenCitation: ((String, Int?) -> Void)?
        var renderMarkdown = false

        // Assistant answers often carry inline markdown (bold, code, links);
        // render it (whitespace-preserving) instead of showing raw "**…**".
        // Falls back to plain text on any parse failure — no silent corruption.
        private var displayText: AttributedString {
            if renderMarkdown, !isMuted, !text.isEmpty,
               let attributed = try? AttributedString(
                   markdown: text,
                   options: AttributedString.MarkdownParsingOptions(
                       interpretedSyntax: .inlineOnlyPreservingWhitespace
                   )
               ) {
                return attributed
            }
            return AttributedString(text)
        }

        var body: some View {
            HStack(alignment: .top, spacing: 0) {
                if isUser { Spacer(minLength: 80) }
                VStack(alignment: .leading, spacing: 8) {
                    HStack(spacing: 8) {
                        Text(role)
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(.secondary)
                        Text(dateText)
                            .font(.caption)
                            .foregroundStyle(.secondary.opacity(0.8))
                        Spacer()
                    }

                    Text(displayText)
                        .font(.system(size: 15))
                        .lineSpacing(5)
                        .foregroundStyle(isMuted ? .secondary : .primary)
                        .italicIfNeeded(isMuted)
                        .textSelection(.enabled)

                    if !citations.isEmpty {
                        FlowLayoutCompat {
                            ForEach(citations.sorted(by: { $0.index < $1.index })) { citation in
                                chip(citation)
                            }
                        }
                    }
                }
                .padding(.horizontal, 14)
                .padding(.vertical, 12)
                .background(isUser ? accentColor.opacity(0.12) : Color.primary.opacity(0.045))
                .clipShape(RoundedRectangle(cornerRadius: 12))
                .frame(maxWidth: 660, alignment: .leading)
                if !isUser { Spacer(minLength: 80) }
            }
            .frame(maxWidth: .infinity, alignment: isUser ? .trailing : .leading)
            .padding(.vertical, 6)
        }

        /// Mirrors `CompanionView.citationChip`: tappable only when the host
        /// hook exists and the citation resolves to a recording.
        @ViewBuilder
        private func chip(_ citation: CitationDisplay) -> some View {
            let label = Text(formattedCitation(citation))
                .font(.caption)
                .padding(.horizontal, 8)
                .padding(.vertical, 4)
                .background(accentColor.opacity(0.12))
                .clipShape(Capsule())
            if let onOpenCitation, !citation.recordingId.isEmpty {
                Button {
                    onOpenCitation(citation.recordingId, citation.startMs)
                } label: {
                    label.contentShape(Capsule())
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("wai-citation-chip")
            } else {
                label
            }
        }
    }

    private var composer: some View {
        VStack(spacing: 0) {
            CompanionDivider()

            HStack(alignment: .bottom, spacing: 10) {
                TextField(
                    t("Give Wai a task", "Дайте Wai задачу"),
                    text: $input,
                    axis: .vertical
                )
                .textFieldStyle(.plain)
                #if os(macOS)
                // Return sends — matching the inbox Ask composer that started
                // this thread; Option+Return still inserts a newline with the
                // vertical axis. iOS keeps the software keyboard's newline.
                .onSubmit {
                    guard !isStreaming else { return }
                    Task { await send() }
                }
                #endif
                .font(.system(size: 14))
                .lineLimit(1...4)
                .padding(CompanionComposerMetrics.textInsets.edgeInsets)
                .frame(
                    minHeight: CompanionComposerMetrics.minHeight,
                    maxHeight: CompanionComposerMetrics.maxHeight,
                    alignment: .topLeading
                )
                .background(Color.primary.opacity(0.05))
                .overlay(
                    RoundedRectangle(cornerRadius: 8)
                        .stroke(Color.primary.opacity(0.10), lineWidth: 1)
                )
                .clipShape(RoundedRectangle(cornerRadius: 8))
                .focused($inputFocused)
                // Make the whole styled box focus the field, not just the text
                // line — the field is taller than one line so the area below it
                // was a dead zone (130).
                .contentShape(Rectangle())
                .onTapGesture { inputFocused = true }
                .accessibilityLabel(t("Message to Wai", "Сообщение для Wai"))
                .accessibilityIdentifier("wai-message-editor")

                if let onVoiceInput, !isStreaming {
                    Button {
                        // Focus the composer first so the host's dictation
                        // transcribes into this field, then start it.
                        inputFocused = true
                        onVoiceInput()
                    } label: {
                        Image(systemName: "mic.fill")
                    }
                    .buttonStyle(.bordered)
                    .help(t("Dictate your message", "Продиктовать сообщение"))
                    .accessibilityIdentifier("wai-voice-input-button")
                }

                if isStreaming {
                    Button {
                        cancelTurn()
                    } label: {
                        Label(t("Stop", "Стоп"), systemImage: "stop.fill")
                            .labelStyle(.titleAndIcon)
                            .frame(minWidth: 88)
                    }
                    .buttonStyle(.bordered)
                    .accessibilityIdentifier("wai-stop-button")
                } else {
                    Button {
                        Task { await send() }
                    } label: {
                        Label(t("Send", "Отправить"), systemImage: "paperplane.fill")
                            .labelStyle(.titleAndIcon)
                            .frame(minWidth: 96)
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(input.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    .accessibilityIdentifier("wai-send-button")
                }
            }
            .frame(maxWidth: contentMaxWidth, alignment: .leading)
            .padding(.horizontal, 24)
            .padding(.vertical, 16)
            .frame(maxWidth: .infinity, alignment: .center)
        }
    }

    private func renameSheet(for chat: CompanionConversation) -> some View {
        VStack(alignment: .leading, spacing: 18) {
            Text(t("Rename thread", "Переименовать диалог"))
                .font(.headline)
            TextField(t("Thread name", "Название диалога"), text: $renameDraft)
                .textFieldStyle(.roundedBorder)
                .accessibilityIdentifier("wai-rename-chat-field")

            HStack {
                Spacer()
                Button(t("Cancel", "Отмена")) {
                    renamingChat = nil
                }
                .keyboardShortcut(.cancelAction)

                Button(t("Save", "Сохранить")) {
                    Task { await renameChat(chat) }
                }
                .buttonStyle(.borderedProminent)
                .keyboardShortcut(.defaultAction)
                .disabled(
                    isRenamingChat
                        || renameDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                )
                .accessibilityIdentifier("wai-rename-chat-save-button")
            }
        }
        .padding(22)
        .frame(minWidth: 620)
    }

    // MARK: - Loading + sending

    private func initialLoad() async {
        if !showsConversationSwitcher, let initialChatId {
            await MainActor.run { activeChatId = initialChatId }
            await loadChat(initialChatId)
            await autoSendInitialIfNeeded()
            return
        }

        // Cover the chat-list fetch too, so a switcher first mount with existing
        // threads shows progress instead of flashing the new-thread hero; the
        // per-chat fetch below re-arms the flag inside loadChat.
        await MainActor.run { isLoadingChat = true }
        do {
            let list = try await apiClient.listCompanionChats()
            await MainActor.run {
                self.chats = list.chats
                if let initialChatId,
                   list.chats.contains(where: { $0.id == initialChatId }) {
                    self.activeChatId = initialChatId
                } else if let first = list.chats.first {
                    self.activeChatId = first.id
                }
                if list.chats.isEmpty {
                    // Genuinely no threads: show the hero immediately.
                    self.isLoadingChat = false
                }
            }
            if let initialChatId,
               list.chats.contains(where: { $0.id == initialChatId }) {
                await loadChat(initialChatId)
            } else if let chatId = list.chats.first?.id {
                await loadChat(chatId)
            }
            await autoSendInitialIfNeeded()
        } catch {
            await MainActor.run {
                errorMessage = error.localizedDescription
                isLoadingChat = false
            }
        }
    }

    /// Type-and-go: send the handed-in first message once the thread is active,
    /// exactly once per mount (the inbox remounts this view per chat).
    @MainActor
    private func autoSendInitialIfNeeded() async {
        guard !didAutoSendInitial,
              let message = initialMessage?.trimmingCharacters(in: .whitespacesAndNewlines),
              !message.isEmpty,
              activeChatId != nil else { return }
        didAutoSendInitial = true
        await send(text: message)
        onInitialMessageConsumed?()
    }

    @MainActor
    private func loadChat(_ chatId: String) async {
        activeChatId = chatId
        messages = []
        completedTurns = [:]
        isLoadingChat = true
        defer { isLoadingChat = false }
        do {
            let detail = try await apiClient.getCompanionChat(chatId: chatId)
            messages = detail.messages
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    @MainActor
    private func newChat() async {
        do {
            let chat = try await apiClient.createCompanionChat()
            chats.insert(chat, at: 0)
            activeChatId = chat.id
            messages = []
            liveTurn = CompanionTurnReducer()
            completedTurns = [:]
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    @MainActor
    private func beginRename(_ chat: CompanionConversation) {
        renameDraft = chatLabel(chat)
        renamingChat = chat
    }

    @MainActor
    private func renameChat(_ chat: CompanionConversation) async {
        let trimmed = renameDraft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        isRenamingChat = true
        defer { isRenamingChat = false }

        do {
            let updated = try await apiClient.patchCompanionChat(
                chatId: chat.id,
                title: trimmed
            )
            replaceChat(updated)
            renamingChat = nil
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    @MainActor
    private func deleteChat(_ chat: CompanionConversation) async {
        do {
            if chat.id == activeChatId {
                cancelTurn()
            }
            try await apiClient.deleteCompanionChat(chatId: chat.id)
            deletingChat = nil
            chats.removeAll { $0.id == chat.id }
            if activeChatId == chat.id {
                messages = []
                activeChatId = nil
                if let nextChat = chats.first {
                    await loadChat(nextChat.id)
                }
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    @MainActor
    private func send(text: String? = nil) async {
        let trimmed = (text ?? input).trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        input = ""
        errorMessage = nil

        // Cancel any in-flight turn first so two streams never interleave.
        turnTask?.cancel()
        turnTask = nil
        // Flip stage synchronously so the disabled button covers the gap.
        stage = .searching
        liveTurn = CompanionTurnReducer()

        var chatId = activeChatId
        if chatId == nil {
            do {
                let chat = try await apiClient.createCompanionChat()
                chats.insert(chat, at: 0)
                chatId = chat.id
                activeChatId = chat.id
                messages = []
            } catch {
                errorMessage = error.localizedDescription
                stage = .idle
                return
            }
        }
        guard let chatId else { stage = .idle; return }

        let optimistic = CompanionMessage(
            id: "local-\(UUID().uuidString)",
            role: .user,
            content: .text(trimmed),
            toolCalls: nil,
            citations: [],
            model: nil,
            inputTokens: nil,
            outputTokens: nil,
            cachedTokens: nil,
            latencyMs: nil,
            createdAt: Date()
        )
        messages.append(optimistic)
        isNearBottom = true

        turnTask = Task { @MainActor in
            var hadError = false
            do {
                let stream = try await apiClient.streamCompanionMessage(
                    chatId: chatId,
                    content: trimmed,
                    viewingRecordingId: viewingRecordingId,
                    viewingFolderId: viewingFolderId
                )
                streamLoop: for await event in stream {
                    if Task.isCancelled { break }
                    handle(event)
                    switch event {
                    case .done:
                        break streamLoop
                    case .error:
                        hadError = true
                        break streamLoop
                    default:
                        break
                    }
                }
                if Task.isCancelled {
                    return
                }
                if !hadError {
                    let detail = try await apiClient.getCompanionChat(chatId: chatId)
                    messages = detail.messages
                    await refreshChats(selecting: chatId)
                    liveTurn = CompanionTurnReducer()
                }
            } catch is CancellationError {
                return
            } catch let urlError as URLError where urlError.code == .cancelled {
                return
            } catch {
                liveTurn.markInterrupted(summary: t("Failed.", "Не удалось."))
                streamTick &+= 1
                errorMessage = error.localizedDescription
            }
            stage = .idle
        }
    }

    @MainActor
    private func refreshChats(selecting chatId: String? = nil) async {
        do {
            let list = try await apiClient.listCompanionChats()
            chats = list.chats
            if let chatId {
                activeChatId = chatId
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    @MainActor
    private func replaceChat(_ chat: CompanionConversation) {
        if let index = chats.firstIndex(where: { $0.id == chat.id }) {
            chats[index] = chat
        } else {
            chats.insert(chat, at: 0)
        }
    }

    @MainActor
    private func cancelTurn() {
        guard turnTask != nil || !liveTurn.isEmpty || stage != .idle else { return }
        turnTask?.cancel()
        turnTask = nil
        liveTurn.markInterrupted(summary: t("Stopped.", "Остановлено."))
        streamTick &+= 1
        stage = .idle
    }

    @MainActor
    private func handle(_ event: CompanionStreamEvent) {
        // Fold every event into the structured timeline (thinking / tool actions
        // / plan / text / approval cards), then react to lifecycle events.
        liveTurn.ingest(event)
        streamTick &+= 1
        switch event {
        case .token:
            stage = .composing
        case .done(let messageId, _, _):
            let completedTurn = liveTurn
            if !completedTurn.isEmpty {
                completedTurns[messageId] = completedTurn
                if let chatId = activeChatId {
                    onTurnCompleted?(CompanionTurnCompletion(
                        chatId: chatId,
                        messageId: messageId,
                        preview: completedTurn.notificationPreview(maxCharacters: 140)
                    ))
                }
            }
            stage = .idle
        case .error(_, let message):
            liveTurn.markInterrupted(summary: t("Failed.", "Не удалось."))
            errorMessage = message
        default:
            break
        }
    }

    // MARK: - Derived

    private var isStreaming: Bool { stage != .idle }

    /// Model + context used in the latest completed assistant turn, for the
    /// header status badge (openclaw-style "GPT-5.5 · 1.2k").
    private var latestModelInfo: (model: String, contextTokens: Int)? {
        guard let last = messages.last(where: { $0.role == .assistant }),
            let model = last.model, !model.isEmpty
        else { return nil }
        let ctx = (last.inputTokens ?? 0) + (last.outputTokens ?? 0)
        return (model, ctx)
    }

    @ViewBuilder
    private var statusBadge: some View {
        if let info = latestModelInfo {
            HStack(spacing: 5) {
                Image(systemName: "cpu").font(.system(size: 10))
                Text(info.model).font(.system(size: 11, weight: .medium))
                if info.contextTokens > 0 {
                    Text("· \(CompanionChatPresentation.formatTokenCount(info.contextTokens))")
                        .font(.system(size: 11))
                }
            }
            .foregroundStyle(.secondary)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(Color.primary.opacity(0.05))
            .clipShape(Capsule())
            .help(t("Model · context used last turn", "Модель · контекст последнего хода"))
            .accessibilityIdentifier("wai-status-badge")
        }
    }

    private var starterPrompts: [String] {
        [
            t("Find what I promised this week.", "Найди, что я обещал на этой неделе."),
            t("Summarize my last meeting and suggest next steps.", "Сделай сводку последней встречи и предложи следующие шаги."),
            t("Remember that I prefer short weekly launch updates.", "Запомни, что я предпочитаю короткие еженедельные апдейты по запуску."),
            t("Open the source I need to continue this task.", "Открой источник, который нужен, чтобы продолжить эту задачу."),
        ]
    }

    private func chatLabel(_ chat: CompanionConversation) -> String {
        CompanionChatPresentation.chatLabel(
            title: chat.title,
            createdAt: chat.createdAt,
            lastMessageAt: chat.lastMessageAt,
            locale: locale
        )
    }

    private func relativeDate(_ date: Date) -> String {
        // A just-sent message has a ~0 (or marginally future, from clock skew)
        // delta, which RelativeDateTimeFormatter renders as the awkward
        // "через 0 сек" / "in 0 sec". Show a natural "just now" instead (106).
        if date.timeIntervalSinceNow > -1 {
            return t("just now", "только что")
        }
        let formatter = RelativeDateTimeFormatter()
        formatter.locale = locale
        formatter.unitsStyle = .short
        return formatter.localizedString(for: date, relativeTo: Date())
    }

    private func formattedCitation(_ c: CitationDisplay) -> String {
        let title = recordings.first(where: { $0.id == c.recordingId })?.title ?? t("Recording", "Запись")
        if let ms = c.startMs {
            return "[\(c.index)] \(title) · \(formatMs(ms))"
        }
        return "[\(c.index)] \(title)"
    }

    private func formatMs(_ ms: Int) -> String {
        let total = ms / 1000
        return String(format: "%d:%02d", total / 60, total % 60)
    }

    private var isRussian: Bool {
        locale.identifier.lowercased().hasPrefix("ru")
    }

    private func t(_ english: String, _ russian: String) -> String {
        isRussian ? russian : english
    }
}

private struct CitationDisplay: Identifiable {
    let index: Int
    let segmentId: String
    let recordingId: String
    let startMs: Int?
    var id: String { "\(segmentId)-\(index)" }
}

private struct CompanionDivider: View {
    var body: some View {
        Color.primary.opacity(0.08)
            .frame(height: 1)
    }
}

private extension View {
    @ViewBuilder
    func scrollContentBackgroundCompatHidden() -> some View {
        if #available(iOS 16.0, macOS 13.0, *) {
            self.scrollContentBackground(.hidden)
        } else {
            self
        }
    }

    @ViewBuilder
    func italicIfNeeded(_ active: Bool) -> some View {
        if active {
            self.italic()
        } else {
            self
        }
    }
}

/// A minimal wrapping `HStack` substitute used for citation chips. Real `FlowLayout`
/// is iOS 16+/macOS 13+ only via `Layout`, so we approximate with a wrapping
/// `HStack` that breaks every few items. For v1 chip volume (≤10) this works fine.
private struct FlowLayoutCompat<Content: View>: View {
    @ViewBuilder var content: Content

    var body: some View {
        // Use the system Layout protocol when available; fall back to a single
        // wrapping HStack-on-line approach for older runtimes.
        if #available(iOS 16.0, macOS 13.0, *) {
            FlowLayout {
                content
            }
        } else {
            HStack { content }
        }
    }
}

@available(iOS 16.0, macOS 13.0, *)
private struct FlowLayout: Layout {
    var spacing: CGFloat = 6

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let width = proposal.width ?? .infinity
        var x: CGFloat = 0
        var y: CGFloat = 0
        var rowHeight: CGFloat = 0
        for view in subviews {
            let size = view.sizeThatFits(.unspecified)
            if x + size.width > width {
                x = 0
                y += rowHeight + spacing
                rowHeight = 0
            }
            x += size.width + spacing
            rowHeight = max(rowHeight, size.height)
        }
        return CGSize(width: width.isFinite ? width : x, height: y + rowHeight)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x = bounds.minX
        var y = bounds.minY
        var rowHeight: CGFloat = 0
        for view in subviews {
            let size = view.sizeThatFits(.unspecified)
            if x + size.width > bounds.maxX {
                x = bounds.minX
                y += rowHeight + spacing
                rowHeight = 0
            }
            view.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(width: size.width, height: size.height))
            x += size.width + spacing
            rowHeight = max(rowHeight, size.height)
        }
    }
}
