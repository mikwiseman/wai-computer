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
            if showChats {
                chatList
                    .frame(maxHeight: 180)
            }
            messageList
            composer
        }
        .task { await initialLoad() }
        .onDisappear { turnTask?.cancel() }
    }

    // MARK: - Sections

    private var header: some View {
        HStack {
            Text(t("Ask Wai", "Спроси Wai"))
                .font(.title3.bold())
            Spacer()
            Button {
                showChats.toggle()
            } label: {
                Text(showChats ? t("Hide chats", "Скрыть чаты") : chatsCountLabel)
            }
            .buttonStyle(.bordered)
            Button {
                Task { await newChat() }
            } label: {
                Text(t("+ New chat", "+ Новый чат"))
            }
            .buttonStyle(.borderedProminent)
        }
        .padding(.horizontal)
        .padding(.vertical, 8)
    }

    private var chatList: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(chats) { chat in
                    chatChip(chat)
                }
            }
            .padding(.horizontal)
        }
    }

    private func chatChip(_ chat: CompanionConversation) -> some View {
        let isActive = chat.id == activeChatId
        return Button {
            Task { await loadChat(chat.id) }
        } label: {
            Text(chatLabel(chat))
                .font(.callout)
                .lineLimit(1)
                .padding(.horizontal, 10)
                .padding(.vertical, 6)
                .background(isActive ? Color.accentColor.opacity(0.2) : Color.secondary.opacity(0.1))
                .clipShape(Capsule())
        }
        .buttonStyle(.plain)
    }

    private var messageList: some View {
        ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
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
                            .padding(.horizontal)
                    }
                }
                .padding(.vertical)
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
    }

    private var emptyState: some View {
        VStack(alignment: .center, spacing: 12) {
            Text(t("What do you want to know?", "Что хочешь узнать?"))
                .font(.title2)
            Text(t("Wai answers from your recordings.", "Wai отвечает по твоим записям."))
                .foregroundStyle(.secondary)
            ForEach(starterPrompts, id: \.self) { prompt in
                Button(prompt) { input = prompt }
                    .buttonStyle(.bordered)
            }
        }
        .frame(maxWidth: .infinity)
        .padding()
    }

    private func bubble(for message: CompanionMessage) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(message.role == .user ? t("You", "Ты") : "Wai")
                .font(.caption2)
                .foregroundStyle(.secondary)
            Text(message.plainText)
                .textSelection(.enabled)
            if !message.citations.isEmpty {
                citationStrip(
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
        .padding(.horizontal)
    }

    private var streamingBubble: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("Wai")
                .font(.caption2)
                .foregroundStyle(.secondary)
            if stage == .searching && streamingText.isEmpty {
                Text(t("Searching recordings...", "Ищем по записям..."))
                    .italic()
                    .foregroundStyle(.secondary)
            }
            if !streamingToolNotes.isEmpty && streamingText.isEmpty {
                VStack(alignment: .leading, spacing: 2) {
                    ForEach(streamingToolNotes, id: \.self) { note in
                        Text(note)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
            }
            if !streamingText.isEmpty {
                Text(streamingText)
                    .textSelection(.enabled)
            }
            if !streamingCitations.isEmpty {
                citationStrip(
                    citations: streamingCitations.map {
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
        .padding(.horizontal)
    }

    private func citationStrip(citations: [CitationDisplay]) -> some View {
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

    private var composer: some View {
        HStack(alignment: .bottom, spacing: 8) {
            TextEditor(text: $input)
                .frame(minHeight: 44, maxHeight: 120)
                .padding(8)
                .background(Color.secondary.opacity(0.1))
                .clipShape(RoundedRectangle(cornerRadius: 8))
            if isStreaming {
                Button {
                    cancelTurn()
                } label: {
                    Text(t("Stop", "Стоп"))
                        .frame(minWidth: 60)
                }
                .buttonStyle(.bordered)
            } else {
                Button {
                    Task { await send() }
                } label: {
                    Text(t("Ask", "Спросить"))
                        .frame(minWidth: 60)
                }
                .buttonStyle(.borderedProminent)
                .disabled(input.trimmingCharacters(in: .whitespaces).isEmpty)
            }
        }
        .padding()
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
