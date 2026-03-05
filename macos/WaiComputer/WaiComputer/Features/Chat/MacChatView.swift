import SwiftUI
import WaiComputerKit

struct MacChatView: View {
    @EnvironmentObject var appState: MacAppState
    @StateObject private var viewModel = MacChatViewModel()

    var body: some View {
        HStack(spacing: 0) {
            sessionList
                .frame(width: 220)

            Palette.border
                .frame(width: 1)

            conversationView
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .task {
            await viewModel.loadSessions(apiClient: appState.getAPIClient())
        }
    }

    // MARK: - Session List

    private var sessionList: some View {
        VStack(spacing: 0) {
            HStack {
                Text("Sessions")
                    .waiSectionHeader()
                Spacer()
                Button {
                    viewModel.startNewChat()
                } label: {
                    Image(systemName: "plus")
                        .foregroundStyle(Palette.textSecondary)
                }
                .buttonStyle(.plain)
            }
            .padding(Spacing.lg)

            WaiDivider()

            if viewModel.sessions.isEmpty {
                ContentUnavailableView(
                    "No Chats",
                    systemImage: "bubble.left.and.bubble.right",
                    description: Text("Start a conversation to ask questions about your recordings.")
                )
            } else {
                List(viewModel.sessions, selection: $viewModel.selectedSessionId) { session in
                    VStack(alignment: .leading, spacing: Spacing.xxs) {
                        Text(session.title ?? "New Chat")
                            .font(Typography.body)
                            .lineLimit(1)
                        Text("\(session.messageCount) messages")
                            .font(Typography.caption)
                            .foregroundStyle(Palette.textTertiary)
                    }
                    .tag(session.id)
                    .contextMenu {
                        Button("Delete", role: .destructive) {
                            Task {
                                await viewModel.deleteSession(id: session.id, apiClient: appState.getAPIClient())
                            }
                        }
                    }
                }
                .listStyle(.sidebar)
            }
        }
        .onChange(of: viewModel.selectedSessionId) { _, newId in
            guard let id = newId else { return }
            Task {
                await viewModel.loadSession(id: id, apiClient: appState.getAPIClient())
            }
        }
    }

    // MARK: - Conversation

    private var conversationView: some View {
        VStack(spacing: 0) {
            if viewModel.messages.isEmpty && viewModel.selectedSessionId == nil {
                Spacer()
                VStack(spacing: Spacing.md) {
                    Image(systemName: "bubble.left.and.bubble.right")
                        .font(.system(size: Spacing.xxxl))
                        .foregroundStyle(Palette.textTertiary)
                    Text("Ask anything about your recordings")
                        .font(Typography.body)
                        .foregroundStyle(Palette.textSecondary)
                }
                Spacer()
            } else {
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: Spacing.xl) {
                            ForEach(viewModel.messages) { message in
                                ChatMessageRow(
                                    message: message,
                                    sources: viewModel.sourcesForMessage(message)
                                )
                                .id(message.id)
                            }

                            if viewModel.isLoading {
                                HStack(spacing: Spacing.sm) {
                                    ProgressView()
                                        .controlSize(.small)
                                    Text("Thinking...")
                                        .font(Typography.bodySmall)
                                        .foregroundStyle(Palette.textTertiary)
                                }
                                .padding(.horizontal, Spacing.lg)
                                .id("loading")
                            }
                        }
                        .padding(Spacing.lg)
                    }
                    .onChange(of: viewModel.messages.count) { _, _ in
                        if let lastId = viewModel.messages.last?.id {
                            withAnimation {
                                proxy.scrollTo(lastId, anchor: .bottom)
                            }
                        }
                    }
                }
            }

            WaiDivider()

            chatInput
        }
    }

    private var chatInput: some View {
        HStack(alignment: .bottom, spacing: Spacing.md) {
            TextField("Ask about your recordings...", text: $viewModel.inputText, axis: .vertical)
                .textFieldStyle(.plain)
                .font(Typography.bodyLarge)
                .lineLimit(1...5)
                .onSubmit {
                    sendMessage()
                }
                .padding(Spacing.md)
                .background(Palette.surfaceSubtle)
                .clipShape(RoundedRectangle(cornerRadius: 8))

            Button {
                sendMessage()
            } label: {
                Image(systemName: "arrow.up")
                    .font(Typography.headingSmall)
                    .foregroundStyle(.white)
                    .frame(width: 28, height: 28)
                    .background(
                        viewModel.inputText.trimmingCharacters(in: .whitespaces).isEmpty
                            ? Palette.textTertiary
                            : Palette.accent
                    )
                    .clipShape(Circle())
            }
            .buttonStyle(.plain)
            .disabled(viewModel.inputText.trimmingCharacters(in: .whitespaces).isEmpty || viewModel.isLoading)
        }
        .padding(Spacing.lg)
    }

    private func sendMessage() {
        let text = viewModel.inputText.trimmingCharacters(in: .whitespaces)
        guard !text.isEmpty else { return }
        Task {
            await viewModel.sendMessage(text, apiClient: appState.getAPIClient())
        }
    }
}

