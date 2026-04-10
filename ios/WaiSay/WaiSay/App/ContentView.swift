import SwiftUI
import WaiSayKit

struct ContentView: View {
    @EnvironmentObject var appState: AppState

    var body: some View {
        Group {
            if appState.isCheckingAuth {
                ProgressView("Loading...")
            } else if appState.isAuthenticated {
                MainTabView()
            } else {
                AuthView()
            }
        }
    }
}

struct MainTabView: View {
    @AppStorage("selectedTab") private var selectedTab = 0
    @StateObject private var recordingViewModel = RecordingViewModel()
    @State private var recoveryNotice: String?
    @State private var recoveryNoticeDismissTask: Task<Void, Never>?

    var body: some View {
        TabView(selection: $selectedTab) {
            WaiHomeView()
                .tabItem {
                    Label("Record", systemImage: "mic.circle.fill")
                }
                .tag(0)

            LibraryView()
                .tabItem {
                    Label("Library", systemImage: "folder.fill")
                }
                .tag(1)

            SettingsView()
                .tabItem {
                    Label("Settings", systemImage: "gear")
                }
                .tag(2)
        }
        .environmentObject(recordingViewModel)
        .overlay(alignment: .top) {
            if let recoveryNotice {
                RecordingRecoveryBanner(message: recoveryNotice) {
                    dismissRecoveryNotice()
                }
                .padding(.top, 12)
                .padding(.horizontal, 12)
            }
        }
        .onAppear {
            // Migrate stored tab index after removing Apps tab (was tag 4/5)
            if selectedTab > 2 { selectedTab = 0 }
        }
        .onReceive(NotificationCenter.default.publisher(for: .pendingRecordingRecoveryNotice)) { notification in
            guard let message = notification.userInfo?["message"] as? String,
                  !message.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            else { return }
            recoveryNotice = message
            scheduleRecoveryNoticeDismiss()
        }
    }

    private func dismissRecoveryNotice() {
        recoveryNoticeDismissTask?.cancel()
        recoveryNoticeDismissTask = nil
        recoveryNotice = nil
    }

    private func scheduleRecoveryNoticeDismiss() {
        recoveryNoticeDismissTask?.cancel()
        recoveryNoticeDismissTask = Task {
            try? await Task.sleep(for: .seconds(8))
            guard !Task.isCancelled else { return }
            await MainActor.run {
                recoveryNotice = nil
                recoveryNoticeDismissTask = nil
            }
        }
    }
}

private struct RecordingRecoveryBanner: View {
    let message: String
    let onDismiss: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: "checkmark.circle.fill")
                .foregroundStyle(.green)
                .font(.headline)

            Text(message)
                .font(.subheadline)
                .foregroundStyle(.primary)
                .frame(maxWidth: .infinity, alignment: .leading)

            Button(action: onDismiss) {
                Image(systemName: "xmark")
                    .font(.caption.bold())
                    .foregroundStyle(.secondary)
            }
            .buttonStyle(.plain)
        }
        .padding(14)
        .background(.ultraThinMaterial)
        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
        .shadow(color: .black.opacity(0.12), radius: 10, y: 4)
        .accessibilityIdentifier("recording-recovery-banner")
    }
}

#Preview {
    ContentView()
        .environmentObject(AppState())
}
