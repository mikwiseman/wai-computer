import SwiftUI
import AVFoundation
import WaiSayKit
import Sparkle

extension Notification.Name {
    static let importAudioFile = Notification.Name("importAudioFile")
    static let showNewRecording = Notification.Name("showNewRecording")
    static let waisayIncomingURL = Notification.Name("waisayIncomingURL")
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
    private let updaterController = SPUStandardUpdaterController(startingUpdater: true, updaterDelegate: nil, userDriverDelegate: nil)

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
                    dictationManager.refreshPermissionState()
                    Task {
                        await appState.resumePendingRecordingSyncIfNeeded()
                    }
                }
                .onOpenURL { url in
                    Task { await appState.handleIncomingURL(url) }
                }
                .onReceive(
                    NotificationCenter.default.publisher(for: .waisayIncomingURL)
                ) { notification in
                    guard let url = notification.object as? URL else { return }
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
                // Opening Settings while recording swaps the detail column
                // and tears down the live recording view, killing the audio
                // task. Block the shortcut + menu item during recording so
                // users can't accidentally lose the take.
                .disabled(isRecordingActivityVisible)

                Divider()
                Button("Check for Updates…") {
                    updaterController.checkForUpdates(nil)
                }
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

    private let closeInterceptor = MainWindowCloseInterceptor()

    private init() {}

    func mainWindowDidAppear() {
        setRegularActivationPolicy()
        attachCloseInterceptorToMainWindow()
    }

    /// Find the SwiftUI-managed main NSWindow and route close attempts
    /// through `MainWindowCloseInterceptor`. When the "Show Dock icon after
    /// closing main window" toggle is ON the interceptor hides the window
    /// instead of letting it close — macOS hides the dock icon for any app
    /// without visible windows even with `.regular` policy, so we have to
    /// keep at least one window alive.
    private func attachCloseInterceptorToMainWindow() {
        guard let window = visibleMainWindows.first else { return }
        closeInterceptor.attach(to: window)
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

/// NSWindowDelegate proxy that intercepts the main window's close attempts.
/// When `showDockIconWhenMainWindowClosed` is enabled we hide the window via
/// `orderOut` instead of letting it actually close — this keeps the app in
/// the dock (macOS hides the dock icon for any windowless app even with
/// `.regular` activation policy).
///
/// Forwards every other delegate call to the original SwiftUI-managed
/// delegate so we don't break SwiftUI's own bookkeeping.
@MainActor
final class MainWindowCloseInterceptor: NSObject, NSWindowDelegate {
    private weak var attachedWindow: NSWindow?
    private weak var originalDelegate: NSWindowDelegate?

    func attach(to window: NSWindow) {
        guard attachedWindow !== window else { return }
        if let existing = window.delegate, !(existing is MainWindowCloseInterceptor) {
            originalDelegate = existing
        }
        window.delegate = self
        attachedWindow = window
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        if MacPresentationSettings.showDockIconWhenMainWindowClosed() {
            sender.orderOut(nil)
            return false
        }
        return originalDelegate?.windowShouldClose?(sender) ?? true
    }

    override func responds(to aSelector: Selector!) -> Bool {
        if super.responds(to: aSelector) { return true }
        return originalDelegate?.responds(to: aSelector) ?? false
    }

    override func forwardingTarget(for aSelector: Selector!) -> Any? {
        if let original = originalDelegate, original.responds(to: aSelector) {
            return original
        }
        return super.forwardingTarget(for: aSelector)
    }
}

@MainActor
final class WaiSayAppDelegate: NSObject, NSApplicationDelegate {
    func applicationWillFinishLaunching(_ notification: Notification) {
        // Run TCC legacy migration before SwiftUI mounts and before any
        // TCC-protected API is touched. If we end up resetting any stale
        // entries, relaunch — `CGRequestListenEventAccess` and
        // `CGRequestPostEventAccess` cache process-level "already asked"
        // state that survives `tccutil reset` and silently swallows the
        // next prompt. Relaunching gives the new process a clean slate so
        // onboarding's Grant clicks trigger fresh system dialogs.
        // Skipped under WAI_ENABLE_UI_TEST_MODE so test runs cannot
        // mutate the host machine's TCC database.
        let isUITestEnvironment = ProcessInfo.processInfo.environment["WAI_ENABLE_UI_TEST_MODE"] == "1"
        guard !isUITestEnvironment else { return }

        // Re-register the .app with LaunchServices on every launch. After
        // a Sparkle update macOS keeps the previous binary's `waisay://`
        // URL scheme handler cached, so magic-link clicks open the page
        // but the running app never receives the URL. Forcing a re-register
        // updates the bundle hash that LaunchServices routes to.
        reregisterWithLaunchServices()

        let microphoneGranted = AVCaptureDevice.authorizationStatus(for: .audio) == .authorized
        let needsRelaunch = MacInputPermission.performOneTimeLegacyTCCMigrationIfNeeded(
            microphoneGranted: microphoneGranted
        )
        if needsRelaunch {
            MacInputPermission.relaunchAfterTCCMigration()
        }
    }

    private func reregisterWithLaunchServices() {
        let bundleURL = Bundle.main.bundleURL
        let lsregister = "/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
        guard FileManager.default.isExecutableFile(atPath: lsregister) else { return }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: lsregister)
        process.arguments = ["-f", bundleURL.path]
        process.standardOutput = nil
        process.standardError = nil
        do {
            try process.run()
            process.waitUntilExit()
        } catch {
            NSLog("[AppLifecycle] lsregister failed: %@", "\(error)")
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        MacPresentationCoordinator.shared.mainWindowDidClose()
        return false
    }

    /// Canonical macOS URL handler — fires reliably for `waisay://` links
    /// even when the app is already running. SwiftUI's `.onOpenURL` modifier
    /// is unreliable for already-running apps (the scene receives the URL
    /// only on launch in some macOS releases). We forward to MacAppState via
    /// NotificationCenter so we don't need a global pointer to it.
    func application(_ application: NSApplication, open urls: [URL]) {
        for url in urls {
            NotificationCenter.default.post(
                name: .waisayIncomingURL,
                object: url
            )
        }
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if !flag {
            // Re-show the main window if it was hidden via orderOut(_:) by
            // MainWindowCloseInterceptor (toggle ON close path). If no
            // window is hidden, fall through and let SwiftUI open a new one.
            for window in NSApp.windows where window.title == "WaiSay" && !window.isVisible {
                window.makeKeyAndOrderFront(nil)
                NSApp.activate(ignoringOtherApps: true)
                MacPresentationCoordinator.shared.mainWindowDidAppear()
                return false
            }
            MacPresentationCoordinator.shared.mainWindowDidAppear()
        }
        return true
    }
}

enum MacLocalUserDataStore {
    static func removeWaiSaySupportDirectories(
        fileManager: FileManager = .default,
        bundleIdentifier: String? = Bundle.main.bundleIdentifier
    ) throws {
        try removeRelativeDirectories(
            in: .applicationSupportDirectory,
            relativePaths: [["WaiSay"]],
            fileManager: fileManager
        )

        var cachePaths = [["WaiSay"], ["SentryCrash", "WaiSay"]]
        if let bundleIdentifier, !bundleIdentifier.isEmpty {
            cachePaths.append([bundleIdentifier])
        }
        try removeRelativeDirectories(
            in: .cachesDirectory,
            relativePaths: cachePaths,
            fileManager: fileManager
        )
    }

    private static func removeRelativeDirectories(
        in searchPathDirectory: FileManager.SearchPathDirectory,
        relativePaths: [[String]],
        fileManager: FileManager
    ) throws {
        guard let base = fileManager.urls(for: searchPathDirectory, in: .userDomainMask).first else {
            return
        }

        for relativePath in relativePaths {
            let directory = relativePath.reduce(base) { url, component in
                url.appendingPathComponent(component, isDirectory: true)
            }
            guard fileManager.fileExists(atPath: directory.path) else {
                continue
            }
            try fileManager.removeItem(at: directory)
        }
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
    @Published var missingPermissions: Set<MissingPermission> = []
    /// Permission kinds the user has explicitly dismissed for this launch only.
    /// Re-armed on every `scenePhase == .active` so a real outage cannot be
    /// permanently silenced.
    @Published var dismissedPermissionBanners: Set<MissingPermission> = []
    private var permissionPollTimer: Timer?

    enum MissingPermission: Hashable {
        case microphone
        case accessibility
    }

    static let onboardingCompletedKey = "nativeOnboardingV3Completed"
    static let onboardingCurrentPageKey = "nativeOnboardingV3CurrentPage"
    static let legacyOnboardingCompletedKeys = ["nativeOnboardingV2Completed"]
    static let onboardingMicAcknowledgedKey = "onboardingMicAcknowledged"

    /// Recording view model — observed directly by recording views via @EnvironmentObject,
    /// NOT forwarded through MacAppState's objectWillChange. This prevents the entire
    /// view hierarchy from rebuilding on every timer tick and transcript update.
    let recordingViewModel: MacRecordingViewModel
    let dictationManager: DictationManager
    let testingMode: MacTestingMode

    private let apiClient: APIClient
    private var hasAttemptedStoredSessionRestore = false

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
        // The V3 key intentionally invalidates older completion flags because
        // permission onboarding now uses the unified Accessibility model.
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
                do {
                    try SessionStore.shared.save(
                        accessToken: accessToken,
                        refreshToken: refreshToken
                    )
                } catch {
                    SentryHelper.captureError(error, extras: ["action": "sessionSaveOnRefresh"])
                }
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

    /// Mark the current welcome and permission tour as seen.
    func completeOnboarding() {
        UserDefaults.standard.set(true, forKey: MacAppState.onboardingCompletedKey)
        UserDefaults.standard.removeObject(forKey: MacAppState.onboardingCurrentPageKey)
        MacAppState.legacyOnboardingCompletedKeys.forEach {
            UserDefaults.standard.removeObject(forKey: $0)
        }
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
        let envAccess = ProcessInfo.processInfo.environment["WAISAY_ACCESS_TOKEN"]
        let envRefresh = ProcessInfo.processInfo.environment["WAISAY_REFRESH_TOKEN"]

        let accessToken: String?
        let refreshToken: String?
        if let envAccess {
            try? SessionStore.shared.save(accessToken: envAccess, refreshToken: envRefresh)
            accessToken = envAccess
            refreshToken = envRefresh
        } else if let session = SessionStore.shared.load() {
            accessToken = session.accessToken
            refreshToken = envRefresh ?? session.refreshToken
            if let envRefresh, envRefresh != session.refreshToken {
                try? SessionStore.shared.save(accessToken: session.accessToken, refreshToken: envRefresh)
            }
        } else {
            accessToken = nil
            refreshToken = envRefresh
        }

        guard let accessToken else {
            isCheckingAuth = false
            return
        }

        Task {
            await apiClient.setAccessToken(accessToken)
            if let refreshToken {
                await apiClient.setRefreshToken(refreshToken)
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
            if let rt = response.refreshToken {
                await apiClient.setRefreshToken(rt)
            }
            persistSession(accessToken: response.accessToken, refreshToken: response.refreshToken)
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
            if let rt = response.refreshToken {
                await apiClient.setRefreshToken(rt)
            }
            persistSession(accessToken: response.accessToken, refreshToken: response.refreshToken)
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
            if let rt = response.refreshToken {
                await apiClient.setRefreshToken(rt)
            }
            persistSession(accessToken: response.accessToken, refreshToken: response.refreshToken)
            magicLinkSent = false
            await loadCurrentUser()
            if isAuthenticated && !hasCompletedOnboarding {
                UserDefaults.standard.set(
                    OnboardingPage.permission.rawValue,
                    forKey: MacAppState.onboardingCurrentPageKey
                )
            }
        } catch let apiError as APIError {
            handleAPIError(apiError)
        } catch {
            self.error = error.userFacingMessage(context: .authentication)
        }

        isLoading = false
    }

    func logout() async {
        if testingMode == .live {
            // Best-effort server logout with refresh token revocation.
            let rt = await apiClient.getRefreshToken()
            do {
                _ = try await apiClient.logout(refreshToken: rt)
            } catch {
                NSLog("[Auth] Server logout failed (proceeding with local logout)")
            }
        }

        await clearLocalSession(removeUserData: true)
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

        await clearLocalSession(removeUserData: true)
        return nil
    }

    private func persistSession(accessToken: String, refreshToken: String?) {
        do {
            try SessionStore.shared.save(accessToken: accessToken, refreshToken: refreshToken)
        } catch {
            SentryHelper.captureError(error, extras: ["action": "sessionSave"])
        }
    }

    private func clearLocalSession(removeUserData: Bool = false) async {
        dictationManager.disable()
        dictationManager.updateEnabled(false)
        await apiClient.setAccessToken(nil)
        await apiClient.setRefreshToken(nil)
        SessionStore.shared.clear()
        var cleanupFailure: String?

        if removeUserData {
            do {
                try clearLocalUserData()
            } catch {
                SentryHelper.captureError(error, extras: ["action": "clearLocalUserData"])
                cleanupFailure = "Signed out, but WaiSay could not remove all local app data. Quit WaiSay and remove its local data manually before sharing this Mac."
            }
        }

        SentryHelper.clearUser()
        currentUser = nil
        isAuthenticated = false
        magicLinkSent = false
        hasAttemptedStoredSessionRestore = false
        if removeUserData {
            UserDefaults.standard.removeObject(forKey: MacAppState.onboardingCompletedKey)
            UserDefaults.standard.removeObject(forKey: MacAppState.onboardingCurrentPageKey)
            UserDefaults.standard.removeObject(forKey: MacAppState.onboardingMicAcknowledgedKey)
            MacAppState.legacyOnboardingCompletedKeys.forEach {
                UserDefaults.standard.removeObject(forKey: $0)
            }
            hasCompletedOnboarding = false
        }
        error = cleanupFailure
    }

    private func clearLocalUserData() throws {
        dictationManager.historyStore?.clearAll()
        dictationManager.dictionaryStore?.clearAll()
        try RecordingBackupStore.removeAllRecordings()
        try MacLocalUserDataStore.removeWaiSaySupportDirectories()
        if let bundleIdentifier = Bundle.main.bundleIdentifier {
            UserDefaults.standard.removePersistentDomain(forName: bundleIdentifier)
        }
        UserDefaults.standard.synchronize()
    }

    /// Called when auto-refresh fails — transition to login screen
    private func handleAuthenticationFailed() {
        SessionStore.shared.clear()
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

    // MARK: - Permission tracking (Wispr Flow-style toast)

    /// Recompute which required permissions are missing. Drops banners that
    /// have been satisfied; re-arms previously dismissed banners only when
    /// scenePhase becomes active so users can't permanently silence one by
    /// accident.
    func refreshPermissionStatus(rearmDismissed: Bool = false) {
        if rearmDismissed {
            dismissedPermissionBanners.removeAll()
        }

        var missing: Set<MissingPermission> = []
        if AVCaptureDevice.authorizationStatus(for: .audio) != .authorized {
            missing.insert(.microphone)
        }
        if MacInputPermission.postEventStatus() != .granted {
            missing.insert(.accessibility)
        }

        if missing != missingPermissions {
            missingPermissions = missing
        }

        // Drive a polling timer only while the banner is visible — stop the
        // moment everything is granted to avoid waking on idle.
        if missing.subtracting(dismissedPermissionBanners).isEmpty {
            stopPermissionPolling()
        } else {
            startPermissionPollingIfNeeded()
        }
    }

    /// The single banner kind to show right now (microphone takes priority).
    var visiblePermissionBanner: MissingPermission? {
        let visible = missingPermissions.subtracting(dismissedPermissionBanners)
        if visible.contains(.microphone) { return .microphone }
        if visible.contains(.accessibility) { return .accessibility }
        return nil
    }

    func dismissPermissionBanner(_ kind: MissingPermission) {
        dismissedPermissionBanners.insert(kind)
    }

    /// Tap handler for the banner's primary action. Triggers the system prompt
    /// when possible, otherwise opens System Settings + reveals the .app in
    /// Finder so the user can drag it onto the "+" if WaiSay is missing from
    /// the list.
    func handlePermissionBannerTap(_ kind: MissingPermission) {
        switch kind {
        case .microphone:
            switch AVCaptureDevice.authorizationStatus(for: .audio) {
            case .notDetermined:
                Task {
                    _ = await AVAudioApplication.requestRecordPermission()
                    await MainActor.run { self.refreshPermissionStatus() }
                }
            default:
                MacInputPermission.revealAppInFinder()
                MacPrivacySettings.openMicrophone()
            }
        case .accessibility:
            // Trigger the canonical Accessibility prompt — Apple displays a
            // system dialog and registers the app in System Settings →
            // Privacy → Accessibility on first call. Reveal in Finder + open
            // Settings as a belt-and-suspenders fallback if the dialog has
            // already been dismissed in the past.
            _ = MacInputPermission.requestAccessibilityAccess()
            MacInputPermission.revealAppInFinder()
            MacPrivacySettings.openAccessibility()
        }
        startPermissionPolling()
    }

    private func startPermissionPollingIfNeeded() {
        guard permissionPollTimer == nil else { return }
        startPermissionPolling()
    }

    private func startPermissionPolling() {
        stopPermissionPolling()
        permissionPollTimer = Timer.scheduledTimer(withTimeInterval: 2.0, repeats: true) { [weak self] _ in
            DispatchQueue.main.async { self?.refreshPermissionStatus() }
        }
    }

    private func stopPermissionPolling() {
        permissionPollTimer?.invalidate()
        permissionPollTimer = nil
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
        if testingMode.isRecordingFlow {
            return MacUITestFixtures.recordingFlowRecordings
        }
        guard testingMode.isMainView else { return nil }
        return MacUITestFixtures.recordings
        #else
        return nil
        #endif
    }

    func uiTestRecordingDetail(id: String) async -> RecordingDetail? {
        #if DEBUG
        guard testingMode.isRecordingFlow || testingMode.isMainView else { return nil }

        try? await Task.sleep(for: .milliseconds(200))
        if testingMode.isRecordingFlow, id == MacUITestFixtures.completedRecording.id {
            return MacUITestFixtures.completedRecordingDetail
        }
        if id == MacUITestFixtures.recording.id {
            return MacUITestFixtures.recordingDetail
        }
        return nil
        #else
        return nil
        #endif
    }
}
