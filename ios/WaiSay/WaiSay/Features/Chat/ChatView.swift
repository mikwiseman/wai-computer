import SwiftUI
import WaiSayKit

struct ChatView: View {
    @EnvironmentObject var appState: AppState
    @StateObject private var viewModel = QAViewModel()
    @FocusState private var isInputFocused: Bool

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                ScrollViewReader { proxy in
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: Spacing.xl) {
                            if viewModel.answer == nil && !viewModel.isLoading && viewModel.error == nil {
                                VStack(spacing: Spacing.md) {
                                    Image(systemName: "bubble.left.and.bubble.right")
                                        .font(.system(size: 48))
                                        .foregroundStyle(Palette.textTertiary)
                                    Text("Ask anything about your recordings")
                                        .font(Typography.body)
                                        .foregroundStyle(Palette.textSecondary)
                                        .multilineTextAlignment(.center)
                                }
                                .frame(maxWidth: .infinity)
                                .padding(.top, 100)
                            }

                            if let answer = viewModel.answer {
                                QAResponseRow(answer: answer, sources: viewModel.sources)
                                    .id("answer")
                            }

                            if viewModel.isLoading {
                                HStack(spacing: Spacing.sm) {
                                    ProgressView()
                                    Text("Thinking...")
                                        .font(Typography.bodySmall)
                                        .foregroundStyle(Palette.textTertiary)
                                }
                                .padding(.top, Spacing.md)
                                .id("loading")
                            }
                            
                            if let error = viewModel.error {
                                Text(error)
                                    .font(Typography.bodySmall)
                                    .foregroundStyle(.red)
                                    .padding(.top, Spacing.md)
                            }
                        }
                        .padding()
                    }
                    .onChange(of: viewModel.isLoading) { _, loading in
                        if loading {
                            withAnimation { proxy.scrollTo("loading", anchor: .bottom) }
                        }
                    }
                    .onChange(of: viewModel.answer) { _, _ in
                        withAnimation { proxy.scrollTo("answer", anchor: .bottom) }
                    }
                }
                
                Divider()
                
                chatInput
            }
            .navigationTitle("Second Brain")
            .navigationBarTitleDisplayMode(.inline)
        }
    }

    private var chatInput: some View {
        HStack(alignment: .bottom, spacing: Spacing.md) {
            TextField("Ask about your recordings...", text: $viewModel.inputText, axis: .vertical)
                .focused($isInputFocused)
                .lineLimit(1...5)
                .padding(10)
                .background(Palette.surfaceSubtle)
                .clipShape(RoundedRectangle(cornerRadius: 16))
                .accessibilityIdentifier("qa-input-field")

            Button {
                sendMessage()
            } label: {
                Image(systemName: "arrow.up")
                    .font(.system(size: 16, weight: .bold))
                    .foregroundStyle(.white)
                    .frame(width: 32, height: 32)
                    .background(
                        viewModel.inputText.trimmingCharacters(in: .whitespaces).isEmpty
                            ? Palette.textTertiary
                            : Palette.accent
                    )
                    .clipShape(Circle())
            }
            .disabled(viewModel.inputText.trimmingCharacters(in: .whitespaces).isEmpty || viewModel.isLoading)
        }
        .padding()
        .background(Palette.surface)
    }

    private func sendMessage() {
        let text = viewModel.inputText.trimmingCharacters(in: .whitespaces)
        guard !text.isEmpty else { return }
        isInputFocused = false
        Task {
            await viewModel.sendMessage(text, apiClient: appState.apiClient)
        }
    }
}

struct QAResponseRow: View {
    let answer: String
    let sources: [QASource]
    @State private var showSources = false

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.sm) {
            HStack(alignment: .center, spacing: Spacing.xs) {
                Image(systemName: "brain")
                    .foregroundStyle(Palette.accent)
                Text("WAI")
                    .font(Typography.labelSmall)
                    .foregroundStyle(Palette.textTertiary)
                    .tracking(1.2)
            }

            Text(answer)
                .font(Typography.reading)
                .lineSpacing(4)

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
                                    .lineLimit(3)
                            }
                            .padding(Spacing.sm)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(Palette.surfaceSubtle)
                            .cornerRadius(8)
                        }
                    }
                    .padding(.top, Spacing.xs)
                }
            }
        }
    }
}

@MainActor
class QAViewModel: ObservableObject {
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
