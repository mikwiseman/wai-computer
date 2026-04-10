import SwiftUI
import WaiSayKit

struct WaiHomeView: View {
    @EnvironmentObject private var appState: AppState

    @State private var showRecorder = false

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                Spacer()

                VStack(spacing: 24) {
                    // Record button
                    Button {
                        showRecorder = true
                    } label: {
                        ZStack {
                            Circle()
                                .fill(Color.red.opacity(0.12))
                                .frame(width: 160, height: 160)

                            Circle()
                                .fill(Color.red)
                                .frame(width: 100, height: 100)

                            Image(systemName: "mic.fill")
                                .font(.system(size: 40))
                                .foregroundStyle(.white)
                        }
                    }
                    .accessibilityLabel("Start recording")

                    Text("Record")
                        .font(.title2.weight(.semibold))

                    Text("Tap to capture transcript, summary, and action items.")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, 32)
                }

                Spacer()
                Spacer()
            }
            .frame(maxWidth: .infinity)
            .navigationTitle("Record")
            .sheet(isPresented: $showRecorder) {
                RecordingView()
                    .environmentObject(appState)
            }
        }
    }
}
