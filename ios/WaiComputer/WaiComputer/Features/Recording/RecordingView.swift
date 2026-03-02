import SwiftUI
import WaiComputerKit

struct RecordingView: View {
    @EnvironmentObject var appState: AppState
    @StateObject private var viewModel = RecordingViewModel()

    var body: some View {
        NavigationStack {
            VStack(spacing: 32) {
                Spacer()

                // Recording type selector
                Picker("Type", selection: $viewModel.recordingType) {
                    Text("Note").tag(RecordingType.note)
                    Text("Meeting").tag(RecordingType.meeting)
                    Text("Reflection").tag(RecordingType.reflection)
                }
                .pickerStyle(.segmented)
                .padding(.horizontal)

                // Recording status
                VStack(spacing: 16) {
                    // Waveform or status indicator
                    ZStack {
                        Circle()
                            .fill(viewModel.isRecording ? Color.red.opacity(0.2) : Color.gray.opacity(0.1))
                            .frame(width: 200, height: 200)

                        Circle()
                            .fill(viewModel.isRecording ? Color.red.opacity(0.4) : Color.gray.opacity(0.2))
                            .frame(width: 150, height: 150)
                            .scaleEffect(viewModel.isRecording ? 1.1 : 1.0)
                            .animation(.easeInOut(duration: 0.5).repeatForever(autoreverses: true), value: viewModel.isRecording)

                        Image(systemName: viewModel.isRecording ? "waveform" : "mic.fill")
                            .font(.system(size: 60))
                            .foregroundStyle(viewModel.isRecording ? .red : .gray)
                    }

                    // Duration
                    Text(viewModel.formattedDuration)
                        .font(.system(size: 48, weight: .light, design: .monospaced))
                        .foregroundStyle(viewModel.isRecording ? .primary : .secondary)
                }

                // Live transcript preview
                if viewModel.isRecording && !viewModel.currentTranscript.isEmpty {
                    ScrollView {
                        Text(viewModel.currentTranscript)
                            .font(.body)
                            .padding()
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .frame(maxHeight: 150)
                    .background(Color.gray.opacity(0.1))
                    .cornerRadius(12)
                    .padding(.horizontal)
                }

                Spacer()

                // Record button
                Button(action: {
                    Task {
                        if viewModel.isRecording {
                            await viewModel.stopRecording()
                        } else {
                            await viewModel.startRecording(
                                apiClient: appState.getAPIClient(),
                                webSocketManager: appState.getWebSocketManager()
                            )
                        }
                    }
                }) {
                    ZStack {
                        Circle()
                            .fill(viewModel.isRecording ? .red : .blue)
                            .frame(width: 80, height: 80)

                        if viewModel.isRecording {
                            RoundedRectangle(cornerRadius: 8)
                                .fill(.white)
                                .frame(width: 30, height: 30)
                        } else {
                            Circle()
                                .fill(.white)
                                .frame(width: 30, height: 30)
                        }
                    }
                }
                .disabled(viewModel.isLoading)

                // Status text
                Text(viewModel.statusText)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .padding(.bottom)
            }
            .navigationTitle("Record")
            .alert("Error", isPresented: .constant(viewModel.error != nil)) {
                Button("OK") { viewModel.error = nil }
            } message: {
                Text(viewModel.error ?? "")
            }
        }
    }
}

#Preview {
    RecordingView()
        .environmentObject(AppState())
}
