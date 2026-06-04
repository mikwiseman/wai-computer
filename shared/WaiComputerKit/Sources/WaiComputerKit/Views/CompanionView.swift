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
}

/// Cross-platform Ask Wai thread view used by both the macOS sidebar `.wai` section
/// and the iOS `WaiHomeView`. Takes an `APIClient` (kept in environment by the
/// host app's auth flow) and a list of recordings used to resolve citation
/// chip titles. Persists chats server-side and streams turns via SSE.
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
    @Environment(\.locale) private var locale
    @Environment(\.companionAccentColor) private var companionAccentColor

    @State private var chats: [CompanionConversation] = []
    @State private var activeChatId: String?
    @State private var messages: [CompanionMessage] = []
    @State private var streamingText: String = ""
    // Whether the chat is scrolled near the bottom. While streaming we only
    // auto-scroll when this is true, so scrolling up mid-answer is not fought (107).
    @State private var isNearBottom: Bool = true
    @State private var streamingCitations: [CompanionStreamCitation] = []
    @State private var streamingToolNotes: [String] = []
    @State private var stage: TurnStage = .idle
    // Read-aloud (voice out): off by default, persisted across launches; speaks
    // the completed answer with a content-aware voice (Russian → Russian voice).
    @AppStorage("companionSpeakAnswers") private var speakAnswers = false
    @State private var readAloud = ReadAloudController(provider: AVSpeechTTSProvider())
    @State private var input: String = ""
    @FocusState private var inputFocused: Bool
    @State private var errorMessage: String?
    @State private var showChats: Bool = false
    @State private var turnTask: Task<Void, Never>?
    @State private var renamingChat: CompanionConversation?
    @State private var renameDraft: String = ""
    @State private var isRenamingChat = false
    @State private var deletingChat: CompanionConversation?
    @State private var pendingActions: [PendingActionVM] = []
    @State private var didAutoSendInitial = false
    private let contentMaxWidth: CGFloat = 880

    private enum TurnStage {
        case idle
        case searching
        case composing
    }

    /// A proposed mutating action shown as an inline approval card, plus its
    /// status once the user resolves it.
    private struct PendingActionVM: Identifiable, Equatable {
        let proposal: CompanionActionProposal
        // pending | resolving | executed | rejected | dispatched | expired | failed
        var status: String
        var id: String { proposal.actionId }
    }

    public init(
        apiClient: APIClient,
        recordings: [Recording],
        initialChatId: String? = nil,
        initialMessage: String? = nil,
        onInitialMessageConsumed: (() -> Void)? = nil,
        showsConversationSwitcher: Bool = true,
        onVoiceInput: (() -> Void)? = nil
    ) {
        self.apiClient = apiClient
        self.recordings = recordings
        self.initialChatId = initialChatId
        self.initialMessage = initialMessage
        self.onInitialMessageConsumed = onInitialMessageConsumed
        self.showsConversationSwitcher = showsConversationSwitcher
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
                pendingActionsBar
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
            pendingActionsBar
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

            Text(t("Ask Wai", "Спроси Wai"))
                .font(.system(size: 18, weight: .semibold))
                .lineLimit(1)
            .layoutPriority(1)

            Spacer(minLength: 12)

            Button {
                speakAnswers.toggle()
                if !speakAnswers { Task { await readAloud.cancel() } }
            } label: {
                Image(systemName: speakAnswers ? "speaker.wave.2.fill" : "speaker.slash")
            }
            .buttonStyle(.bordered)
            .foregroundStyle(speakAnswers ? companionAccentColor : .secondary)
            .help(
                speakAnswers
                    ? t("Read answers aloud: on", "Озвучивать ответы: вкл")
                    : t("Read answers aloud: off", "Озвучивать ответы: выкл")
            )
            .accessibilityIdentifier("wai-speak-toggle-button")

            if showsConversationSwitcher {
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

            Button {
                Task { await newChat() }
            } label: {
                Label(t("New thread", "Новый диалог"), systemImage: "plus")
                    .labelStyle(.titleAndIcon)
            }
            .buttonStyle(.borderedProminent)
            .help(t("New Wai thread", "Новый диалог Wai"))
            .accessibilityIdentifier("wai-new-chat-button")
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
                        if messages.isEmpty && streamingText.isEmpty {
                            emptyState
                        }
                        ForEach(messages) { message in
                            bubble(for: message)
                                .id(message.id)
                        }
                        if isStreaming {
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
                    withAnimation {
                        proxy.scrollTo("bottomAnchor", anchor: .bottom)
                    }
                }
                .onChangeCompat(of: streamingText) {
                    guard isNearBottom else { return }
                    proxy.scrollTo("bottomAnchor", anchor: .bottom)
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
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

    private func bubble(for message: CompanionMessage) -> some View {
        let isUser = message.role == .user
        return MessageRow(
            role: isUser ? t("You", "Ты") : "Wai",
            text: message.plainText,
            dateText: relativeDate(message.createdAt),
            isUser: isUser,
            accentColor: companionAccentColor,
            citations: message.citations.map { cit in
                CitationDisplay(
                    index: cit.citationIndex,
                    segmentId: cit.segmentId ?? "",
                    recordingId: cit.recordingId ?? "",
                    startMs: nil
                )
            },
            formattedCitation: formattedCitation
        )
    }

    private var streamingBubble: some View {
        let text: String = {
            if !streamingText.isEmpty { return streamingText }
            if stage == .searching { return t("Searching Inbox...", "Ищем по Инбоксу...") }
            return streamingToolNotes.joined(separator: "\n")
        }()

        return MessageRow(
            role: "Wai",
            text: text,
            dateText: t("Now", "Сейчас"),
            isMuted: streamingText.isEmpty,
            isUser: false,
            accentColor: companionAccentColor,
            citations: streamingCitations.map {
                CitationDisplay(
                    index: $0.index,
                    segmentId: $0.segmentId,
                    recordingId: $0.recordingId,
                    startMs: $0.startMs
                )
            },
            formattedCitation: formattedCitation
        )
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

                    Text(text)
                        .font(.system(size: 15))
                        .lineSpacing(5)
                        .foregroundStyle(isMuted ? .secondary : .primary)
                        .italicIfNeeded(isMuted)
                        .textSelection(.enabled)

                    if !citations.isEmpty {
                        FlowLayoutCompat {
                            ForEach(citations.sorted(by: { $0.index < $1.index })) { citation in
                                Text(formattedCitation(citation))
                                    .font(.caption)
                                    .padding(.horizontal, 8)
                                    .padding(.vertical, 4)
                                    .background(accentColor.opacity(0.12))
                                    .clipShape(Capsule())
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
    }

    private var composer: some View {
        VStack(spacing: 0) {
            CompanionDivider()

            HStack(alignment: .bottom, spacing: 10) {
                TextField(
                    t("Ask Wai to search, remember, plan, or act...", "Попросите Wai искать, помнить, планировать или действовать..."),
                    text: $input,
                    axis: .vertical
                )
                .textFieldStyle(.plain)
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
                        Label(t("Ask", "Спросить"), systemImage: "paperplane.fill")
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

    @ViewBuilder
    private var pendingActionsBar: some View {
        if !pendingActions.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                Text(t("Needs your approval", "Нужно ваше подтверждение"))
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(.secondary)
                ForEach(pendingActions) { item in
                    actionCard(item)
                }
            }
            .frame(maxWidth: contentMaxWidth, alignment: .leading)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 16)
            .padding(.vertical, 10)
        }
    }

    @ViewBuilder
    private func actionCard(_ item: PendingActionVM) -> some View {
        let open = item.status == "pending" || item.status == "resolving"
        VStack(alignment: .leading, spacing: 8) {
            Text(item.proposal.preview)
                .font(.system(size: 14))
                .fixedSize(horizontal: false, vertical: true)
            if open {
                HStack(spacing: 8) {
                    Button(t("Approve", "Подтвердить")) {
                        Task { await resolveAction(item.proposal.actionId, .once) }
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(companionAccentColor)
                    Button(t("Always", "Всегда")) {
                        Task { await resolveAction(item.proposal.actionId, .always) }
                    }
                    Button(t("Reject", "Отклонить"), role: .destructive) {
                        Task { await resolveAction(item.proposal.actionId, .reject) }
                    }
                }
                .disabled(item.status == "resolving")
            } else {
                Text(actionStatusLabel(item.status))
                    .font(.system(size: 12))
                    .foregroundStyle(.secondary)
            }
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.primary.opacity(0.045))
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .overlay(
            RoundedRectangle(cornerRadius: 8)
                .strokeBorder(companionAccentColor.opacity(0.35), lineWidth: 1)
        )
    }

    private func actionStatusLabel(_ status: String) -> String {
        switch status {
        case "executed": return t("Done", "Готово")
        case "rejected": return t("Rejected", "Отклонено")
        case "dispatched": return t("Sent to your Mac", "Отправлено на ваш Mac")
        case "expired": return t("Expired", "Истекло")
        case "failed": return t("Failed", "Ошибка")
        default: return status
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
            }
            if let initialChatId,
               list.chats.contains(where: { $0.id == initialChatId }) {
                await loadChat(initialChatId)
            } else if let chatId = list.chats.first?.id {
                await loadChat(chatId)
            }
            await autoSendInitialIfNeeded()
        } catch {
            await MainActor.run { errorMessage = error.localizedDescription }
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
        pendingActions = []
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
            pendingActions = []
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
        Task { await readAloud.cancel() }  // barge-in: stop reading the prior answer

        // Flip stage synchronously so the disabled button covers the gap.
        stage = .searching
        streamingText = ""
        streamingCitations = []
        streamingToolNotes = []

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

        turnTask = Task { @MainActor in
            var hadError = false
            do {
                let stream = try await apiClient.streamCompanionMessage(
                    chatId: chatId,
                    content: trimmed
                )
                for await event in stream {
                    if Task.isCancelled { break }
                    handle(event)
                    if case .done = event { break }
                }
                if Task.isCancelled {
                    return
                }
                // Speak the finished answer (detached so reading never throttles
                // the text stream); the segmenter splits it into sentences.
                if speakAnswers, !streamingText.isEmpty {
                    let answer = streamingText
                    Task { await speakAnswer(answer) }
                }
                let detail = try await apiClient.getCompanionChat(chatId: chatId)
                messages = detail.messages
                await refreshChats(selecting: chatId)
            } catch is CancellationError {
                return
            } catch let urlError as URLError where urlError.code == .cancelled {
                return
            } catch {
                hadError = true
                errorMessage = error.localizedDescription
            }
            if !hadError {
                streamingText = ""
                streamingCitations = []
                streamingToolNotes = []
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
        turnTask?.cancel()
        turnTask = nil
        Task { await readAloud.cancel() }
        streamingText = ""
        streamingCitations = []
        streamingToolNotes = []
        stage = .idle
    }

    @MainActor
    private func resolveAction(_ actionId: String, _ decision: AgentActionDecision) async {
        guard let chatId = activeChatId else { return }
        errorMessage = nil
        if let idx = pendingActions.firstIndex(where: { $0.proposal.actionId == actionId }) {
            pendingActions[idx].status = "resolving"
        }
        do {
            let response = try await apiClient.resolveCompanionAction(
                chatId: chatId,
                actionId: actionId,
                CompanionResolveActionRequest(decision: decision)
            )
            if let idx = pendingActions.firstIndex(where: { $0.proposal.actionId == actionId }) {
                pendingActions[idx].status = response.status
            }
        } catch {
            // Surface the gate's verdict (409 already-resolved, 410 expired, …) —
            // no silent fallback; leave the card actionable so the user can retry.
            errorMessage = error.localizedDescription
            if let idx = pendingActions.firstIndex(where: { $0.proposal.actionId == actionId }) {
                pendingActions[idx].status = "pending"
            }
        }
    }

    /// Read a completed answer aloud, sentence by sentence (content-aware voice).
    @MainActor
    private func speakAnswer(_ text: String) async {
        await readAloud.begin()
        await readAloud.feed(text)
        await readAloud.finish()
    }

    @MainActor
    private func handle(_ event: CompanionStreamEvent) {
        switch event {
        case .turnStart:
            break
        case .toolCall(let callId, let tool):
            streamingToolNotes.append("\(tool) (\(callId))…")
        case .toolResult(let callId, let summary):
            if let idx = streamingToolNotes.firstIndex(where: { $0.contains(callId) }) {
                streamingToolNotes[idx] = "\(streamingToolNotes[idx]) → \(summary)"
            }
        case .token(let text):
            streamingText += text
            if !streamingText.isEmpty { stage = .composing }
        case .citation(let citation):
            if !streamingCitations.contains(where: {
                $0.index == citation.index
                    && $0.segmentId == citation.segmentId
                    && $0.spanStart == citation.spanStart
            }) {
                streamingCitations.append(citation)
            }
        case .done:
            stage = .idle
        case .memoryUpdated:
            break  // a subtle "remembered" toast is a later nicety
        case .actionProposed(let proposal):
            // Surface as an inline approval card the user can act on (previously
            // flattened into a dead note, so the agent could never actually act).
            if !pendingActions.contains(where: { $0.proposal.actionId == proposal.actionId }) {
                pendingActions.append(PendingActionVM(proposal: proposal, status: "pending"))
            }
        case .actionResult(let actionId, let status, _, _):
            if let idx = pendingActions.firstIndex(where: { $0.proposal.actionId == actionId }) {
                pendingActions[idx].status = status
            }
        case .narration:
            break  // spoken via TTS on the voice surface; no-op in the chat view
        case .desktopAction:
            break  // executed by the macOS DesktopActuator (P4)
        case .error(_, let message):
            errorMessage = message
        }
    }

    // MARK: - Derived

    private var isStreaming: Bool { stage != .idle }

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
