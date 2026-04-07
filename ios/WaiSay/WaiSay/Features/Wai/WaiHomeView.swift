import SwiftUI
import WaiSayKit

struct WaiHomeView: View {
    @EnvironmentObject private var appState: AppState

    @State private var messages: [WaiAgentMessage] = []
    @State private var input = ""
    @State private var sessionId: String?
    @State private var isLoading = false
    @State private var error: String?
    @State private var showRecorder = false
    @State private var voiceSession: RealtimeVoiceSession?
    @State private var isPreparingVoice = false

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                if messages.isEmpty && !isLoading {
                    emptyState
                } else {
                    messageList
                }

                if let voiceSession {
                    voiceSessionBanner(voiceSession)
                }

                if let error {
                    Text(error)
                        .font(.caption)
                        .foregroundStyle(.red)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.horizontal)
                        .padding(.top, 8)
                }

                Divider()
                inputBar
            }
            .navigationTitle("Wai")
            .toolbar {
                ToolbarItemGroup(placement: .topBarTrailing) {
                    Button {
                        Task { await prepareVoiceSession(mode: .conversation) }
                    } label: {
                        if isPreparingVoice {
                            ProgressView()
                        } else {
                            Image(systemName: "waveform.badge.mic")
                        }
                    }
                    .help("Prepare realtime conversation")

                    Button {
                        showRecorder = true
                    } label: {
                        Image(systemName: "mic.circle")
                    }
                }
            }
            .sheet(isPresented: $showRecorder) {
                RecordingView()
                    .environmentObject(appState)
            }
        }
    }

    private var emptyState: some View {
        ScrollView {
            VStack(spacing: 24) {
                VStack(spacing: 12) {
                    Image(systemName: "brain.head.profile")
                        .font(.system(size: 58))
                        .foregroundStyle(.blue)

                    Text("Talk to Wai")
                        .font(.title2.weight(.semibold))

                    Text("Start with text, prepare a realtime voice session, or open recording mode for notes and meetings.")
                        .multilineTextAlignment(.center)
                        .foregroundStyle(.secondary)
                        .padding(.horizontal)
                }
                .padding(.top, 40)

                VStack(spacing: 12) {
                    quickAction(
                        title: "Create a landing page",
                        subtitle: "Draft, preview, and publish from one dialogue."
                    ) {
                        input = "Create a landing page for my product and prepare it for publish."
                    }

                    quickAction(
                        title: "Create an app",
                        subtitle: "Generate a collection-backed app and keep it in my shelf."
                    ) {
                        input = "Create a simple CRM app for my clients."
                    }

                    quickAction(
                        title: "Run voice session",
                        subtitle: "Prepare a realtime conversation session with Wai."
                    ) {
                        Task { await prepareVoiceSession(mode: .conversation) }
                    }

                    quickAction(
                        title: "Record a meeting",
                        subtitle: "Capture transcript, summary, and commitments."
                    ) {
                        showRecorder = true
                    }
                }
                .padding(.horizontal)
            }
            .frame(maxWidth: .infinity)
        }
    }

    private var messageList: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 12) {
                    ForEach(messages) { message in
                        WaiMessageRow(message: message)
                            .id(message.id)
                    }

                    if isLoading {
                        HStack(spacing: 8) {
                            ProgressView()
                                .controlSize(.small)
                            Text("Wai is working…")
                                .font(.footnote)
                                .foregroundStyle(.secondary)
                        }
                        .padding(.horizontal)
                    }
                }
                .padding()
            }
            .onChange(of: messages.count) { _, _ in
                guard let lastId = messages.last?.id else { return }
                withAnimation {
                    proxy.scrollTo(lastId, anchor: .bottom)
                }
            }
        }
    }

    private var inputBar: some View {
        HStack(alignment: .bottom, spacing: 12) {
            TextField("Say or type what you need…", text: $input, axis: .vertical)
                .textFieldStyle(.roundedBorder)
                .lineLimit(1...4)

            Button(action: sendMessage) {
                Image(systemName: "arrow.up.circle.fill")
                    .font(.system(size: 28))
                    .foregroundStyle(input.trimmed().isEmpty || isLoading ? Color.secondary : Color.blue)
            }
            .disabled(input.trimmed().isEmpty || isLoading)
        }
        .padding()
    }

    private func quickAction(title: String, subtitle: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(.headline)
                    .foregroundStyle(.primary)
                Text(subtitle)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding()
            .background(Color(.secondarySystemBackground))
            .clipShape(RoundedRectangle(cornerRadius: 14))
        }
        .buttonStyle(.plain)
    }

    private func voiceSessionBanner(_ voiceSession: RealtimeVoiceSession) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Label("Realtime voice session ready", systemImage: "waveform.badge.checkmark")
                    .font(.subheadline.weight(.semibold))
                Spacer()
                Text(voiceSession.mode.capitalized)
                    .font(.caption.weight(.medium))
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(Color.blue.opacity(0.12))
                    .clipShape(Capsule())
            }

            Text("Provider: \(voiceSession.provider). Agent: \(voiceSession.agentId). Expires in \(voiceSession.expiresInSeconds / 60)m.")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding()
        .background(Color.blue.opacity(0.08))
        .clipShape(RoundedRectangle(cornerRadius: 14))
        .padding(.horizontal)
        .padding(.bottom, 8)
    }

    private func sendMessage() {
        let text = input.trimmed()
        guard !text.isEmpty, !isLoading else { return }

        error = nil
        messages.append(WaiAgentMessage(id: UUID().uuidString, role: .user, content: text, intent: nil))
        input = ""
        isLoading = true

        Task {
            do {
                let result = try await appState.getAPIClient().sendAgentMessage(text, sessionId: sessionId)
                sessionId = result.sessionId
                messages.append(
                    WaiAgentMessage(
                        id: UUID().uuidString,
                        role: .assistant,
                        content: result.response,
                        intent: result.intent
                    )
                )
            } catch {
                self.error = error.userFacingMessage(context: .generic)
            }
            isLoading = false
        }
    }

    private func prepareVoiceSession(mode: RealtimeVoiceMode) async {
        guard !isPreparingVoice else { return }
        isPreparingVoice = true
        defer { isPreparingVoice = false }

        do {
            error = nil
            voiceSession = try await appState.getAPIClient().createRealtimeVoiceSession(mode: mode)
        } catch {
            self.error = error.userFacingMessage(context: .generic)
        }
    }
}

private struct WaiAgentMessage: Identifiable {
    enum Role {
        case user
        case assistant
    }

    let id: String
    let role: Role
    let content: String
    let intent: String?
}

private struct WaiMessageRow: View {
    let message: WaiAgentMessage

    var body: some View {
        HStack {
            if message.role == .assistant {
                bubble
                Spacer(minLength: 40)
            } else {
                Spacer(minLength: 40)
                bubble
            }
        }
    }

    private var bubble: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(message.content)
                .foregroundStyle(message.role == .user ? .white : .primary)
            if let intent = message.intent, message.role == .assistant {
                Text(intent.uppercased())
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(.secondary)
            }
        }
        .padding(12)
        .background(message.role == .user ? Color.blue : Color(.secondarySystemBackground))
        .clipShape(RoundedRectangle(cornerRadius: 14))
    }
}

private extension String {
    func trimmed() -> String {
        trimmingCharacters(in: .whitespacesAndNewlines)
    }
}
