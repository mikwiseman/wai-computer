import SwiftUI
import WaiSayKit

#if DEBUG
enum IOSScreenshotScreen: String {
    case record
    case library
    case detail
    case settings
}
#endif

enum IOSTestingMode: Equatable {
    case live
    #if DEBUG
    case screenshot(IOSScreenshotScreen)
    #endif

    static var current: IOSTestingMode {
        #if DEBUG
        guard ProcessInfo.processInfo.environment["WAI_ENABLE_SCREENSHOT_MODE"] == "1" else {
            return .live
        }

        if let rawValue = ProcessInfo.processInfo.environment["WAI_SCREENSHOT_SCREEN"],
           let screen = IOSScreenshotScreen(rawValue: rawValue) {
            return .screenshot(screen)
        }

        return .screenshot(.record)
        #else
        return .live
        #endif
    }

    var isScreenshot: Bool {
        #if DEBUG
        if case .screenshot = self {
            return true
        }
        #endif
        return false
    }
}

#if DEBUG
enum IOSScreenshotFixtures {
    static let createdAt = Date(timeIntervalSince1970: 1_713_158_400)

    static let user = User(
        id: "ios-screenshot-user",
        email: "hello@waiwai.is",
        createdAt: createdAt
    )

    static let recordings: [Recording] = [
        Recording(
            id: "rec-1",
            title: "Weekly Team Standup",
            type: .meeting,
            status: .ready,
            durationSeconds: 1847,
            createdAt: createdAt
        ),
        Recording(
            id: "rec-2",
            title: "Product Roadmap Sync",
            type: .meeting,
            status: .ready,
            durationSeconds: 2240,
            createdAt: createdAt.addingTimeInterval(-86_400)
        ),
        Recording(
            id: "rec-3",
            title: "Design Review",
            type: .meeting,
            status: .ready,
            durationSeconds: 1640,
            createdAt: createdAt.addingTimeInterval(-172_800)
        ),
        Recording(
            id: "rec-4",
            title: "Customer Interview",
            type: .meeting,
            status: .ready,
            durationSeconds: 1312,
            createdAt: createdAt.addingTimeInterval(-259_200)
        ),
        Recording(
            id: "rec-5",
            title: "Strategy Notes",
            type: .note,
            status: .ready,
            durationSeconds: 905,
            createdAt: createdAt.addingTimeInterval(-345_600)
        ),
        Recording(
            id: "rec-6",
            title: "Morning Reflection",
            type: .reflection,
            status: .ready,
            durationSeconds: 367,
            createdAt: createdAt.addingTimeInterval(-432_000)
        ),
    ]

    static let detailRecording = recordings[0]

    static let detail = RecordingDetail(
        id: detailRecording.id,
        title: detailRecording.title,
        type: detailRecording.type,
        status: .ready,
        durationSeconds: detailRecording.durationSeconds,
        language: "en",
        createdAt: detailRecording.createdAt,
        segments: [
            Segment(
                id: "s1",
                speaker: "Alex",
                content: "Quick update. Search is shipping this week and beta feedback is strong.",
                startMs: 0,
                endMs: 4_800,
                confidence: 0.96
            ),
            Segment(
                id: "s2",
                speaker: "Sarah",
                content: "Mobile capture is stable now. We only need to polish library and summaries.",
                startMs: 5_200,
                endMs: 10_600,
                confidence: 0.95
            ),
            Segment(
                id: "s3",
                speaker: "David",
                content: "Let's push the TestFlight build today and share it with the design partners.",
                startMs: 11_000,
                endMs: 16_300,
                confidence: 0.94
            ),
            Segment(
                id: "s4",
                speaker: "Alex",
                content: "Agreed. We'll package the release notes and screenshots right after QA signs off.",
                startMs: 16_700,
                endMs: 22_400,
                confidence: 0.94
            ),
        ],
        summary: Summary(
            summary: "The team confirmed that search is ready to ship, mobile capture is stable, and the next step is pushing a polished TestFlight build with updated screenshots.",
            keyPoints: [
                "Search is ready to ship this week",
                "Mobile capture is stable",
                "Library and summary polish remain",
            ],
            decisions: [
                Decision(
                    decision: "Ship a new TestFlight build today",
                    context: "Share with design partners immediately after QA"
                ),
            ],
            topics: ["Search", "Mobile Capture", "TestFlight"],
            peopleMentioned: ["Alex", "Sarah", "David"],
            sentiment: "positive"
        ),
        actionItems: {
            let json = """
            [
              {
                "id": "a1",
                "recording_id": "rec-1",
                "task": "Upload fresh TestFlight build",
                "owner": "David",
                "due_date": "2026-04-16",
                "priority": "high",
                "status": "pending",
                "source": "ai"
              },
              {
                "id": "a2",
                "recording_id": "rec-1",
                "task": "Refresh App Store screenshots",
                "owner": "Sarah",
                "due_date": "2026-04-16",
                "priority": "high",
                "status": "pending",
                "source": "ai"
              }
            ]
            """.data(using: .utf8)!
            return try! JSONDecoder().decode([ActionItem].self, from: json)
        }()
    )

