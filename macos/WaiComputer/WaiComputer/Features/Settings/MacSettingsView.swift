import SwiftUI
import WaiComputerKit

struct MacSettingsView: View {
    @EnvironmentObject var appState: MacAppState
    @State private var showSignOutConfirmation = false

    var body: some View {
        Form {
            Section {
                if let user = appState.currentUser {
                    LabeledContent("Email", value: user.email)
                        .font(Typography.body)
                    LabeledContent("Member Since", value: user.createdAt.formatted(date: .long, time: .omitted))
                        .font(Typography.body)
                }
            } header: {
                Text("Account")
                    .waiSectionHeader()
            }

            Section {
                let devices = SystemAudioManager.shared.availableDevices
                if devices.isEmpty {
                    Text("No audio input devices found")
                        .font(Typography.body)
                        .foregroundStyle(Palette.textSecondary)
                } else {
                    ForEach(devices) { device in
                        HStack {
                            Image(systemName: device.isBlackHole ? "speaker.wave.2" : "mic")
                                .foregroundStyle(Palette.textTertiary)
                            Text(device.name)
                                .font(Typography.body)
                            Spacer()
                            if device.isInput {
                                Text("Input")
                                    .font(Typography.caption)
                                    .foregroundStyle(Palette.textTertiary)
                            }
                        }
                    }
                }

                if !SystemAudioManager.shared.isBlackHoleInstalled {
                    HStack {
                        Image(systemName: "exclamationmark.triangle")
                            .foregroundStyle(Palette.accent)
                        Text("BlackHole not installed — system audio capture unavailable")
                            .font(Typography.bodySmall)
                    }
                }
            } header: {
                Text("Audio")
                    .waiSectionHeader()
            }

            Section {
                LabeledContent("Version") {
                    Text(Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0.0")
                        .font(Typography.mono)
                }
            } header: {
                Text("About")
                    .waiSectionHeader()
            }

            Section {
                Button("Sign Out") {
                    showSignOutConfirmation = true
                }
                .font(Typography.body)
                .foregroundStyle(Palette.textSecondary)
            }
        }
        .formStyle(.grouped)
        .confirmationDialog("Are you sure you want to sign out?", isPresented: $showSignOutConfirmation) {
            Button("Sign Out", role: .destructive) {
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
