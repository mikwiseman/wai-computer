import SwiftUI
import WaiSayKit
#if SPARKLE
import Sparkle
#endif

extension Notification.Name {
    static let importAudioFile = Notification.Name("importAudioFile")
    static let showNewRecording = Notification.Name("showNewRecording")
}

@main
struct WaiSayMacApp: App {
    @NSApplicationDelegateAdaptor(WaiSayAppDelegate.self) private var appDelegate
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var recordingViewModel: MacRecordingViewModel
    @StateObject private var appState: MacAppState
    @StateObject private var dictationManager: DictationManager
    @StateObject private var historyStore: DictationHistoryStore
    @StateObject private var dictionaryStore: DictationDictionaryStore
    #if SPARKLE
    private let updaterController = SPUStandardUpdaterController(startingUpdater: true, updaterDelegate: nil, userDriverDelegate: nil)
    #endif

    init() {
        #if !DEBUG
        SentryHelper.start(dsn: "https://05638b94653e5d1bca3552d885d5dc4f@o4508963132145664.ingest.us.sentry.io/4511194363658240")
        #endif

        let testingMode = MacTestingMode.current
        let recordingViewModel = MacRecordingViewModel(testingMode: testingMode)
        let dictation = DictationManager()
        let history = DictationHistoryStore()
        let dictionary = DictationDictionaryStore()
        dictation.historyStore = history
        dictation.dictionaryStore = dictionary

        _recordingViewModel = StateObject(wrappedValue: recordingViewModel)
        _dictationManager = StateObject(wrappedValue: dictation)
        _historyStore = StateObject(wrappedValue: history)
        _dictionaryStore = StateObject(wrappedValue: dictionary)
        _appState = StateObject(
            wrappedValue: MacAppState(
                recordingViewModel: recordingViewModel,
                dictationManager: dictation,
                testingMode: testingMode
            )
        )
    }

    var body: some Scene {
        WindowGroup("WaiSay", id: MacPresentationCoordinator.mainWindowID) {
            MacContentView()
                .environmentObject(appState)
                .environmentObject(recordingViewModel)
                .environmentObject(dictationManager)
                .environmentObject(historyStore)
                .environmentObject(dictionaryStore)
                .onAppear {
                    MacPresentationCoordinator.shared.mainWindowDidAppear()
                }
                .onChange(of: scenePhase) { _, newPhase in
                    guard newPhase == .active else { return }
                    Task {
                        await appState.resumePendingRecordingSyncIfNeeded()
                    }
                }
                .onOpenURL { url in
                    Task { await appState.handleIncomingURL(url) }
                }
                .handlesExternalEvents(preferring: Set(["main"]), allowing: Set(["main"]))
        }
        .handlesExternalEvents(matching: Set(["main"]))
        .windowStyle(.hiddenTitleBar)
        .defaultSize(width: 1200, height: 800)
        .commands {
            // Replace default Cmd+N (new window) with recording commands
            CommandGroup(replacing: .newItem) {
                Button("New Recording") {
                    NotificationCenter.default.post(name: .showNewRecording, object: nil)
                }
                .keyboardShortcut("n", modifiers: .command)
                .disabled(isRecordingActivityVisible || !appState.isAuthenticated)

                Divider()

                Button("Record Mic + System Audio") {
                    Task { await appState.startRecording(type: .note, inputSource: .dual) }
                }
                .keyboardShortcut("r", modifiers: .command)
                .disabled(isRecordingActivityVisible || !appState.isAuthenticated)

                Button("Record Mic Only") {
                    Task { await appState.startRecording(type: .note, inputSource: .microphone) }
                }
                .keyboardShortcut("r", modifiers: [.command, .shift])
                .disabled(isRecordingActivityVisible || !appState.isAuthenticated)

                Divider()

                Button("Import Audio File") {
                    NotificationCenter.default.post(name: .importAudioFile, object: nil)
                }
                .keyboardShortcut("i", modifiers: .command)
                .disabled(isRecordingActivityVisible || !appState.isAuthenticated)
            }

            // Settings (Cmd+,)
            CommandGroup(replacing: .appSettings) {
                Button("Settings…") {
                    NotificationCenter.default.post(name: .init("navigateToSettings"), object: nil)
                }
                .keyboardShortcut(",", modifiers: .command)

                #if SPARKLE
                Divider()
                Button("Check for Updates…") {
                    updaterController.checkForUpdates(nil)
                }
                #endif
            }

            // View menu — sidebar navigation
            CommandMenu("View") {
                Button("All Recordings") {
                    NotificationCenter.default.post(name: .init("navigateTo"), object: "allRecordings")
                }
                .keyboardShortcut("1", modifiers: .command)

                Button("History") {
                    NotificationCenter.default.post(name: .init("navigateTo"), object: "history")
                }
                .keyboardShortcut("2", modifiers: .command)

                Button("Dictionary") {
                    NotificationCenter.default.post(name: .init("navigateTo"), object: "dictionary")
                }
                .keyboardShortcut("3", modifiers: .command)

                Button("Settings") {
                    NotificationCenter.default.post(name: .init("navigateToSettings"), object: nil)
                }
                .keyboardShortcut("4", modifiers: .command)

                Divider()

                Button("Trash") {
                    NotificationCenter.default.post(name: .init("navigateTo"), object: "trash")
                }
                .keyboardShortcut("5", modifiers: .command)
            }

            // Remove the default "New Window" from the Window menu
            CommandGroup(replacing: .windowList) {}
        }

        // Menu bar extra
        MenuBarExtra("WaiSay", systemImage: isRecordingActivityVisible ? "waveform.circle.fill" : "brain.head.profile") {
            MenuBarView()
                .environmentObject(appState)
                .environmentObject(recordingViewModel)
                .environmentObject(dictationManager)
        }
        .menuBarExtraStyle(.window)
    }

