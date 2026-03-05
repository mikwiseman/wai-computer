import SwiftUI
import WaiComputerKit

@main
struct WaiComputerMacApp: App {
    @StateObject private var appState = MacAppState()

    var body: some Scene {
        WindowGroup {
            MacContentView()
                .environmentObject(appState)
                .onOpenURL { url in
                    Task { await appState.handleIncomingURL(url) }
                }
        }
        .windowStyle(.hiddenTitleBar)
        .defaultSize(width: 1200, height: 800)

        // Menu bar extra
        MenuBarExtra("WaiComputer", systemImage: appState.isRecording ? "waveform.circle.fill" : "brain.head.profile") {
            MenuBarView()
                .environmentObject(appState)
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
    @Published var recordingViewModel = MacRecordingViewModel()

    private let apiClient: APIClient
    private let webSocketManager: WebSocketManager

    init() {
        #if DEBUG
        let baseURL = URL(string: "http://localhost:8000")!
        #else
        let baseURL = URL(string: "https://api.wai.computer")!
        #endif
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
        await recordingViewModel.startRecording(
            apiClient: apiClient,
            webSocketManager: webSocketManager,
            type: type
        )
        isRecording = recordingViewModel.isRecording
        currentRecordingId = recordingViewModel.currentRecordingId
    }

    func stopRecording() async {
        await recordingViewModel.stopRecording()
        isRecording = false
        currentRecordingId = nil
    }

    func getAPIClient() -> APIClient {
        return apiClient
    }

    func getWebSocketManager() -> WebSocketManager {
        return webSocketManager
    }
}
