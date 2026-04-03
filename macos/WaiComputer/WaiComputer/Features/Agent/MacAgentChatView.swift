import SwiftUI
import WaiComputerKit

struct MacAgentChatView: View {
    let apiClient: APIClient

    @State private var messages: [AgentMessage] = []
    @State private var inputText = ""
    @State private var isLoading = false
    @State private var sessionId: String?
    @State private var error: String?

    var body: some View {
        VStack(spacing: 0) {
            if messages.isEmpty && !isLoading {
                emptyState
            } else {
                messageList
            }

            WaiDivider()

            chatInput
        }
        .alert("Agent Error", isPresented: Binding(
            get: { error != nil },
            set: { if !$0 { error = nil } }
        )) {
            Button("OK") { error = nil }
        } message: {
            Text(error ?? "Something went wrong.")
        }
    }

    // MARK: - Empty State

    private var emptyState: some View {
        VStack(spacing: Spacing.xl) {
            Spacer()

            Image(systemName: "brain")
                .font(.system(size: Spacing.xxxl))
                .foregroundStyle(Palette.textTertiary)

            Text("What can I help you with?")
                .font(Typography.displaySmall)
                .foregroundStyle(Palette.textSecondary)

            HStack(spacing: Spacing.md) {
                suggestionChip("Find what Alex said")
                suggestionChip("Create a habit tracker")
                suggestionChip("Build a landing page")
            }

            Spacer()
        }
    }

    private func suggestionChip(_ text: String) -> some View {
        Button {
            inputText = text
            sendMessage()
        } label: {
            Text(text)
                .font(Typography.bodySmall)
                .foregroundStyle(Palette.accent)
                .padding(.horizontal, Spacing.md)
                .padding(.vertical, Spacing.sm)
                .background(Palette.accentSubtle)
                .clipShape(RoundedRectangle(cornerRadius: 8))
        }
        .buttonStyle(.plain)
    }

    // MARK: - Message List

    private var messageList: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: Spacing.xl) {
                    ForEach(messages) { message in
                        AgentMessageRow(message: message)
                            .id(message.id)
                    }

                    if isLoading {
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
            .onChange(of: messages.count) { _, _ in
                if let lastId = messages.last?.id {
                    withAnimation {
                        proxy.scrollTo(lastId, anchor: .bottom)
                    }
                }
            }
        }
    }

    // MARK: - Input

    private var chatInput: some View {
        HStack(alignment: .bottom, spacing: Spacing.md) {
            TextField("Ask Wai anything...", text: $inputText, axis: .vertical)
                .textFieldStyle(.plain)
                .font(Typography.bodyLarge)
                .lineLimit(1...5)
                .onSubmit {
                    sendMessage()
                }
                .padding(Spacing.md)
                .background(Palette.surfaceSubtle)
                .clipShape(RoundedRectangle(cornerRadius: 8))
                .accessibilityIdentifier("agent-chat-input")

            Button {
                sendMessage()
            } label: {
                Image(systemName: "arrow.up")
                    .font(Typography.headingSmall)
                    .foregroundStyle(.white)
                    .frame(width: 28, height: 28)
                    .background(
                        inputText.trimmingCharacters(in: .whitespaces).isEmpty
                            ? Palette.textTertiary
                            : Palette.accent
                    )
                    .clipShape(Circle())
            }
            .buttonStyle(.plain)
            .disabled(inputText.trimmingCharacters(in: .whitespaces).isEmpty || isLoading)
            .accessibilityIdentifier("agent-chat-send")
        }
        .padding(Spacing.lg)
    }

    // MARK: - Actions

    private func sendMessage() {
        let text = inputText.trimmingCharacters(in: .whitespaces)
        guard !text.isEmpty else { return }

        let userMessage = AgentMessage(
            id: UUID().uuidString,
            role: .user,
            content: text,
            intent: nil
        )
        messages.append(userMessage)
        inputText = ""
        isLoading = true

        Task {
            do {
                let response = try await apiClient.sendAgentMessage(text, sessionId: sessionId)
                sessionId = response.sessionId

                let assistantMessage = AgentMessage(
                    id: UUID().uuidString,
                    role: .assistant,
                    content: response.response,
                    intent: response.intent
                )
                messages.append(assistantMessage)
            } catch {
                self.error = error.userFacingMessage(context: .generic)
            }
            isLoading = false
        }
    }
}

// MARK: - Agent Message Model

struct AgentMessage: Identifiable {
    let id: String
    let role: Role
    let content: String
    let intent: String?

    enum Role {
        case user
        case assistant
    }
}

// MARK: - Agent Message Row

private struct AgentMessageRow: View {
    let message: AgentMessage

    var isUser: Bool { message.role == .user }

    var body: some View {
        HStack(alignment: .top, spacing: Spacing.md) {
            RoundedRectangle(cornerRadius: 1)
                .fill(isUser ? Color.clear : Palette.accent)
                .frame(width: 2)

            VStack(alignment: .leading, spacing: Spacing.xs) {
                HStack(spacing: Spacing.sm) {
                    Text(isUser ? "YOU" : "WAI")
                        .font(Typography.labelSmall)
                        .foregroundStyle(Palette.textTertiary)
                        .tracking(1.2)

                    if let intent = message.intent, !isUser {
                        Text(intent.uppercased())
                            .font(Typography.caption)
                            .foregroundStyle(.white)
                            .padding(.horizontal, Spacing.sm)
                            .padding(.vertical, Spacing.xxs)
                            .background(intentColor(intent))
                            .clipShape(RoundedRectangle(cornerRadius: 4))
                    }
                }

                Text(message.content)
                    .font(Typography.reading)
                    .lineSpacing(6)
                    .textSelection(.enabled)
            }
        }
    }

    private func intentColor(_ intent: String) -> Color {
        switch intent.lowercased() {
        case "search":
            return Palette.typeMeeting
        case "build":
            return Palette.typeReflection
        case "chat":
            return Palette.typeNote
        default:
            return Palette.textTertiary
        }
    }
}
