import SwiftUI
import WaiComputerKit

@main
struct WaiComputerMacApp: App {
    @StateObject private var appState = MacAppState()

    var body: some Scene {
        WindowGroup {
            MacContentView()
                .environmentObject(appState)
                .environmentObject(appState.recordingViewModel)
                .onOpenURL { url in
                    Task { await appState.handleIncomingURL(url) }
                }
                .handlesExternalEvents(preferring: Set(["main"]), allowing: Set(["main"]))
        }
        .handlesExternalEvents(matching: Set(["main"]))
        .windowStyle(.hiddenTitleBar)
        .defaultSize(width: 1200, height: 800)
        .commands {
            // Replace default Cmd+N (new window) with new recording
            CommandGroup(replacing: .newItem) {
                Button("New Recording") {
                    Task { await appState.startRecording(type: .note) }
                }
                .keyboardShortcut("n", modifiers: .command)
                .disabled(appState.isRecording || !appState.isAuthenticated)
            }

            // Remove the default "New Window" from the Window menu
            CommandGroup(replacing: .windowList) {}
        }

        // Menu bar extra
        MenuBarExtra("WaiComputer", systemImage: appState.isRecording ? "waveform.circle.fill" : "brain.head.profile") {
            MenuBarView()
                .environmentObject(appState)
                .environmentObject(appState.recordingViewModel)
        }
        .menuBarExtraStyle(.window)
    }
}

/// Mac-specific app state with system audio support
@MainActor
class MacAppState: ObservableObject {
    @Published var isAuthenticated = false
    @Published var isCheckingAuth = true
    @Published var currentUser: User?
    @Published var isLoading = false
    @Published var error: String?
    @Published var magicLinkSent = false
    @Published var isRecording = false
    @Published var currentRecordingId: String?
    @Published var selectedRecordingFromMenu: String?

    /// Recording view model — observed directly by recording views via @EnvironmentObject,
    /// NOT forwarded through MacAppState's objectWillChange. This prevents the entire
    /// view hierarchy from rebuilding on every timer tick and transcript update.
    let recordingViewModel = MacRecordingViewModel()

    private let apiClient: APIClient
    private let webSocketManager: WebSocketManager

    init() {
        let baseURL = URL(string: "https://wai.computer")!
        apiClient = APIClient(baseURL: baseURL)
        webSocketManager = WebSocketManager(baseURL: baseURL)

        if let token = UserDefaults.standard.string(forKey: "accessToken") {
            Task {
                await apiClient.setAccessToken(token)
                await webSocketManager.setAccessToken(token)
                await loadCurrentUser()
                isCheckingAuth = false
            }
        } else {
            isCheckingAuth = false
        }
    }

    func login(email: String, password: String) async {
        isLoading = true
        error = nil

        do {
            let response = try await apiClient.login(email: email, password: password)
            await apiClient.setAccessToken(response.accessToken)
            await webSocketManager.setAccessToken(response.accessToken)
            UserDefaults.standard.set(response.accessToken, forKey: "accessToken")
            await loadCurrentUser()
        } catch let apiError as APIError {
            handleAPIError(apiError)
        } catch {
            self.error = error.localizedDescription
        }

        isLoading = false
    }

    func register(email: String, password: String) async {
        isLoading = true
        error = nil

        do {
            let response = try await apiClient.register(email: email, password: password)
            await apiClient.setAccessToken(response.accessToken)
            await webSocketManager.setAccessToken(response.accessToken)
            UserDefaults.standard.set(response.accessToken, forKey: "accessToken")
            await loadCurrentUser()
        } catch let apiError as APIError {
            handleAPIError(apiError)
        } catch {
            self.error = error.localizedDescription
        }

        isLoading = false
    }

    func requestMagicLink(email: String) async {
        isLoading = true
        error = nil

        do {
            _ = try await apiClient.requestMagicLink(email: email, client: "macos")
            magicLinkSent = true
        } catch let apiError as APIError {
            handleAPIError(apiError)
        } catch {
            self.error = error.localizedDescription
        }

        isLoading = false
    }

    func handleIncomingURL(_ url: URL) async {
        guard url.scheme == "waicomputer",
              url.host == "auth",
              url.path == "/verify" || url.path == "verify",
              let components = URLComponents(url: url, resolvingAgainstBaseURL: false),
              let token = components.queryItems?.first(where: { $0.name == "token" })?.value
        else { return }

        isLoading = true
        error = nil

        do {
            let response = try await apiClient.verifyMagicLink(token: token)
            await apiClient.setAccessToken(response.accessToken)
            await webSocketManager.setAccessToken(response.accessToken)
            UserDefaults.standard.set(response.accessToken, forKey: "accessToken")
            magicLinkSent = false
            await loadCurrentUser()
        } catch let apiError as APIError {
            handleAPIError(apiError)
        } catch {
            self.error = error.localizedDescription
        }

        isLoading = false
    }

    func logout() async {
        await apiClient.setAccessToken(nil)
        await webSocketManager.setAccessToken(nil)
        UserDefaults.standard.removeObject(forKey: "accessToken")
        currentUser = nil
        isAuthenticated = false
    }

    func loadCurrentUser() async {
        do {
            let user = try await apiClient.getCurrentUser()
            currentUser = user
            isAuthenticated = true
        } catch {
            isAuthenticated = false
            currentUser = nil
        }
    }

    private func handleAPIError(_ error: APIError) {
        switch error {
        case .unauthorized:
            self.error = "Invalid credentials"
        case .httpError(_, let message):
            self.error = message ?? "An error occurred"
        case .networkError:
            self.error = "Network error. Please check your connection."
        default:
            self.error = "An unexpected error occurred"
        }
    }

    func startRecording(type: RecordingType) async {
        // Set isRecording IMMEDIATELY so the UI switches to LiveRecordingView
        // before the async setup (API call, WebSocket connect, audio start) completes.
        // If setup fails, the view model will set its own isRecording back to false,
        // and we sync that state below.
        isRecording = true

        await recordingViewModel.startRecording(
            apiClient: apiClient,
            webSocketManager: webSocketManager,
            type: type
        )

        // Sync state after setup completes — if setup failed,
        // recordingViewModel.isRecording will be false
        isRecording = recordingViewModel.isRecording
        currentRecordingId = recordingViewModel.currentRecordingId
    }

    func stopRecording() async {
        await recordingViewModel.stopRecording()
        isRecording = false
        // Keep currentRecordingId from recordingViewModel so the UI
        // can navigate to the completed recording detail view
    }

    /// Reset recording state after navigating away from live recording view.
    /// Safe to call while cleanup is in progress — only resets display state.
    func resetRecordingState() {
        // Only reset transcript/display state, not lifecycle state.
        // The cleanup task in MacRecordingViewModel manages its own lifecycle.
        recordingViewModel.resetState()
        currentRecordingId = nil
    }

    func getAPIClient() -> APIClient {
        return apiClient
    }

    func getWebSocketManager() -> WebSocketManager {
        return webSocketManager
    }
}