    static func recording(id: String) -> Recording {
        recordings.first(where: { $0.id == id }) ?? detailRecording
    }
}
#endif

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
    @Published var hasCompletedOnboarding: Bool = false

    static let onboardingCompletedKey = "nativeOnboardingV1Completed"

    let apiClient: APIClient
    private var hasAttemptedStoredSessionRestore = false

    init() {
        #if !DEBUG
        SentryHelper.start(dsn: "<SENTRY_DSN>")
        #endif

        // Configure API client
        let baseURL = URL(string: "https://say.waiwai.is")!
        apiClient = APIClient(baseURL: baseURL)

        // Resolve onboarding flag honoring env-var overrides used by tests/dev.
        let env = ProcessInfo.processInfo.environment
        if env["WAI_FORCE_ONBOARDING"] == "1" {
            UserDefaults.standard.set(false, forKey: AppState.onboardingCompletedKey)
            hasCompletedOnboarding = false
        } else if env["WAI_SKIP_ONBOARDING"] == "1" {
            UserDefaults.standard.set(true, forKey: AppState.onboardingCompletedKey)
            hasCompletedOnboarding = true
        } else {
            hasCompletedOnboarding = UserDefaults.standard.bool(forKey: AppState.onboardingCompletedKey)
        }

        #if DEBUG
        if IOSTestingMode.current.isScreenshot {
            currentUser = IOSScreenshotFixtures.user
            isAuthenticated = true
            isCheckingAuth = false
            hasCompletedOnboarding = true
            return
        }
        #endif

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

        if hasCompletedOnboarding {
            beginStoredSessionRestoreIfNeeded()
        } else {
            isCheckingAuth = false
        }
    }

    /// Mark the welcome tour as seen. The flag persists across logout and
    /// account deletion — onboarding is a product introduction, not part of
    /// the auth lifecycle.
    func completeOnboarding() {
        UserDefaults.standard.set(true, forKey: AppState.onboardingCompletedKey)
        hasCompletedOnboarding = true
        beginStoredSessionRestoreIfNeeded()
    }

    private func beginStoredSessionRestoreIfNeeded() {
        guard !hasAttemptedStoredSessionRestore else {
            isCheckingAuth = false
            return
        }

        hasAttemptedStoredSessionRestore = true
        isCheckingAuth = true

        // Restore tokens only after onboarding. This avoids a first-launch
        // Keychain prompt and prevents old installs from silently skipping the tour.
        let accessToken: String? = {
            if let arg = ProcessInfo.processInfo.environment["WAISAY_ACCESS_TOKEN"] {
                KeychainHelper.save(key: KeychainHelper.accessTokenKey, value: arg)
                return arg
            }
            return KeychainHelper.load(key: KeychainHelper.accessTokenKey)
        }()
        let refreshOverride = ProcessInfo.processInfo.environment["WAISAY_REFRESH_TOKEN"]
        if let refreshOverride {
            KeychainHelper.save(key: KeychainHelper.refreshTokenKey, value: refreshOverride)
        }

        guard let accessToken else {
            isCheckingAuth = false
            return
        }

        Task {
            await apiClient.setAccessToken(accessToken)
            let rt = refreshOverride ?? KeychainHelper.load(key: KeychainHelper.refreshTokenKey)
            if let rt {
                await apiClient.setRefreshToken(rt)
            }
            await loadCurrentUser()
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

        await clearLocalSession()
    }

    /// Permanently delete the current account. Returns an error message on
    /// failure; on success tokens are cleared and the app is routed back to
    /// the auth screen.
    func deleteAccount() async -> String? {
        guard isAuthenticated else { return nil }
        isLoading = true
        error = nil
        defer { isLoading = false }

        do {
            _ = try await apiClient.deleteAccount()
        } catch {
            SentryHelper.captureError(error, extras: ["action": "deleteAccount"])
            let message = error.userFacingMessage(context: .authentication)
            self.error = message
            return message
        }

        await clearLocalSession()
        return nil
    }

    /// Clear in-memory auth state, API client tokens, Keychain entries, and
    /// Sentry user context. Used by both `logout` and `deleteAccount`.
    private func clearLocalSession() async {
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
        Task {
            await apiClient.setAccessToken(nil)
            await apiClient.setRefreshToken(nil)
        }
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