// MARK: - Chat Message Row (flat thread, no bubbles)

struct ChatMessageRow: View {
    let message: ChatMessageResponse
    let sources: [ChatSource]
    @State private var showSources = false

    var isUser: Bool { message.role == "user" }

    var body: some View {
        HStack(alignment: .top, spacing: Spacing.md) {
            // Accent left bar for assistant, invisible spacer for user (consistent alignment)
            RoundedRectangle(cornerRadius: 1)
                .fill(isUser ? Color.clear : Palette.accent)
                .frame(width: 2)

            VStack(alignment: .leading, spacing: Spacing.xs) {
                // Role label
                Text(isUser ? "YOU" : "WAI")
                    .font(Typography.labelSmall)
                    .foregroundStyle(Palette.textTertiary)
                    .tracking(1.2)

                // Message content
                Text(message.content)
                    .font(Typography.reading)
                    .lineSpacing(6)
                    .textSelection(.enabled)

                // Sources
                if !isUser && !sources.isEmpty {
                    Button {
                        withAnimation { showSources.toggle() }
                    } label: {
                        HStack(spacing: Spacing.xs) {
                            Text("\(sources.count) source\(sources.count == 1 ? "" : "s")")
                                .font(Typography.label)
                            Image(systemName: showSources ? "chevron.up" : "chevron.down")
                                .font(Typography.caption)
                        }
                        .foregroundStyle(Palette.accent)
                    }
                    .buttonStyle(.plain)
                    .padding(.top, Spacing.xs)

                    if showSources {
                        VStack(alignment: .leading, spacing: Spacing.sm) {
                            ForEach(sources) { source in
                                VStack(alignment: .leading, spacing: Spacing.xxs) {
                                    HStack(spacing: Spacing.xs) {
                                        if let title = source.recordingTitle {
                                            Text(title)
                                                .font(Typography.label)
                                        }
                                        if let speaker = source.speaker {
                                            Text("(\(speaker))")
                                                .font(Typography.caption)
                                                .foregroundStyle(Palette.textTertiary)
                                        }
                                    }
                                    Text(source.content)
                                        .font(Typography.bodySmall)
                                        .foregroundStyle(Palette.textSecondary)
                                        .lineLimit(2)
                                }
                            }
                        }
                        .padding(.top, Spacing.xs)
                    }
                }
            }
        }
    }
}

// MARK: - ViewModel

@MainActor
class MacChatViewModel: ObservableObject {
    @Published var sessions: [ChatSessionListItem] = []
    @Published var selectedSessionId: String?
    @Published var messages: [ChatMessageResponse] = []
    @Published var inputText = ""
    @Published var isLoading = false
    @Published var error: String?

    private var messageSourcesMap: [String: [ChatSource]] = [:]

    func sourcesForMessage(_ message: ChatMessageResponse) -> [ChatSource] {
        messageSourcesMap[message.id] ?? []
    }

    func loadSessions(apiClient: APIClient) async {
        do {
            sessions = try await apiClient.listChatSessions()
        } catch {
            self.error = error.localizedDescription
        }
    }

    func loadSession(id: String, apiClient: APIClient) async {
        do {
            let detail = try await apiClient.getChatSession(id: id)
            messages = detail.messages
        } catch {
            self.error = error.localizedDescription
        }
    }

    func startNewChat() {
        selectedSessionId = nil
        messages = []
        messageSourcesMap = [:]
        inputText = ""
    }

    func sendMessage(_ text: String, apiClient: APIClient) async {
        let tempUserMessage = ChatMessageResponse(
            id: UUID().uuidString,
            role: "user",
            content: text,
            sourceSegmentIds: nil,
            sourceRecordingIds: nil,
            createdAt: Date()
        )
        messages.append(tempUserMessage)
        inputText = ""
        isLoading = true

        do {
            let response = try await apiClient.sendChatMessage(
                question: text,
                sessionId: selectedSessionId
            )

            selectedSessionId = response.sessionId

            let detail = try await apiClient.getChatSession(id: response.sessionId)
            messages = detail.messages

            messageSourcesMap[response.messageId] = response.sources

            sessions = try await apiClient.listChatSessions()

        } catch {
            self.error = error.localizedDescription
        }

        isLoading = false
    }

    func deleteSession(id: String, apiClient: APIClient) async {
        do {
            try await apiClient.deleteChatSession(id: id)
            sessions.removeAll { $0.id == id }
            if selectedSessionId == id {
                startNewChat()
            }
        } catch {
            self.error = error.localizedDescription
        }
    }
}