    private var isRecordingActivityVisible: Bool {
        recordingViewModel.shouldPresentLiveView || appState.completedRecordingContext != nil
    }
}

enum MacPresentationSettings {
    static let showDockIconWhenMainWindowClosedKey = "showDockIconWhenMainWindowClosed"

    static func showDockIconWhenMainWindowClosed(in defaults: UserDefaults = .standard) -> Bool {
        defaults.bool(forKey: showDockIconWhenMainWindowClosedKey)
    }
}

enum MacMainWindowAction: Equatable {
    case importAudioFile
    case settings
}

@MainActor
final class MacPresentationCoordinator {
    static let shared = MacPresentationCoordinator()
    static let mainWindowID = "main"

    private init() {}

    func mainWindowDidAppear() {
        setRegularActivationPolicy()
    }

    func mainWindowDidClose() {
        guard !MacPresentationSettings.showDockIconWhenMainWindowClosed() else {
            setRegularActivationPolicy()
            return
        }

        setActivationPolicy(.accessory)
    }

    func updateActivationPolicyForCurrentWindowState() {
        if hasVisibleMainWindow || MacPresentationSettings.showDockIconWhenMainWindowClosed() {
            setRegularActivationPolicy()
        } else {
            setActivationPolicy(.accessory)
        }
    }

    func showMainWindow(openMainWindow: () -> Void) {
        setRegularActivationPolicy()

        if let window = visibleMainWindows.first {
            if window.isMiniaturized {
                window.deminiaturize(nil)
            }
            window.makeKeyAndOrderFront(nil)
        } else {
            openMainWindow()
        }

        NSApp.activate(ignoringOtherApps: true)
    }

    private var hasVisibleMainWindow: Bool {
        !visibleMainWindows.isEmpty
    }

    private var visibleMainWindows: [NSWindow] {
        NSApp.windows.filter { window in
            window.isVisible &&
                window.canBecomeMain &&
                window.level == .normal &&
                !window.isExcludedFromWindowsMenu &&
                window.title == "WaiSay"
        }
    }

