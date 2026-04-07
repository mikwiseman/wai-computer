import SwiftUI
import WaiSayKit

struct MacChatView: View {
    @EnvironmentObject var appState: MacAppState
    @StateObject private var viewModel = MacQAViewModel()

    var body: some View {
        VStack(spacing: 0) {
            conversationView
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            
            WaiDivider()
            
            chatInput
        }
    }

    private var conversationView: some View {
        VStack(spacing: 0) {
            if viewModel.answer == nil && !viewModel.isLoading && viewModel.error == nil {
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
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: Spacing.xl) {
                        if let answer = viewModel.answer {
                            QAResponseRow(
                                answer: answer,
                                sources: viewModel.sources
                            )
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
                        
                        if let error = viewModel.error {
                            Text(error)
                                .font(Typography.bodySmall)
                                .foregroundStyle(.red)
                                .padding(.horizontal, Spacing.lg)
                        }
                    }
                    .padding(Spacing.lg)
                }
            }
        }
    }

    private var chatInput: some View {
        HStack(alignment: .bottom, spacing: Spacing.md) {
            TextField("Ask about your recordings...", text: $viewModel.inputText)
                .textFieldStyle(.plain)
                .font(Typography.bodyLarge)
                .onSubmit {
                    sendMessage()
                }
                .padding(Spacing.md)
                .background(Palette.surfaceSubtle)
                .clipShape(RoundedRectangle(cornerRadius: 8))
                .accessibilityIdentifier("qa-input-field")

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

struct QAResponseRow: View {
    let answer: String
    let sources: [QASource]
    @State private var showSources = false

    var body: some View {
        HStack(alignment: .top, spacing: Spacing.md) {
            RoundedRectangle(cornerRadius: 1)
                .fill(Palette.accent)
                .frame(width: 2)

            VStack(alignment: .leading, spacing: Spacing.xs) {
                Text("WAI")
                    .font(Typography.labelSmall)
                    .foregroundStyle(Palette.textTertiary)
                    .tracking(1.2)

                Text(answer)
                    .font(Typography.reading)
                    .lineSpacing(6)
                    .textSelection(.enabled)

                if !sources.isEmpty {
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
                                .padding(Spacing.xs)
                                .background(Palette.surfaceSubtle)
                                .cornerRadius(4)
                            }
                        }
                        .padding(.top, Spacing.xs)
                    }
                }
            }
        }
    }
}

@MainActor
class MacQAViewModel: ObservableObject {
    @Published var answer: String?
    @Published var sources: [QASource] = []
    @Published var inputText = ""
    @Published var isLoading = false
    @Published var error: String?

    func sendMessage(_ text: String, apiClient: APIClient) async {
        inputText = ""
        isLoading = true
        error = nil

        do {
            let response = try await apiClient.askDatabase(question: text)
            answer = response.answer
            sources = response.sources
        } catch {
            self.error = error.userFacingMessage(context: .generic)
        }

        isLoading = false
    }
}
