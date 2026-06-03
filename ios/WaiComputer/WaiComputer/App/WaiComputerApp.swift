import SwiftUI
import WaiComputerKit

#if DEBUG
enum IOSScreenshotScreen: String {
    case record
    case library
    case detail
    case settings
    case search
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

    static let searchResponse: SearchResponse = {
        let data = """
        {
            "results": [
                {
                    "recording_id": "rec-1",
                    "recording_title": "Weekly Team Standup",
                    "recording_type": "meeting",
                    "segment_id": "search-seg-1",
                    "speaker": "Alex",
                    "content": "Quick update. Search is shipping this week and beta feedback is strong.",
                    "start_ms": 0,
                    "end_ms": 4800,
                    "score": 0.96
                },
                {
                    "recording_id": "rec-2",
                    "recording_title": "Product Roadmap Sync",
                    "recording_type": "meeting",
                    "segment_id": "search-seg-2",
                    "speaker": "Sarah",
                    "content": "We aligned the roadmap around search, capture stability, and the library polish.",
                    "start_ms": 12000,
                    "end_ms": 19200,
                    "score": 0.74
                }
            ],
            "total": 2
        }
        """.data(using: .utf8)!
        guard let response = try? JSONDecoder().decode(SearchResponse.self, from: data) else {
            fatalError("searchResponse fixture JSON is malformed — fix IOSScreenshotFixtures")
        }
        return response
    }()

    static func recording(id: String) -> Recording {
        recordings.first(where: { $0.id == id }) ?? detailRecording
    }
}
#endif

@main
struct WaiComputerApp: App {
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var appState = AppState()
    @StateObject private var languageManager = LanguageManager.shared
    @AppStorage(IOSThemePreferences.appearanceKey) private var appearanceModeRawValue = IOSThemePreferences.defaultAppearance.rawValue
    @AppStorage(IOSThemePreferences.accentKey) private var accentChoiceRawValue = IOSThemePreferences.defaultAccent.rawValue

    private var appearanceMode: IOSAppearanceMode {
        IOSAppearanceMode(rawValue: appearanceModeRawValue) ?? IOSThemePreferences.defaultAppearance
    }

    private var accentChoice: IOSAccentChoice {
        IOSAccentChoice(rawValue: accentChoiceRawValue) ?? IOSThemePreferences.defaultAccent
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environment(\.locale, languageManager.preferredLocale)
                .environmentObject(languageManager)
                .environmentObject(appState)
                .preferredColorScheme(appearanceMode.preferredColorScheme)
                .tint(accentChoice.tintColor)
                .onOpenURL { url in
                    Task { await appState.handleIncomingURL(url) }
                }
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
    @Published var magicLinkSent = false
    @Published var passwordResetSent = false

    static let onboardingCompletedKey = "nativeOnboardingV2Completed"

    let apiClient: APIClient
    private var hasAttemptedStoredSessionRestore = false

    init() {
        #if !DEBUG
        SentryHelper.start(dsn: "https://b677540a781e0058c8568b614d517530@o4508963132145664.ingest.us.sentry.io/4511116052070400")
        #endif

        // Configure API client
        let baseURL = URL(string: "https://wai.computer")!
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
            if let arg = ProcessInfo.processInfo.environment["WAICOMPUTER_ACCESS_TOKEN"] {
                KeychainHelper.save(key: KeychainHelper.accessTokenKey, value: arg)
                return arg
            }
            return KeychainHelper.load(key: KeychainHelper.accessTokenKey)
        }()
        let refreshOverride = ProcessInfo.processInfo.environment["WAICOMPUTER_REFRESH_TOKEN"]
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

    func register(email: String, password: String, acceptedLegalTerms: Bool) async {
        isLoading = true
        error = nil

        do {
            let response = try await apiClient.register(
                email: email,
                password: password,
                acceptedLegalTerms: acceptedLegalTerms
            )
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

    /// In-app language → backend locale tag ("ru" or "en"). Mirrors macOS.
    private var authLocale: String {
        LanguageManager.shared.preferredLocale.language.languageCode?.identifier == "ru" ? "ru" : "en"
    }

    /// Request a passwordless sign-in link. Mirrors macOS `requestMagicLink`.
    func requestMagicLink(email: String, acceptedLegalTerms: Bool = false) async {
        isLoading = true
        error = nil
        do {
            _ = try await apiClient.requestMagicLink(
                email: email,
                client: "ios",
                locale: authLocale,
                acceptedLegalTerms: acceptedLegalTerms
            )
            magicLinkSent = true
        } catch let apiError as APIError {
            handleAPIError(apiError)
        } catch {
            self.error = error.userFacingMessage(context: .authentication)
        }
        isLoading = false
    }

    /// Request a password-reset email. Mirrors macOS `requestPasswordReset`.
    func requestPasswordReset(email: String, locale: String?) async {
        isLoading = true
        error = nil
        do {
            _ = try await apiClient.requestPasswordReset(email: email, locale: locale)
            passwordResetSent = true
        } catch let apiError as APIError {
            handleAPIError(apiError)
        } catch {
            self.error = error.userFacingMessage(context: .authentication)
        }
        isLoading = false
    }

    /// Handle the magic-link deep link `waicomputer://auth/verify?token=…`.
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
            KeychainHelper.save(key: KeychainHelper.accessTokenKey, value: response.accessToken)
            if let rt = response.refreshToken {
                await apiClient.setRefreshToken(rt)
                KeychainHelper.save(key: KeychainHelper.refreshTokenKey, value: rt)
            }
            magicLinkSent = false
            // A user arriving via magic link has effectively finished onboarding.
            if !hasCompletedOnboarding {
                UserDefaults.standard.set(true, forKey: AppState.onboardingCompletedKey)
                hasCompletedOnboarding = true
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

    /// Deterministic search results for DEBUG screenshot / UI-test runs so the
    /// search surface can be captured without a live backend. Mirrors
    /// `MacAppState.uiTestSearchResponse(query:)`.
    func uiTestSearchResponse(query: String) -> SearchResponse? {
        #if DEBUG
        guard IOSTestingMode.current.isScreenshot,
              !query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        else { return nil }
        return IOSScreenshotFixtures.searchResponse
        #else
        return nil
        #endif
    }
}
