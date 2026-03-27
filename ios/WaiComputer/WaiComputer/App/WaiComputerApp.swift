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
    @Published var isCheckingAuth = true
    @Published var currentUser: User?
    @Published var isLoading = false
    @Published var error: String?

    private let apiClient: APIClient

    init() {
        // Configure API client
        #if DEBUG
        let baseURL = URL(string: "http://localhost:8000")!
        #else
        let baseURL = URL(string: "https://api.wai.computer")!
        #endif
        apiClient = APIClient(baseURL: baseURL)

        // Migrate from UserDefaults to Keychain (one-time)
        if KeychainHelper.load(key: KeychainHelper.accessTokenKey) == nil,
           let legacyToken = UserDefaults.standard.string(forKey: "accessToken") {
            KeychainHelper.save(key: KeychainHelper.accessTokenKey, value: legacyToken)
            UserDefaults.standard.removeObject(forKey: "accessToken")
        }

        // Set up token refresh callbacks
        Task {
            await apiClient.setOnTokenRefreshed { accessToken, refreshToken in
                KeychainHelper.save(key: KeychainHelper.accessTokenKey, value: accessToken)
                KeychainHelper.save(key: KeychainHelper.refreshTokenKey, value: refreshToken)
            }
            await apiClient.setOnAuthenticationFailed { [weak self] in
                Task { @MainActor in
                    self?.handleAuthenticationFailed()
                }
            }
        }

        // Restore tokens from Keychain
        if let accessToken = KeychainHelper.load(key: KeychainHelper.accessTokenKey) {
            Task {
                await apiClient.setAccessToken(accessToken)
                if let refreshToken = KeychainHelper.load(key: KeychainHelper.refreshTokenKey) {
                    await apiClient.setRefreshToken(refreshToken)
                }
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
            KeychainHelper.save(key: KeychainHelper.accessTokenKey, value: response.accessToken)
            if let rt = response.refreshToken {
                await apiClient.setRefreshToken(rt)
                KeychainHelper.save(key: KeychainHelper.refreshTokenKey, value: rt)
            }
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
            KeychainHelper.save(key: KeychainHelper.accessTokenKey, value: response.accessToken)
            if let rt = response.refreshToken {
                await apiClient.setRefreshToken(rt)
                KeychainHelper.save(key: KeychainHelper.refreshTokenKey, value: rt)
            }
            await loadCurrentUser()
        } catch let apiError as APIError {
            handleAPIError(apiError)
        } catch {
            self.error = error.localizedDescription
        }

        isLoading = false
    }

    func logout() async {
        let rt = await apiClient.getRefreshToken()
        do {
            _ = try await apiClient.logout(refreshToken: rt)
        } catch {
            // Best-effort server logout
        }

        await apiClient.setAccessToken(nil)
        await apiClient.setRefreshToken(nil)
        KeychainHelper.delete(key: KeychainHelper.accessTokenKey)
        KeychainHelper.delete(key: KeychainHelper.refreshTokenKey)
        UserDefaults.standard.removeObject(forKey: "accessToken")
        currentUser = nil
        isAuthenticated = false
    }

    /// Called when auto-refresh fails — transition to login screen
    private func handleAuthenticationFailed() {
        KeychainHelper.delete(key: KeychainHelper.accessTokenKey)
        KeychainHelper.delete(key: KeychainHelper.refreshTokenKey)
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
}