    private func setRegularActivationPolicy() {
        guard NSApp.activationPolicy() != .regular else { return }
        setActivationPolicy(.regular)
    }

    private func setActivationPolicy(_ policy: NSApplication.ActivationPolicy) {
        guard !NSApp.setActivationPolicy(policy) else { return }
        NSLog("[AppLifecycle] Failed to set activation policy %@", activationPolicyName(policy))
    }

    private func activationPolicyName(_ policy: NSApplication.ActivationPolicy) -> String {
        switch policy {
        case .regular:
            return "regular"
        case .accessory:
            return "accessory"
        case .prohibited:
            return "prohibited"
        @unknown default:
            return "unknown"
        }
    }
}

@MainActor
final class WaiSayAppDelegate: NSObject, NSApplicationDelegate {
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        MacPresentationCoordinator.shared.mainWindowDidClose()
        return false
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if !flag {
            MacPresentationCoordinator.shared.mainWindowDidAppear()
        }
        return true
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
    @Published var completedRecordingContext: CompletedRecordingContext?
    @Published var selectedRecordingFromMenu: String?
    @Published var pendingMainWindowAction: MacMainWindowAction?
    @Published var hasCompletedOnboarding: Bool = false

    static let onboardingCompletedKey = "hasCompletedOnboarding"
    static let onboardingMicAcknowledgedKey = "onboardingMicAcknowledged"

    /// Recording view model — observed directly by recording views via @EnvironmentObject,
    /// NOT forwarded through MacAppState's objectWillChange. This prevents the entire
    /// view hierarchy from rebuilding on every timer tick and transcript update.
    let recordingViewModel: MacRecordingViewModel
    let dictationManager: DictationManager
    let testingMode: MacTestingMode

    private let apiClient: APIClient

