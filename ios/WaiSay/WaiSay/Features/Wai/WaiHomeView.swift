import SwiftUI
import WaiSayKit

struct WaiHomeView: View {
    @EnvironmentObject private var appState: AppState

    @State private var error: String?
    @State private var showRecorder = false
    @State private var voiceSession: RealtimeVoiceSession?
    @State private var isPreparingVoice = false

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                emptyState

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

                Spacer()
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

                    Text("Prepare a realtime voice session, or open recording mode for notes and meetings.")
                        .multilineTextAlignment(.center)
                        .foregroundStyle(.secondary)
                        .padding(.horizontal)
                }
                .padding(.top, 40)

                VStack(spacing: 12) {
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

            Text("Provider: \(voiceSession.provider). Model: \(voiceSession.modelId). Expires in \(voiceSession.expiresInSeconds / 60)m.")
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding()
        .background(Color.blue.opacity(0.08))
        .clipShape(RoundedRectangle(cornerRadius: 14))
        .padding(.horizontal)
        .padding(.bottom, 8)
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
