import SwiftUI
import WaiComputerKit

struct MacChatView: View {
    @EnvironmentObject var appState: MacAppState
    @StateObject private var viewModel = MacChatViewModel()

    var body: some View {
        HSplitView {
            // Session list
            sessionList
                .frame(minWidth: 200, idealWidth: 250, maxWidth: 300)

            // Conversation
            conversationView
        }
        .task {
            await viewModel.loadSessions(apiClient: appState.getAPIClient())
        }
    }

    // MARK: - Session List

    private var sessionList: some View {
        VStack(spacing: 0) {
            HStack {
                Text("Chat Sessions")
                    .font(.headline)
                Spacer()
                Button {
                    viewModel.startNewChat()
                } label: {
                    Image(systemName: "plus")
                }
                .buttonStyle(.plain)
            }
            .padding()

            Divider()

            if viewModel.sessions.isEmpty {
                ContentUnavailableView(
                    "No Chats",
                    systemImage: "bubble.left.and.bubble.right",
                    description: Text("Start a conversation to ask questions about your recordings.")
                )
            } else {
                List(viewModel.sessions, selection: $viewModel.selectedSessionId) { session in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(session.title ?? "New Chat")
                            .font(.body)
                            .lineLimit(1)
                        Text("\(session.messageCount) messages")
                            .font(.caption)
                            .foregroundStyle(.secondary)
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
                .listStyle(.inset)
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
                // Empty state for new chat
                Spacer()
                VStack(spacing: 12) {
                    Image(systemName: "bubble.left.and.bubble.right.fill")
                        .font(.system(size: 48))
                        .foregroundStyle(.secondary)
                    Text("Ask anything about your recordings")
                        .font(.title3)
                        .foregroundStyle(.secondary)
                }
                Spacer()
            } else {
                // Messages
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(spacing: 12) {
                            ForEach(viewModel.messages) { message in
                                ChatBubble(message: message, sources: viewModel.sourcesForMessage(message))
                                    .id(message.id)
                            }

                            if viewModel.isLoading {
                                HStack {
                                    ProgressView()
                                        .controlSize(.small)
                                    Text("Thinking...")
                                        .foregroundStyle(.secondary)
                                    Spacer()
                                }
                                .padding(.horizontal)
                                .id("loading")
                            }
                        }
                        .padding()
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

            Divider()

            // Input
            chatInput
        }
    }

    private var chatInput: some View {
        HStack(spacing: 10) {
            TextField("Ask about your recordings...", text: $viewModel.inputText)
                .textFieldStyle(.plain)
                .font(.body)
                .onSubmit {
                    sendMessage()
                }

            Button {
                sendMessage()
            } label: {
                Image(systemName: "arrow.up.circle.fill")
                    .font(.title2)
                    .foregroundStyle(viewModel.inputText.trimmingCharacters(in: .whitespaces).isEmpty ? .gray : .blue)
            }
            .buttonStyle(.plain)
            .disabled(viewModel.inputText.trimmingCharacters(in: .whitespaces).isEmpty || viewModel.isLoading)
        }
        .padding()
    }

    private func sendMessage() {
        let text = viewModel.inputText.trimmingCharacters(in: .whitespaces)
        guard !text.isEmpty else { return }
        Task {
            await viewModel.sendMessage(text, apiClient: appState.getAPIClient())
        }
    }
}

// MARK: - Chat Bubble

struct ChatBubble: View {
    let message: ChatMessageResponse
    let sources: [ChatSource]
    @State private var showSources = false

    var isUser: Bool { message.role == "user" }

    var body: some View {
        HStack {
            if isUser { Spacer(minLength: 60) }

            VStack(alignment: isUser ? .trailing : .leading, spacing: 6) {
                Text(message.content)
                    .font(.body)
                    .padding(12)
                    .background(isUser ? Color.blue : Color.gray.opacity(0.15))
                    .foregroundStyle(isUser ? .white : .primary)
                    .clipShape(RoundedRectangle(cornerRadius: 12))

                // Source citations
                if !isUser && !sources.isEmpty {
                    Button {
                        withAnimation { showSources.toggle() }
                    } label: {
                        HStack(spacing: 4) {
                            Image(systemName: "doc.text")
                            Text("\(sources.count) source\(sources.count == 1 ? "" : "s")")
                            Image(systemName: showSources ? "chevron.up" : "chevron.down")
                        }
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    }
                    .buttonStyle(.plain)

                    if showSources {
                        VStack(alignment: .leading, spacing: 6) {
                            ForEach(sources) { source in
                                VStack(alignment: .leading, spacing: 2) {
                                    HStack(spacing: 4) {
                                        if let title = source.recordingTitle {
                                            Text(title)
                                                .font(.caption)
                                                .fontWeight(.medium)
                                        }
                                        if let speaker = source.speaker {
                                            Text("(\(speaker))")
                                                .font(.caption2)
                                                .foregroundStyle(.secondary)
                                        }
                                    }
                                    Text(source.content)
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                        .lineLimit(2)
                                }
                                .padding(8)
                                .background(Color.gray.opacity(0.08))
                                .cornerRadius(6)
                            }
                        }
                    }
                }
            }

            if !isUser { Spacer(minLength: 60) }
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

    // Store sources keyed by message ID from the latest response
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
        // Add user message locally for immediate display
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

            // Update session ID (may be new)
            selectedSessionId = response.sessionId

            // Replace temp user message and add assistant response
            // Reload full session to get proper message IDs
            let detail = try await apiClient.getChatSession(id: response.sessionId)
            messages = detail.messages

            // Store sources for the assistant's response message
            messageSourcesMap[response.messageId] = response.sources

            // Reload sessions list
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