    init(
        recordingViewModel: MacRecordingViewModel,
        dictationManager: DictationManager,
        testingMode: MacTestingMode = .current
    ) {
        self.recordingViewModel = recordingViewModel
        self.dictationManager = dictationManager
        self.testingMode = testingMode

        let baseURL = URL(string: "https://say.waiwai.is")!
        apiClient = APIClient(baseURL: baseURL)

        // Resolve onboarding flag honoring env-var overrides used by tests/dev.
        let env = ProcessInfo.processInfo.environment
        if env["WAI_FORCE_ONBOARDING"] == "1" {
            UserDefaults.standard.set(false, forKey: MacAppState.onboardingCompletedKey)
            hasCompletedOnboarding = false
        } else if env["WAI_SKIP_ONBOARDING"] == "1" {
            UserDefaults.standard.set(true, forKey: MacAppState.onboardingCompletedKey)
            hasCompletedOnboarding = true
        } else {
            hasCompletedOnboarding = UserDefaults.standard.bool(forKey: MacAppState.onboardingCompletedKey)
        }

        #if DEBUG
        if testingMode.isRecordingFlow || testingMode.isMainView {
            currentUser = MacUITestFixtures.user
            isAuthenticated = true
            isCheckingAuth = false
            hasCompletedOnboarding = true
            return
        }
        if testingMode.isAuthFlow {
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

        // Restore tokens from Keychain (or environment for screenshots)
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

        if let accessToken {
            Task {
                await apiClient.setAccessToken(accessToken)
                let rt = refreshOverride ?? KeychainHelper.load(key: KeychainHelper.refreshTokenKey)
                if let rt {
                    await apiClient.setRefreshToken(rt)
                }
                await loadCurrentUser()
                // Returning user with valid tokens — they've already conceptually
                // onboarded, even if UserDefaults was wiped (clean install with
                // Keychain restored). Skip the welcome tour.
                if isAuthenticated && !hasCompletedOnboarding {
                    completeOnboarding()
                }
                isCheckingAuth = false
            }
        } else {
            isCheckingAuth = false
        }
    }

    /// Mark the welcome tour as seen. The flag persists across logout and
    /// account deletion — onboarding is a product introduction, not part of
    /// the auth lifecycle.
    func completeOnboarding() {
        UserDefaults.standard.set(true, forKey: MacAppState.onboardingCompletedKey)
        hasCompletedOnboarding = true
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

    func requestMagicLink(email: String) async {
        isLoading = true
        error = nil

        do {
            _ = try await apiClient.requestMagicLink(email: email, client: "macos")
            magicLinkSent = true
        } catch let apiError as APIError {
            handleAPIError(apiError)
        } catch {
            self.error = error.userFacingMessage(context: .authentication)
        }

        isLoading = false
    }

    func handleIncomingURL(_ url: URL) async {
        guard url.scheme == "waisay",
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
            await loadCurrentUser()
            // External-trigger auth (deep link from email) can land mid-onboarding.
            // Don't trap an authenticated user behind the welcome tour.
            if isAuthenticated && !hasCompletedOnboarding {
                completeOnboarding()
            }
        } catch let apiError as APIError {
            handleAPIError(apiError)
        } catch {
            self.error = error.userFacingMessage(context: .authentication)
        }

        isLoading = false
    }

    func logout() async {
        // Best-effort server logout with refresh token revocation
        let rt = await apiClient.getRefreshToken()
        do {
            _ = try await apiClient.logout(refreshToken: rt)
        } catch {
            NSLog("[Auth] Server logout failed (proceeding with local logout)")
        }

        await clearLocalSession()
    }

    /// Permanently delete the signed-in account. Returns an error message on
    /// failure; on success tokens + user context are cleared and the app
    /// routes back to the auth screen.
    func deleteAccount() async -> String? {
        guard isAuthenticated else { return nil }

        do {
            _ = try await apiClient.deleteAccount()
        } catch {
            SentryHelper.captureError(error, extras: ["action": "deleteAccount"])
            return error.userFacingMessage(context: .authentication)
        }

        await clearLocalSession()
        return nil
    }

    private func clearLocalSession() async {
        dictationManager.disable()
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
        dictationManager.disable()
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
            dictationManager.configure(apiClient: apiClient) { [weak recordingViewModel] in
                recordingViewModel?.phase == .idle
            }
        } catch {
            isAuthenticated = false
            currentUser = nil
            SentryHelper.clearUser()
            dictationManager.disable()
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

    func startRecording(
        type: RecordingType,
        inputSource: MacRecordingInputSource = .dual
    ) async {
        completedRecordingContext = nil
        if dictationManager.state != .idle {
            await dictationManager.cancelDictation()
        }

        await recordingViewModel.startRecording(
            apiClient: apiClient,
            type: type,
            inputSource: inputSource
        )
    }

    func stopRecording() async {
        if completedRecordingContext == nil,
           let recordingId = recordingViewModel.currentRecordingId {
            completedRecordingContext = CompletedRecordingContext(
                recordingId: recordingId,
                transcript: recordingViewModel.currentTranscript,
                duration: recordingViewModel.duration,
                recordingType: recordingViewModel.recordingType
            )
        }

        await recordingViewModel.stopRecording()
    }

    func finishCompletedRecordingTransition(recordingId: String) {
        guard completedRecordingContext?.recordingId == recordingId else { return }

        recordingViewModel.resetState()
        completedRecordingContext = nil
    }

    func getAPIClient() -> APIClient {
        return apiClient
    }

    func uiTestRecordings() -> [Recording]? {
        #if DEBUG
        guard testingMode.isRecordingFlow || testingMode.isMainView else { return nil }
        return MacUITestFixtures.recordings
        #else
        return nil
        #endif
    }

    func uiTestRecordingDetail(id: String) async -> RecordingDetail? {
        #if DEBUG
        guard testingMode.isRecordingFlow || testingMode.isMainView,
              id == MacUITestFixtures.recording.id else { return nil }

        try? await Task.sleep(for: .milliseconds(200))
        return MacUITestFixtures.recordingDetail
        #else
        return nil
        #endif
    }
}
