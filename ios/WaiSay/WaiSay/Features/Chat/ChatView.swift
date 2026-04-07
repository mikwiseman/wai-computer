import SwiftUI
import WaiSayKit

struct ChatView: View {
    @EnvironmentObject var appState: AppState
    @StateObject private var viewModel = ChatViewModel()

    var body: some View {
        NavigationStack {
            Group {
                if viewModel.selectedSession != nil {
                    conversationView
                } else {
                    sessionListView
                }
            }
            .navigationTitle(viewModel.selectedSession != nil
                ? (viewModel.selectedSession?.title ?? "Chat")
                : "Chat")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                if viewModel.selectedSession != nil {
                    ToolbarItem(placement: .topBarLeading) {
                        Button {
                            viewModel.backToSessions()
                        } label: {
                            HStack(spacing: 4) {
                                Image(systemName: "chevron.left")
                                Text("Sessions")
                            }
                        }
                    }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        viewModel.startNewChat()
                    } label: {
                        Image(systemName: "square.and.pencil")
                    }
                }
            }
            .task {
                await viewModel.loadSessions(apiClient: appState.getAPIClient())
            }
        }
    }

    // MARK: - Session List

    private var sessionListView: some View {
        Group {
            if viewModel.isLoadingSessions && viewModel.sessions.isEmpty {
                ProgressView("Loading chats...")
            } else if viewModel.sessions.isEmpty {
                ContentUnavailableView(
                    "No Chats",
                    systemImage: "bubble.left.and.bubble.right",
                    description: Text("Start a conversation to ask questions about your recordings.")
                )
            } else {
                List {
                    if !viewModel.pinnedSessions.isEmpty {
                        Section("Pinned") {
                            ForEach(viewModel.pinnedSessions) { session in
                                sessionRow(session)
                            }
                        }
                    }

                    Section(viewModel.pinnedSessions.isEmpty ? "" : "Recent") {
                        ForEach(viewModel.unpinnedSessions) { session in
                            sessionRow(session)
                        }
                    }
                }
                .refreshable {
                    await viewModel.loadSessions(apiClient: appState.getAPIClient())
                }
            }
        }
    }

    private func sessionRow(_ session: ChatSessionListItem) -> some View {
        Button {
            Task {
                await viewModel.openSession(session, apiClient: appState.getAPIClient())
            }
        } label: {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    HStack(spacing: 6) {
                        if session.pinnedAt != nil {
                            Image(systemName: "pin.fill")
                                .font(.caption2)
                                .foregroundStyle(.orange)
                        }
                        Text(session.title ?? "New Chat")
                            .font(.headline)
                            .lineLimit(1)
                    }

                    Text("\(session.messageCount) message\(session.messageCount == 1 ? "" : "s")")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Image(systemName: "chevron.right")
                    .font(.caption)
                    .foregroundStyle(.tertiary)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .swipeActions(edge: .trailing, allowsFullSwipe: true) {
            Button(role: .destructive) {
                Task {
                    await viewModel.deleteSession(id: session.id, apiClient: appState.getAPIClient())
                }
            } label: {
                Label("Delete", systemImage: "trash")
            }
        }
        .swipeActions(edge: .leading) {
            Button {
                Task {
                    await viewModel.togglePin(session: session, apiClient: appState.getAPIClient())
                }
            } label: {
                Label(
                    session.pinnedAt != nil ? "Unpin" : "Pin",
                    systemImage: session.pinnedAt != nil ? "pin.slash" : "pin"
                )
            }
            .tint(.orange)
        }
    }

    // MARK: - Conversation

    private var conversationView: some View {
        VStack(spacing: 0) {
            if viewModel.messages.isEmpty && !viewModel.isLoading {
                Spacer()
                VStack(spacing: 12) {
                    Image(systemName: "bubble.left.and.bubble.right")
                        .font(.system(size: 48))
                        .foregroundStyle(.tertiary)
                    Text("Ask anything about your recordings")
                        .font(.body)
                        .foregroundStyle(.secondary)
                }
                Spacer()
            } else {
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 16) {
                            ForEach(viewModel.messages) { message in
                                ChatMessageRow(
                                    message: message,
                                    sources: viewModel.sourcesForMessage(message)
                                )
                                .id(message.id)
                            }

                            if viewModel.isLoading {
                                HStack(spacing: 8) {
                                    ProgressView()
                                        .controlSize(.small)
                                    Text("Thinking...")
                                        .font(.footnote)
                                        .foregroundStyle(.secondary)
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

            if let error = viewModel.error {
                Text(error)
                    .font(.caption)
                    .foregroundStyle(.red)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal)
                    .padding(.top, 8)
            }

            Divider()
            chatInput
        }
    }

    private var chatInput: some View {
        HStack(alignment: .bottom, spacing: 12) {
            TextField("Ask about your recordings...", text: $viewModel.inputText, axis: .vertical)
                .textFieldStyle(.roundedBorder)
                .lineLimit(1...4)

            Button(action: sendMessage) {
                Image(systemName: "arrow.up.circle.fill")
                    .font(.system(size: 28))
                    .foregroundStyle(
                        viewModel.inputText.trimmingCharacters(in: .whitespaces).isEmpty || viewModel.isLoading
                            ? Color.secondary
                            : Color.blue
                    )
            }
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

// MARK: - Chat Message Row

private struct ChatMessageRow: View {
    let message: ChatMessageResponse
    let sources: [ChatSource]
    @State private var showSources = false

    private var isUser: Bool { message.role == "user" }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            // Role label
            Text(isUser ? "YOU" : "WAI")
                .font(.caption2.weight(.semibold))
                .foregroundStyle(.secondary)
                .tracking(1.2)

            // Message content
            Text(message.content)
                .font(.body)
                .textSelection(.enabled)

            // Sources
            if !isUser && !sources.isEmpty {
                Button {
                    withAnimation { showSources.toggle() }
                } label: {
                    HStack(spacing: 4) {
                        Text("\(sources.count) source\(sources.count == 1 ? "" : "s")")
                            .font(.caption)
                        Image(systemName: showSources ? "chevron.up" : "chevron.down")
                            .font(.caption2)
                    }
                    .foregroundStyle(.blue)
                }
                .buttonStyle(.plain)

                if showSources {
                    VStack(alignment: .leading, spacing: 10) {
                        ForEach(sources) { source in
                            VStack(alignment: .leading, spacing: 2) {
                                HStack(spacing: 4) {
                                    if let title = source.recordingTitle {
                                        Text(title)
                                            .font(.caption.weight(.medium))
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
                        }
                    }
                    .padding(10)
                    .background(Color(.secondarySystemBackground))
                    .clipShape(RoundedRectangle(cornerRadius: 8))
                }
            }
        }
        .padding(.leading, isUser ? 0 : 8)
        .overlay(alignment: .leading) {
            if !isUser {
                RoundedRectangle(cornerRadius: 1)
                    .fill(Color.blue)
                    .frame(width: 2)
            }
        }
    }
}

// MARK: - ViewModel

@MainActor
class ChatViewModel: ObservableObject {
    @Published var sessions: [ChatSessionListItem] = []
    @Published var selectedSession: ChatSessionListItem?
    @Published var messages: [ChatMessageResponse] = []
    @Published var inputText = ""
    @Published var isLoading = false
    @Published var isLoadingSessions = false
    @Published var error: String?

    private var currentSessionId: String?
    private var messageSourcesMap: [String: [ChatSource]] = [:]

    var pinnedSessions: [ChatSessionListItem] {
        sessions.filter { $0.pinnedAt != nil }
    }

    var unpinnedSessions: [ChatSessionListItem] {
        sessions.filter { $0.pinnedAt == nil }
    }

    func sourcesForMessage(_ message: ChatMessageResponse) -> [ChatSource] {
        messageSourcesMap[message.id] ?? []
    }

    func loadSessions(apiClient: APIClient) async {
        isLoadingSessions = true
        do {
            sessions = try await apiClient.listChatSessions()
        } catch {
            self.error = error.userFacingMessage(context: .generic)
        }
        isLoadingSessions = false
    }

    func openSession(_ session: ChatSessionListItem, apiClient: APIClient) async {
        selectedSession = session
        currentSessionId = session.id
        messages = []
        messageSourcesMap = [:]
        isLoading = true

        do {
            let detail = try await apiClient.getChatSession(id: session.id)
            messages = detail.messages
        } catch {
            self.error = error.userFacingMessage(context: .generic)
        }

        isLoading = false
    }

    func startNewChat() {
        selectedSession = nil
        currentSessionId = nil
        messages = []
        messageSourcesMap = [:]
        inputText = ""
        error = nil
    }

    func backToSessions() {
        selectedSession = nil
        currentSessionId = nil
        messages = []
        messageSourcesMap = [:]
        inputText = ""
        error = nil
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
        error = nil

        do {
            let response = try await apiClient.sendChatMessage(
                question: text,
                sessionId: currentSessionId
            )

            currentSessionId = response.sessionId

            let detail = try await apiClient.getChatSession(id: response.sessionId)
            messages = detail.messages

            messageSourcesMap[response.messageId] = response.sources

            // Refresh sessions list and update selectedSession
            sessions = try await apiClient.listChatSessions()
            selectedSession = sessions.first { $0.id == response.sessionId }
        } catch {
            self.error = error.userFacingMessage(context: .generic)
        }

        isLoading = false
    }

    func deleteSession(id: String, apiClient: APIClient) async {
        do {
            try await apiClient.deleteChatSession(id: id)
            sessions.removeAll { $0.id == id }
            if currentSessionId == id {
                startNewChat()
            }
        } catch {
            self.error = error.userFacingMessage(context: .generic)
        }
    }

    func togglePin(session: ChatSessionListItem, apiClient: APIClient) async {
        do {
            if session.pinnedAt != nil {
                let updated = try await apiClient.unpinChatSession(id: session.id)
                if let index = sessions.firstIndex(where: { $0.id == session.id }) {
                    sessions[index] = updated
                }
            } else {
                let updated = try await apiClient.pinChatSession(id: session.id)
                if let index = sessions.firstIndex(where: { $0.id == session.id }) {
                    sessions[index] = updated
                }
            }
        } catch {
            self.error = error.userFacingMessage(context: .generic)
        }
    }
}

#Preview {
    ChatView()
        .environmentObject(AppState())
}
