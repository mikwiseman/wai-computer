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
                        LazyVStack(alignment: .leading, spacing: 24) {
                            if viewModel.answer == nil && !viewModel.isLoading && viewModel.error == nil {
                                VStack(spacing: 16) {
                                    Image(systemName: "bubble.left.and.bubble.right")
                                        .font(.system(size: 48))
                                        .foregroundStyle(Color.gray)
                                    Text("Ask anything about your recordings")
                                        .font(.body)
                                        .foregroundStyle(Color.secondary)
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
                                HStack(spacing: 12) {
                                    ProgressView()
                                    Text("Thinking...")
                                        .font(.footnote)
                                        .foregroundStyle(Color.gray)
                                }
                                .padding(.top, 16)
                                .id("loading")
                            }
                            
                            if let error = viewModel.error {
                                Text(error)
                                    .font(.footnote)
                                    .foregroundStyle(.red)
                                    .padding(.top, 16)
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
        HStack(alignment: .bottom, spacing: 16) {
            TextField("Ask about your recordings...", text: $viewModel.inputText, axis: .vertical)
                .focused($isInputFocused)
                .lineLimit(1...5)
                .padding(10)
                .background(Color(.secondarySystemBackground))
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
                            ? Color.gray
                            : Color.blue
                    )
                    .clipShape(Circle())
            }
            .disabled(viewModel.inputText.trimmingCharacters(in: .whitespaces).isEmpty || viewModel.isLoading)
        }
        .padding()
        .background(Color(.systemBackground))
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
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .center, spacing: 8) {
                Image(systemName: "brain")
                    .foregroundStyle(Color.blue)
                Text("WAI")
                    .font(.caption2)
                    .foregroundStyle(Color.gray)
                    .tracking(1.2)
            }

            Text(answer)
                .font(.body)
                .lineSpacing(4)

            if !sources.isEmpty {
                Button {
                    withAnimation { showSources.toggle() }
                } label: {
                    HStack(spacing: 8) {
                        Text("\(sources.count) source\(sources.count == 1 ? "" : "s")")
                            .font(.subheadline)
                        Image(systemName: showSources ? "chevron.up" : "chevron.down")
                            .font(.caption)
                    }
                    .foregroundStyle(Color.blue)
                }
                .padding(.top, 8)

                if showSources {
                    VStack(alignment: .leading, spacing: 12) {
                        ForEach(sources) { source in
                            VStack(alignment: .leading, spacing: 4) {
                                HStack(spacing: 8) {
                                    if let title = source.recordingTitle {
                                        Text(title)
                                            .font(.subheadline)
                                    }
                                    if let speaker = source.speaker {
                                        Text("(\(speaker))")
                                            .font(.caption)
                                            .foregroundStyle(Color.gray)
                                    }
                                }
                                Text(source.content)
                                    .font(.footnote)
                                    .foregroundStyle(Color.secondary)
                                    .lineLimit(3)
                            }
                            .padding(12)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(Color(.secondarySystemBackground))
                            .cornerRadius(8)
                        }
                    }
                    .padding(.top, 8)
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
