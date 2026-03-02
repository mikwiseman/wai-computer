import SwiftUI
import WaiComputerKit

struct MacSettingsView: View {
    @EnvironmentObject var appState: MacAppState
    @State private var showLogoutConfirmation = false

    var body: some View {
        Form {
            Section("Account") {
                if let user = appState.currentUser {
                    LabeledContent("Email", value: user.email)
                    LabeledContent("Member Since", value: user.createdAt.formatted(date: .long, time: .omitted))
                }
            }

            Section("Audio") {
                let devices = SystemAudioManager.shared.availableDevices
                if devices.isEmpty {
                    Text("No audio input devices found")
                        .foregroundStyle(.secondary)
                } else {
                    ForEach(devices) { device in
                        HStack {
                            Image(systemName: device.isBlackHole ? "speaker.wave.2" : "mic")
                                .foregroundStyle(.secondary)
                            Text(device.name)
                            Spacer()
                            if device.isInput {
                                Text("Input")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                }

                if !SystemAudioManager.shared.isBlackHoleInstalled {
                    HStack {
                        Image(systemName: "exclamationmark.triangle")
                            .foregroundStyle(.orange)
                        Text("BlackHole not installed — system audio capture unavailable")
                            .font(.caption)
                    }
                }
            }

            Section("About") {
                LabeledContent("Version") {
                    Text(Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0.0")
                }
            }

            Section {
                Button("Logout", role: .destructive) {
                    showLogoutConfirmation = true
                }
            }
        }
        .formStyle(.grouped)
        .confirmationDialog("Are you sure you want to logout?", isPresented: $showLogoutConfirmation) {
            Button("Logout", role: .destructive) {
                Task {
                    await appState.logout()
                }
            }
            Button("Cancel", role: .cancel) {}
        }
        .onAppear {
            SystemAudioManager.shared.refreshDevices()
        }
    }
}
