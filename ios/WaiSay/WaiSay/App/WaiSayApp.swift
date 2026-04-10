import SwiftUI
import WaiSayKit

@main
struct WaiSayApp: App {
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var appState = AppState()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(appState)
                .onChange(of: scenePhase) { _, newPhase in
                    guard newPhase == .active else { return }
                    Task {
                        await appState.resumePendingRecordingSyncIfNeeded()
                    }
                }
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

    let apiClient: APIClient

    init() {
        #if !DEBUG
        SentryHelper.start(dsn: "https://0ce75b3bd10ed900ea5e9eb3f043d447@o4508963132145664.ingest.us.sentry.io/4511194363592704")
        #endif

        // Configure API client
        #if DEBUG
        let baseURL = URL(string: "http://localhost:8000")!
        #else
        let baseURL = URL(string: "https://say.waiwai.is")!
        #endif
        apiClient = APIClient(baseURL: baseURL)

        // Set up token refresh callbacks
        Task {
            await apiClient.setOnTokenRefreshed { accessToken, refreshToken in
                KeychainHelper.save(key: KeychainHelper.accessTokenKey, value: accessToken)
                KeychainHelper.save(key: KeychainHelper.refreshTokenKey, value: refreshToken)
                Task {
                    await PendingRecordingSyncCoordinator.shared.scheduleSync(using: self.apiClient)
                }
            }
            await apiClient.setOnAuthenticationFailed { [weak self] in
                Task { @MainActor in
                    self?.handleAuthenticationFailed()
                }
            }
        }

        // Start network monitoring — triggers sync on connectivity recovery
        NetworkMonitor.shared.start { [weak self] in
            guard let self else { return }
            Task { @MainActor in
                await self.resumePendingRecordingSyncIfNeeded()
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
            self.error = error.userFacingMessage(context: .authentication)
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
            self.error = error.userFacingMessage(context: .authentication)
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
        SentryHelper.clearUser()
        currentUser = nil
        isAuthenticated = false
    }

    /// Called when auto-refresh fails — transition to login screen
    private func handleAuthenticationFailed() {
        KeychainHelper.delete(key: KeychainHelper.accessTokenKey)
        KeychainHelper.delete(key: KeychainHelper.refreshTokenKey)
        currentUser = nil
        isAuthenticated = false
    }

    func loadCurrentUser() async {
        do {
            let user = try await apiClient.getCurrentUser()
            currentUser = user
            isAuthenticated = true
            SentryHelper.setUser(id: user.id)
            await PendingRecordingSyncCoordinator.shared.scheduleSync(using: apiClient)
        } catch {
            isAuthenticated = false
            currentUser = nil
            SentryHelper.clearUser()
        }
    }

    func resumePendingRecordingSyncIfNeeded() async {
        guard isAuthenticated else { return }
        await PendingRecordingSyncCoordinator.shared.scheduleSync(using: apiClient)
    }

    private func handleAPIError(_ error: APIError) {
        switch error {
        case .unauthorized:
            self.error = "Invalid credentials"
        case .httpError, .networkError:
            self.error = error.userFacingMessage(context: .authentication)
        default:
            self.error = error.userFacingMessage(context: .authentication)
        }
    }

    func getAPIClient() -> APIClient {
        return apiClient
    }
}
