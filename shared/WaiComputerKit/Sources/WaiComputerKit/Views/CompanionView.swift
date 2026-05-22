import Foundation
import SwiftUI

/// Cross-platform Wai chat view used by both the macOS sidebar `.wai` section
/// and the iOS `WaiHomeView`. Takes an `APIClient` (kept in environment by the
/// host app's auth flow) and a list of recordings used to resolve citation
/// chip titles. Persists chats server-side and streams turns via SSE.
public struct CompanionView: View {
    public let apiClient: APIClient
    public let recordings: [Recording]
    @Environment(\.locale) private var locale

    @State private var chats: [CompanionConversation] = []
    @State private var activeChatId: String?
    @State private var messages: [CompanionMessage] = []
    @State private var streamingText: String = ""
    @State private var streamingCitations: [CompanionStreamCitation] = []
    @State private var streamingToolNotes: [String] = []
    @State private var stage: TurnStage = .idle
    @State private var input: String = ""
    @State private var errorMessage: String?
    @State private var showChats: Bool = false
    @State private var turnTask: Task<Void, Never>?
    private let contentMaxWidth: CGFloat = 880

    private enum TurnStage {
        case idle
        case searching
        case composing
    }

    public init(apiClient: APIClient, recordings: [Recording]) {
        self.apiClient = apiClient
        self.recordings = recordings
    }

    public var body: some View {
        VStack(spacing: 0) {
            header
            CompanionDivider()
            if showChats {
                chatList
                CompanionDivider()
            }
            messageList
            composer
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .task { await initialLoad() }
        .onDisappear { turnTask?.cancel() }
    }

    // MARK: - Sections

    private var header: some View {
        HStack(spacing: 12) {
            Text(t("Ask Wai", "Спроси Wai"))
                .font(.system(size: 18, weight: .semibold))
                .lineLimit(1)
                .layoutPriority(1)

            Spacer(minLength: 12)

            Button {
                showChats.toggle()
            } label: {
                Label(showChats ? t("Hide chats", "Скрыть чаты") : chatsCountLabel, systemImage: "bubble.left.and.bubble.right")
                    .labelStyle(.titleAndIcon)
            }
            .buttonStyle(.bordered)
            .help(showChats ? t("Hide chats", "Скрыть чаты") : t("Show chats", "Показать чаты"))
            .accessibilityIdentifier("wai-toggle-chats-button")

            Button {
                Task { await newChat() }
            } label: {
                Label(t("New chat", "Новый чат"), systemImage: "plus")
                    .labelStyle(.titleAndIcon)
            }
            .buttonStyle(.borderedProminent)
            .help(t("New chat", "Новый чат"))
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
                ForEach(chats) { chat in
                    chatRow(chat)
                }
            }
            .frame(maxWidth: contentMaxWidth, alignment: .leading)
            .padding(.horizontal, 24)
            .padding(.vertical, 8)
            .frame(maxWidth: .infinity, alignment: .center)
        }
        .frame(maxHeight: 220)
    }

