import SwiftUI
import WaiComputerKit

@main
struct WaiComputerApp: App {
    @StateObject private var appState = AppState()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(appState)
        }
    }
}

/// Global app state
@MainActor
class AppState: ObservableObject {
    @Published var isAuthenticated = false
    @Published var currentUser: User?
    @Published var isLoading = false
    @Published var error: String?

    private let apiClient: APIClient
    private let webSocketManager: WebSocketManager

    init() {
        // Configure API client
        #if DEBUG
        let baseURL = URL(string: "http://localhost:8000")!
        #else
        let baseURL = URL(string: "https://api.wai.computer")!
        #endif
        apiClient = APIClient(baseURL: baseURL)
        webSocketManager = WebSocketManager(baseURL: baseURL)

        // Check for saved token
        if let token = UserDefaults.standard.string(forKey: "accessToken") {
            Task {
                await apiClient.setAccessToken(token)
                await webSocketManager.setAccessToken(token)
                await loadCurrentUser()
            }
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

    func getAPIClient() -> APIClient {
        return apiClient
    }

    func getWebSocketManager() -> WebSocketManager {
        return webSocketManager
    }
}
