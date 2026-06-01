import SwiftUI
import WaiComputerKit

struct ContentView: View {
    @EnvironmentObject var appState: AppState

    var body: some View {
        let environment = ProcessInfo.processInfo.environment
        Group {
            if appState.isCheckingAuth {
                ProgressView("Loading...")
            } else if !appState.hasCompletedOnboarding {
                OnboardingView()
            } else if appState.isAuthenticated {
                if let recId = environment["WAICOMPUTER_RECORDING_ID"] {
                    NavigationStack {
                        RecordingDetailView(recording: screenshotRecording(for: recId))
                    }
                } else {
                    MainTabView()
                }
            } else {
                AuthView()
            }
        }
    }

    private func screenshotRecording(for id: String) -> Recording {
        #if DEBUG
        if IOSTestingMode.current.isScreenshot {
            return IOSScreenshotFixtures.recording(id: id)
        }
        #endif

        return Recording(id: id, type: .meeting, createdAt: Date())
    }
}

struct MainTabView: View {
    @EnvironmentObject var languageManager: LanguageManager
    @EnvironmentObject var appState: AppState
    @AppStorage("selectedTab") private var selectedTab = 0
    @StateObject private var recordingViewModel = RecordingViewModel()
    @State private var recoveryNotice: String?
    @State private var recoveryNoticeDismissTask: Task<Void, Never>?

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }

    var body: some View {
        TabView(selection: $selectedTab) {
            RecordingView()
                .tabItem {
                    Label(t("Record", "Запись"), systemImage: "mic.circle.fill")
                }
                .tag(0)

            LibraryView()
                .tabItem {
                    Label(t("Library", "Библиотека"), systemImage: "folder.fill")
                }
                .tag(1)

            SecondBrainView(apiClient: appState.getAPIClient())
                .tabItem {
                    Label(t("Brain", "Мозг"), systemImage: "brain")
                }
                .tag(2)

            WaiHomeView()
                .tabItem {
                    Label("Wai", systemImage: "sparkles")
                }
                .tag(3)

            SettingsView()
                .tabItem {
                    Label(t("Settings", "Настройки"), systemImage: "gear")
                }
                .tag(4)
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
            // Clamp into valid range (0 Record / 1 Library / 2 Brain / 3 Wai / 4 Settings)
            if !(0...4).contains(selectedTab) { selectedTab = 0 }
            // Allow env override for screenshots
            if let tab = ProcessInfo.processInfo.environment["WAICOMPUTER_TAB"],
               let n = Int(tab) { selectedTab = n }
        }
        .onReceive(NotificationCenter.default.publisher(for: .pendingRecordingRecoveryNotice)) { notification in
            guard let message = notification.userInfo?["message"] as? String,
                  !message.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            else { return }
            recoveryNotice = message
            scheduleRecoveryNoticeDismiss()
        }
        // Deep-link section navigation, mirroring MacContentView.swift:496-507.
        // The target is carried as `object` to match the macOS poster contract
        // (WaiComputerMacApp.swift:207-236). Only targets backed by an iOS tab
        // are handled; others are ignored rather than guessed at.
        .onReceive(NotificationCenter.default.publisher(for: .init("navigateTo"))) { notification in
            guard let target = notification.object as? String else { return }
            switch target {
            case "allRecordings": selectedTab = 1
            case "wai": selectedTab = 2
            case "settings": selectedTab = 3
            default: break
            }
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