    private func chatRow(_ chat: CompanionConversation) -> some View {
        let isActive = chat.id == activeChatId
        return Button {
            Task { await loadChat(chat.id) }
        } label: {
            HStack(spacing: 10) {
                Image(systemName: "bubble.left")
                    .foregroundStyle(isActive ? Color.accentColor : .secondary)
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

                Spacer()
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 9)
            .background(isActive ? Color.accentColor.opacity(0.14) : Color.clear)
            .clipShape(RoundedRectangle(cornerRadius: 8))
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("wai-chat-row")
    }

    private var messageList: some View {
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
                }
                .frame(maxWidth: contentMaxWidth, alignment: .leading)
                .padding(.horizontal, 24)
                .padding(.vertical, 16)
                .frame(maxWidth: .infinity, alignment: .center)
            }
            .onChange(of: messages.count) {
                withAnimation {
                    proxy.scrollTo(messages.last?.id ?? "streaming", anchor: .bottom)
                }
            }
            .onChange(of: streamingText) {
                proxy.scrollTo("streaming", anchor: .bottom)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var emptyState: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(t("What do you want to know?", "Что хочешь узнать?"))
                .font(.system(size: 22, weight: .semibold, design: .serif))
            Text(t("Wai answers from your recordings.", "Wai отвечает по твоим записям."))
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
        MessageRow(
            role: message.role == .user ? t("You", "Ты") : "Wai",
            text: message.plainText,
            dateText: relativeDate(message.createdAt),
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
            if stage == .searching { return t("Searching recordings...", "Ищем по записям...") }
            return streamingToolNotes.joined(separator: "\n")
        }()

        return MessageRow(
            role: "Wai",
            text: text,
            dateText: t("Now", "Сейчас"),
            isMuted: streamingText.isEmpty,
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
        let citations: [CitationDisplay]
        let formattedCitation: (CitationDisplay) -> String

        var body: some View {
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
                                .background(Color.accentColor.opacity(0.12))
                                .clipShape(Capsule())
                        }
                    }
                }
            }
            .padding(.vertical, 14)
            .overlay(alignment: .bottom) {
                Color.primary.opacity(0.08)
                    .frame(height: 1)
            }
        }
    }

    private var composer: some View {
        VStack(spacing: 0) {
            CompanionDivider()

            HStack(alignment: .bottom, spacing: 10) {
                ZStack(alignment: .topLeading) {
                    RoundedRectangle(cornerRadius: 8)
                        .fill(Color.primary.opacity(0.05))

                    if input.isEmpty {
                        Text(t("Ask Wai about your recordings...", "Спроси Wai о своих записях..."))
                            .font(.system(size: 14))
                            .foregroundStyle(.secondary)
                            .padding(.horizontal, 12)
                            .padding(.vertical, 11)
                            .allowsHitTesting(false)
                    }

                    TextEditor(text: $input)
                        .font(.system(size: 14))
                        .scrollContentBackgroundCompatHidden()
                        .padding(6)
                        .frame(minHeight: 56, maxHeight: 96)
                        .accessibilityLabel(t("Message to Wai", "Сообщение для Wai"))
                        .accessibilityIdentifier("wai-message-editor")
                }
                .overlay(
                    RoundedRectangle(cornerRadius: 8)
                        .stroke(Color.primary.opacity(0.10), lineWidth: 1)
                )

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

    // MARK: - Loading + sending

    private func initialLoad() async {
        do {
            let list = try await apiClient.listCompanionChats()
            await MainActor.run {
                self.chats = list.chats
                if let first = list.chats.first {
                    self.activeChatId = first.id
                }
            }
            if let chatId = list.chats.first?.id {
                await loadChat(chatId)
            }
        } catch {
            await MainActor.run { errorMessage = error.localizedDescription }
        }
    }

    @MainActor
    private func loadChat(_ chatId: String) async {
        activeChatId = chatId
        messages = []
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
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    @MainActor
    private func send() async {
        let trimmed = input.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        input = ""
        errorMessage = nil

        // Cancel any in-flight turn first so two streams never interleave.
        turnTask?.cancel()
        turnTask = nil

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
                let detail = try await apiClient.getCompanionChat(chatId: chatId)
                messages = detail.messages
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
    private func cancelTurn() {
        turnTask?.cancel()
        turnTask = nil
        streamingText = ""
        streamingCitations = []
        streamingToolNotes = []
        stage = .idle
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
        case .error(_, let message):
            errorMessage = message
        }
    }

    // MARK: - Derived

    private var isStreaming: Bool { stage != .idle }

    private var chatsCountLabel: String {
        if isRussian {
            return "Чаты: \(chats.count)"
        }
        return "Chats (\(chats.count))"
    }

    private var starterPrompts: [String] {
        [
            t("What did I commit to this week?", "Что я обещал сделать на этой неделе?"),
            t("Summarize my last meeting.", "Сделай сводку последней встречи."),
            t("What patterns show up in my reflections?", "Какие повторяющиеся темы есть в моих рефлексиях?"),
            t("When did I first mention pricing?", "Когда я впервые упомянул цены?"),
        ]
    }

    private func chatLabel(_ chat: CompanionConversation) -> String {
        if let title = chat.title, !title.isEmpty { return title }
        let formatter = DateFormatter()
        formatter.dateStyle = .short
        formatter.timeStyle = .short
        let when = chat.lastMessageAt ?? chat.createdAt
        return "\(t("Chat", "Чат")) · \(formatter.string(from: when))"
    }

    private func relativeDate(_ date: Date) -> String {
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
