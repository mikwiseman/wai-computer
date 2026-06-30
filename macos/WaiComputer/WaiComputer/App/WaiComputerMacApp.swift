import SwiftUI
import AVFoundation
import WaiComputerKit
import Sparkle

extension Notification.Name {
    static let importAudioFile = Notification.Name("importAudioFile")
    static let showNewRecording = Notification.Name("showNewRecording")
    static let macInboxCommand = Notification.Name("macInboxCommand")
    static let macCreateFolder = Notification.Name("macCreateFolder")
    static let macOpenWaiChat = Notification.Name("macOpenWaiChat")
    static let waicomputerIncomingURL = Notification.Name("waicomputerIncomingURL")
    static let waicomputerCheckForUpdates = Notification.Name("waicomputerCheckForUpdates")
}

enum MacInboxCommand: String, Equatable {
    case contextualNew
    case showCreatePane
    case recordNow
    case uploadFile
}

@main
struct WaiComputerMacApp: App {
    @NSApplicationDelegateAdaptor(WaiComputerAppDelegate.self) private var appDelegate
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var recordingViewModel: MacRecordingViewModel
    @StateObject private var appState: MacAppState
    @StateObject private var dictationManager: DictationManager
    @StateObject private var historyStore: DictationHistoryStore
    @StateObject private var dictionaryStore: DictationDictionaryStore
    @StateObject private var languageStore: DictationLanguageStore
    @StateObject private var learningEngine: DictionaryLearningEngine
    @AppStorage(BetaChannelStore.userDefaultsKey) private var receiveBetaUpdates = false
    @AppStorage(MacThemePreferences.appearanceKey) private var appearanceModeRawValue = MacThemePreferences.defaultAppearance.rawValue
    @AppStorage(MacThemePreferences.accentKey) private var accentChoiceRawValue = MacThemePreferences.defaultAccent.rawValue
    // Sparkle weakly references delegates, so keep this instance alive for the app lifetime.
    private let updaterDelegate: BetaChannelUpdaterDelegate?
    private let updateUserDriverDelegate: RecordingAwareUpdateUserDriverDelegate?
    private let updaterController: SPUStandardUpdaterController?

    init() {
        #if !DEBUG
        SentryHelper.start(dsn: "https://7d4dee467b0776baf21d5833aa953caa@o4508963132145664.ingest.us.sentry.io/4511116051939328")
        #endif

        let testingMode = MacTestingMode.current
        #if DEBUG
        testingMode.prepareProcessForUITesting()
        #endif
        let recordingViewModel = MacRecordingViewModel(testingMode: testingMode)
        let dictation = DictationManager()
        let history = DictationHistoryStore()
        let dictionary = DictationDictionaryStore()
        let languages = DictationLanguageStore()
        dictation.historyStore = history
        dictation.dictionaryStore = dictionary
        dictation.languageStore = languages
        dictionary.onRealtimeHintsChanged = { [weak dictation] reason in
            dictation?.prefetchSessionConfigForCurrentLanguage(reason: reason)
        }
        let learningEngine = DictionaryLearningEngine(lexicon: MacLexiconChecker())
        let editWatcher = DictationEditWatcher(engine: learningEngine)
        dictation.learningEngine = learningEngine
        dictation.editWatcher = editWatcher
        let appState = MacAppState(
            recordingViewModel: recordingViewModel,
            dictationManager: dictation,
            testingMode: testingMode
        )

        #if DEBUG
        updaterDelegate = nil
        updateUserDriverDelegate = nil
        updaterController = nil
        #else
        let updaterDelegate = BetaChannelUpdaterDelegate()
        let updateUserDriverDelegate = RecordingAwareUpdateUserDriverDelegate {
            recordingViewModel.shouldPresentLiveView || appState.completedRecordingContext != nil
        }
        self.updaterDelegate = updaterDelegate
        self.updateUserDriverDelegate = updateUserDriverDelegate
        updaterController = SPUStandardUpdaterController(
            startingUpdater: true,
            updaterDelegate: updaterDelegate,
            userDriverDelegate: updateUserDriverDelegate
        )
        #endif

        _recordingViewModel = StateObject(wrappedValue: recordingViewModel)
        _dictationManager = StateObject(wrappedValue: dictation)
        _historyStore = StateObject(wrappedValue: history)
        _dictionaryStore = StateObject(wrappedValue: dictionary)
        _languageStore = StateObject(wrappedValue: languages)
        _learningEngine = StateObject(wrappedValue: learningEngine)
        _appState = StateObject(wrappedValue: appState)
    }

    @StateObject private var languageManager = LanguageManager.shared

    private var selectedAppearanceMode: MacAppearanceMode {
        MacAppearanceMode(rawValue: appearanceModeRawValue) ?? MacThemePreferences.defaultAppearance
    }

    private var selectedAccentChoice: MacAccentChoice {
        MacAccentChoice(rawValue: accentChoiceRawValue) ?? MacThemePreferences.defaultAccent
    }

    var body: some Scene {
        WindowGroup("WaiComputer", id: MacPresentationCoordinator.mainWindowID) {
            MacContentView()
                .environment(\.locale, languageManager.preferredLocale)
                .environmentObject(languageManager)
                .environmentObject(appState)
                .environmentObject(recordingViewModel)
                .environmentObject(dictationManager)
                .environmentObject(historyStore)
                .environmentObject(dictionaryStore)
                .environmentObject(languageStore)
                .environmentObject(learningEngine)
                .preferredColorScheme(selectedAppearanceMode.preferredColorScheme)
                .tint(selectedAccentChoice.tintColor)
                .onAppear {
                    MacPresentationCoordinator.shared.mainWindowDidAppear()
                }
                .onChangeCompat(of: receiveBetaUpdates) { _, _ in
                    updaterController?.updater.resetUpdateCycle()
                }
                .onChangeCompat(of: isRecordingActivityVisible) { _, isActive in
                    guard !isActive else { return }
                    updateUserDriverDelegate?.presentDeferredUpdateIfIdle(using: updaterController)
                }
                .onChangeCompat(of: scenePhase) { _, newPhase in
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
                    NotificationCenter.default.publisher(for: .waicomputerIncomingURL)
                ) { notification in
                    guard let url = notification.object as? URL else { return }
                    Task { await appState.handleIncomingURL(url) }
                }
                .onReceive(
                    NotificationCenter.default.publisher(for: .waicomputerCheckForUpdates)
                ) { _ in
                    if isRecordingActivityVisible {
                        updateUserDriverDelegate?.deferUpdateCheckUntilIdle()
                    } else {
                        updaterController?.checkForUpdates(nil)
                    }
                }
                .handlesExternalEvents(preferring: Set(["main"]), allowing: Set(["main"]))
        }
        .handlesExternalEvents(matching: Set(["main"]))
        .windowStyle(.hiddenTitleBar)
        .defaultSize(width: 1200, height: 800)
        .commands {
            // Replace default Cmd+N (new window) with Inbox-first creation commands.
            CommandGroup(replacing: .newItem) {
                if recordingViewModel.shouldPresentLiveView {
                    Button(recordingViewModel.canResumeRecording ? t("Resume Recording", "Продолжить запись") : t("Pause Recording", "Пауза")) {
                        Task {
                            if recordingViewModel.canResumeRecording {
                                await appState.resumeRecording()
                            } else {
                                await appState.pauseRecording()
                            }
                        }
                    }
                    .keyboardShortcut("p", modifiers: [.command, .shift])
                    .disabled(!recordingViewModel.canPauseRecording && !recordingViewModel.canResumeRecording)

                    Button(t("Stop Recording", "Остановить запись")) {
                        Task { await appState.stopRecording() }
                    }
                    .keyboardShortcut(".", modifiers: .command)
                    .disabled(!recordingViewModel.canStopRecording)

                    Divider()
                }

                Button(t("New Inbox Item", "Новый объект в Инбоксе")) {
                    postInboxCommand(.contextualNew)
                }
                .keyboardShortcut("n", modifiers: .command)
                .disabled(isRecordingActivityVisible || !appState.isAuthenticated)

                Button(t("New Folder", "Новая папка")) {
                    NotificationCenter.default.post(name: .macCreateFolder, object: nil)
                }
                .keyboardShortcut("n", modifiers: [.command, .shift])
                .disabled(isRecordingActivityVisible || !appState.isAuthenticated)

                Divider()

                Button(t("Record Now", "Записать сейчас")) {
                    postInboxCommand(.recordNow)
                }
                .keyboardShortcut("r", modifiers: [.command, .shift])
                .disabled(isRecordingActivityVisible || !appState.isAuthenticated)

                Button(t("Upload File", "Загрузить файл")) {
                    postInboxCommand(.uploadFile)
                }
                .keyboardShortcut("u", modifiers: [.command, .option])
                .disabled(isRecordingActivityVisible || !appState.isAuthenticated)

                Button("Wai") {
                    postNavigationTarget("wai")
                }
                .keyboardShortcut("a", modifiers: [.command, .option])
                .disabled(isRecordingActivityVisible || !appState.isAuthenticated)
            }

            // Settings (Cmd+,)
            CommandGroup(replacing: .appSettings) {
                Button(t("Settings…", "Настройки…")) {
                    NotificationCenter.default.post(name: .init("navigateToSettings"), object: nil)
                }
                .keyboardShortcut(",", modifiers: .command)
                // Opening Settings while recording swaps the detail column
                // and tears down the live recording view, killing the audio
                // task. Block the shortcut + menu item during recording so
                // users can't accidentally lose the take.
                .disabled(isRecordingActivityVisible)

                Divider()
                #if !DEBUG
                Button(t("Check for Updates…", "Проверить обновления…")) {
                    updaterController?.checkForUpdates(nil)
                }
                .disabled(isRecordingActivityVisible)
                #endif
            }

            CommandMenu(t("Navigate", "Переход")) {
                Button(t("Inbox", "Инбокс")) {
                    NotificationCenter.default.post(name: .init("navigateTo"), object: "inbox")
                }
                .keyboardShortcut("1", modifiers: .command)

                Button(t("Trash", "Корзина")) {
                    NotificationCenter.default.post(name: .init("navigateTo"), object: "trash")
                }
                .keyboardShortcut("2", modifiers: .command)

                Button(t("History", "История")) {
                    NotificationCenter.default.post(name: .init("navigateTo"), object: "history")
                }
                .keyboardShortcut("3", modifiers: .command)

                Button(t("Dictionary", "Словарь")) {
                    NotificationCenter.default.post(name: .init("navigateTo"), object: "dictionary")
                }
                .keyboardShortcut("4", modifiers: .command)

                Divider()

                Button(t("Search", "Поиск")) {
                    NotificationCenter.default.post(name: .init("navigateTo"), object: "search")
                }
                .keyboardShortcut("f", modifiers: .command)

                Button("Wai") {
                    NotificationCenter.default.post(name: .init("navigateTo"), object: "wai")
                }
            }

            MacSelectionCommands()

            // Remove the default "New Window" from the Window menu
            CommandGroup(replacing: .windowList) {}
        }

        // Menu bar extra — BrandIconMenuBar is a 22pt template asset, so SwiftUI
        // sizes it correctly inside the menu bar without explicit frame modifiers.
        // While recording, swap to a filled waveform symbol as a visual "active" cue.
        MenuBarExtra {
            MenuBarView()
                .environmentObject(appState)
                .environmentObject(recordingViewModel)
                .environmentObject(dictationManager)
                .environmentObject(historyStore)
                .environmentObject(languageManager)
                .preferredColorScheme(selectedAppearanceMode.preferredColorScheme)
                .tint(selectedAccentChoice.tintColor)
        } label: {
            if isRecordingActivityVisible {
                Image(systemName: "waveform.circle.fill")
            } else {
                Image("BrandIconMenuBar")
            }
        }
        .menuBarExtraStyle(.window)
    }

    private var isRecordingActivityVisible: Bool {
        recordingViewModel.shouldPresentLiveView || appState.completedRecordingContext != nil
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }

    private func postInboxCommand(_ command: MacInboxCommand) {
        NotificationCenter.default.post(name: .macInboxCommand, object: command.rawValue)
    }

    private func postNavigationTarget(_ target: String) {
        NotificationCenter.default.post(name: .init("navigateTo"), object: target)
    }
}

enum MacPresentationSettings {
    static let showDockIconWhenMainWindowClosedKey = "showDockIconWhenMainWindowClosed"

    static func showDockIconWhenMainWindowClosed(in defaults: UserDefaults = .standard) -> Bool {
        defaults.bool(forKey: showDockIconWhenMainWindowClosedKey)
    }
}

enum MacMainWindowAction: Equatable {
    case inboxCommand(MacInboxCommand)
    case settings
}

@MainActor
final class MacPresentationCoordinator {
    static let shared = MacPresentationCoordinator()
    static let mainWindowID = "main"

    private let closeInterceptor = MainWindowCloseInterceptor()
    private var didPlaceMainWindowThisLaunch = false

    private init() {}

    func mainWindowDidAppear() {
        setRegularActivationPolicy()
        attachCloseInterceptorToMainWindow()
        #if DEBUG
        if placeMainWindowForUITestingIfNeeded() {
            return
        }
        #endif
        centerMainWindowIfNeeded()
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

    private func centerMainWindowIfNeeded() {
        guard !didPlaceMainWindowThisLaunch,
              let window = visibleMainWindows.first,
              let screen = window.screen ?? NSScreen.main
        else { return }

        let visibleFrame = screen.visibleFrame
        if window.frame.maxY >= visibleFrame.maxY - 4 {
            window.center()
        }
        didPlaceMainWindowThisLaunch = true
    }

    #if DEBUG
    private func placeMainWindowForUITestingIfNeeded() -> Bool {
        guard !didPlaceMainWindowThisLaunch else { return true }

        let env = ProcessInfo.processInfo.environment
        guard env["WAI_ENABLE_UI_TEST_MODE"] == "1" else { return false }

        let keys = [
            "WAICOMPUTER_TEST_WINDOW_X",
            "WAICOMPUTER_TEST_WINDOW_Y",
            "WAICOMPUTER_TEST_WINDOW_WIDTH",
            "WAICOMPUTER_TEST_WINDOW_HEIGHT",
        ]
        let rawValues = keys.map { env[$0] }
        guard rawValues.contains(where: { $0 != nil }) else { return false }
        guard rawValues.allSatisfy({ $0 != nil }) else {
            preconditionFailure("Incomplete UI test window bounds environment")
        }
        guard
            let x = Double(rawValues[0]!),
            let y = Double(rawValues[1]!),
            let width = Double(rawValues[2]!),
            let height = Double(rawValues[3]!),
            width > 0,
            height > 0,
            let window = visibleMainWindows.first
        else {
            preconditionFailure("Invalid UI test window bounds environment")
        }

        window.setFrame(NSRect(x: x, y: y, width: width, height: height), display: false)
        didPlaceMainWindowThisLaunch = true
        return true
    }
    #endif

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
                window.title == "WaiComputer"
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

    func windowWillClose(_ notification: Notification) {
        if let window = notification.object as? NSWindow, window === attachedWindow {
            MacPresentationCoordinator.shared.mainWindowDidClose()
        }
        originalDelegate?.windowWillClose?(notification)
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
final class WaiComputerAppDelegate: NSObject, NSApplicationDelegate {
    func applicationWillFinishLaunching(_ notification: Notification) {
        MacWaiTaskNotificationCenter.shared.configure()

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
        // a Sparkle update macOS keeps the previous binary's `waicomputer://`
        // URL scheme handler cached, so magic-link clicks open the page
        // but the running app never receives the URL. Forcing a re-register
        // updates the bundle hash that LaunchServices routes to.
        reregisterWithLaunchServices()

        let microphoneGranted = AVCaptureDevice.authorizationStatus(for: .audio) == .authorized
        let needsRelaunch = MacInputPermission.performOneTimeLegacyTCCMigrationIfNeeded(
            microphoneGranted: microphoneGranted
        )

        // Sweep up ghost "WaiSay.app" rows in System Settings → Privacy &
        // Security left over from the is.waiwai.say → is.waiwai.computer
        // rebrand. These never grant permission to the new binary (different
        // bundle ID + designated requirement), they just confuse the user
        // into thinking permission is already granted.
        MacInputPermission.cleanupLegacyWaiSayTCCIfNeeded()

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

    /// Canonical macOS URL handler — fires reliably for `waicomputer://` links
    /// even when the app is already running. SwiftUI's `.onOpenURL` modifier
    /// is unreliable for already-running apps (the scene receives the URL
    /// only on launch in some macOS releases). We forward to MacAppState via
    /// NotificationCenter so we don't need a global pointer to it.
    func application(_ application: NSApplication, open urls: [URL]) {
        for url in urls {
            NotificationCenter.default.post(
                name: .waicomputerIncomingURL,
                object: url
            )
        }
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if !flag {
            // Re-show the main window if it was hidden via orderOut(_:) by
            // MainWindowCloseInterceptor (toggle ON close path). If no
            // window is hidden, fall through and let SwiftUI open a new one.
            for window in NSApp.windows where window.title == "WaiComputer" && !window.isVisible {
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
    static func removeWaiComputerSupportDirectories(
        fileManager: FileManager = .default,
        bundleIdentifier: String? = Bundle.main.bundleIdentifier
    ) throws {
        try removeRelativeDirectories(
            in: .applicationSupportDirectory,
            relativePaths: [["WaiComputer"]],
            fileManager: fileManager
        )

        var cachePaths = [["WaiComputer"], ["SentryCrash", "WaiComputer"]]
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
    @Published var passwordResetSent = false
    @Published var completedRecordingContext: CompletedRecordingContext?
    @Published var selectedRecordingFromMenu: String?
    @Published var pendingMainWindowAction: MacMainWindowAction?
    @Published var hasCompletedPreAuthOnboarding: Bool = false
    @Published var hasCompletedPostAuthOnboarding: Bool = false
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

    nonisolated static let onboardingCompletedKey = MacOnboardingDefaultsSnapshot.onboardingCompletedKey
    nonisolated static let onboardingCurrentPageKey = MacOnboardingDefaultsSnapshot.onboardingCurrentPageKey
    nonisolated static let preAuthOnboardingCompletedKey = MacOnboardingDefaultsSnapshot.preAuthOnboardingCompletedKey
    nonisolated static let preAuthOnboardingCurrentPageKey = MacOnboardingDefaultsSnapshot.preAuthOnboardingCurrentPageKey
    nonisolated static let postAuthOnboardingCurrentPageKey = MacOnboardingDefaultsSnapshot.postAuthOnboardingCurrentPageKey
    nonisolated static let legacyOnboardingCompletedKeys = MacOnboardingDefaultsSnapshot.legacyOnboardingCompletedKeys
    nonisolated static let onboardingMicAcknowledgedKey = MacOnboardingDefaultsSnapshot.onboardingMicAcknowledgedKey
    nonisolated static let onboardingSystemAudioSetupKey = MacOnboardingDefaultsSnapshot.onboardingSystemAudioSetupKey

    /// Recording view model — observed directly by recording views via @EnvironmentObject,
    /// NOT forwarded through MacAppState's objectWillChange. This prevents the entire
    /// view hierarchy from rebuilding on every timer tick and transcript update.
    let recordingViewModel: MacRecordingViewModel
    let dictationManager: DictationManager
    let testingMode: MacTestingMode
    let serviceBaseURL: URL

    private let apiClient: APIClient
    private var hasAttemptedStoredSessionRestore = false
    private var pendingRecordingSyncObserver: NSObjectProtocol?

    init(
        recordingViewModel: MacRecordingViewModel,
        dictationManager: DictationManager,
        testingMode: MacTestingMode = .current
    ) {
        self.recordingViewModel = recordingViewModel
        self.dictationManager = dictationManager
        self.testingMode = testingMode

        // Allow dev/test overrides via env var so we can point the app at a
        // local backend during E2E testing without touching the binary.
        let baseURL: URL
        if let override = ProcessInfo.processInfo.environment["WAI_API_BASE_URL"],
           let overrideURL = URL(string: override) {
            baseURL = overrideURL
        } else {
            baseURL = URL(string: "https://wai.computer")!
        }
        serviceBaseURL = baseURL
        apiClient = APIClient(baseURL: baseURL)

        // Resolve onboarding flags honoring env-var overrides used by tests/dev.
        // V5 splits local first-run setup before auth from API-backed voice
        // setup after auth.
        let env = ProcessInfo.processInfo.environment
        if env["WAI_FORCE_ONBOARDING"] == "1" {
            UserDefaults.standard.set(false, forKey: MacAppState.preAuthOnboardingCompletedKey)
            if !Self.hasExplicitOnboardingCurrentPageArgument {
                UserDefaults.standard.removeObject(forKey: MacAppState.preAuthOnboardingCurrentPageKey)
                UserDefaults.standard.removeObject(forKey: MacAppState.postAuthOnboardingCurrentPageKey)
            }
            hasCompletedPreAuthOnboarding = false
            hasCompletedPostAuthOnboarding = false
        } else if env["WAI_SKIP_ONBOARDING"] == "1" {
            UserDefaults.standard.set(true, forKey: MacAppState.preAuthOnboardingCompletedKey)
            hasCompletedPreAuthOnboarding = true
            hasCompletedPostAuthOnboarding = true
        } else {
            hasCompletedPreAuthOnboarding = Self.preAuthOnboardingCompleted()
            hasCompletedPostAuthOnboarding = false
        }
        refreshCombinedOnboardingState()

        pendingRecordingSyncObserver = NotificationCenter.default.addObserver(
            forName: .pendingRecordingSyncDidFinish,
            object: nil,
            queue: .main
        ) { [weak self] notification in
            guard let syncedRecordingId = notification.userInfo?["recordingId"] as? String else {
                return
            }
            Task { @MainActor in
                self?.handlePendingRecordingSyncDidFinish(recordingId: syncedRecordingId)
            }
        }

        #if DEBUG
        if testingMode.isRecordingFlow || testingMode.isMainView {
            currentUser = MacUITestFixtures.user
            isAuthenticated = true
            isCheckingAuth = false
            hasCompletedPreAuthOnboarding = true
            hasCompletedPostAuthOnboarding = true
            hasCompletedOnboarding = true
            return
        }
        if testingMode.isAuthFlow {
            isCheckingAuth = false
            if env["WAI_FORCE_ONBOARDING"] == "1" {
                hasCompletedPreAuthOnboarding = false
                hasCompletedPostAuthOnboarding = false
                refreshCombinedOnboardingState()
            } else {
                hasCompletedPreAuthOnboarding = true
                hasCompletedPostAuthOnboarding = true
                hasCompletedOnboarding = true
            }
            return
        }
        if testingMode.isOnboardingFlow {
            currentUser = MacUITestFixtures.user
            isAuthenticated = true
            isCheckingAuth = false
            hasCompletedPreAuthOnboarding = false
            hasCompletedPostAuthOnboarding = false
            refreshCombinedOnboardingState()
            dictationManager.configure(
                apiClient: apiClient,
                canStart: { [weak recordingViewModel] in
                    guard let recordingViewModel else { return false }
                    return Self.canStartDictationDuringRecording(phase: recordingViewModel.phase)
                },
                canStartReason: { [weak recordingViewModel] in
                    guard let recordingViewModel else { return "recording_view_model_unavailable" }
                    return Self.dictationStartGateReason(phase: recordingViewModel.phase)
                }
            )
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
                guard self.isAuthenticated else { return }
                await self.dictationManager.historyStore?.hydrate()
                await self.dictationManager.dictionaryStore?.hydrate()
            }
        }

        if hasCompletedPreAuthOnboarding {
            beginStoredSessionRestoreIfNeeded()
        } else {
            isCheckingAuth = false
        }
    }

    deinit {
        if let pendingRecordingSyncObserver {
            NotificationCenter.default.removeObserver(pendingRecordingSyncObserver)
        }
        permissionPollTimer?.invalidate()
    }

    private static var hasExplicitOnboardingCurrentPageArgument: Bool {
        ProcessInfo.processInfo.arguments.contains("-\(onboardingCurrentPageKey)")
            || ProcessInfo.processInfo.arguments.contains("-\(preAuthOnboardingCurrentPageKey)")
            || ProcessInfo.processInfo.arguments.contains("-\(postAuthOnboardingCurrentPageKey)")
    }

    private static func preAuthOnboardingCompleted() -> Bool {
        UserDefaults.standard.bool(forKey: preAuthOnboardingCompletedKey)
            || UserDefaults.standard.bool(forKey: onboardingCompletedKey)
    }

    private static func postAuthOnboardingCompletedKey(userId: String) -> String {
        MacOnboardingDefaultsSnapshot.postAuthOnboardingCompletedKey(userId: userId)
    }

    private func refreshCombinedOnboardingState() {
        hasCompletedOnboarding = hasCompletedPreAuthOnboarding && hasCompletedPostAuthOnboarding
    }

    /// Backward-compatible completion hook for older call sites.
    func completeOnboarding() {
        if isAuthenticated {
            completePostAuthOnboarding()
        } else {
            completePreAuthOnboarding()
        }
    }

    func completePreAuthOnboarding() {
        UserDefaults.standard.set(true, forKey: MacAppState.preAuthOnboardingCompletedKey)
        UserDefaults.standard.removeObject(forKey: MacAppState.preAuthOnboardingCurrentPageKey)
        UserDefaults.standard.removeObject(forKey: MacAppState.onboardingCurrentPageKey)
        MacAppState.legacyOnboardingCompletedKeys.forEach {
            UserDefaults.standard.removeObject(forKey: $0)
        }
        hasCompletedPreAuthOnboarding = true
        refreshCombinedOnboardingState()
        beginStoredSessionRestoreIfNeeded()
    }

    func completePostAuthOnboarding() {
        if let userId = currentUser?.id {
            UserDefaults.standard.set(
                true,
                forKey: MacAppState.postAuthOnboardingCompletedKey(userId: userId)
            )
        }
        UserDefaults.standard.removeObject(forKey: MacAppState.postAuthOnboardingCurrentPageKey)
        UserDefaults.standard.set(true, forKey: MacAppState.onboardingCompletedKey)
        hasCompletedPostAuthOnboarding = true
        refreshCombinedOnboardingState()
    }

    func resetOnboardingForSetupRerun() {
        UserDefaults.standard.set(false, forKey: MacAppState.onboardingCompletedKey)
        UserDefaults.standard.removeObject(forKey: MacAppState.onboardingCurrentPageKey)
        UserDefaults.standard.set(false, forKey: MacAppState.preAuthOnboardingCompletedKey)
        UserDefaults.standard.removeObject(forKey: MacAppState.preAuthOnboardingCurrentPageKey)
        UserDefaults.standard.removeObject(forKey: MacAppState.postAuthOnboardingCurrentPageKey)
        if let userId = currentUser?.id {
            UserDefaults.standard.removeObject(
                forKey: MacAppState.postAuthOnboardingCompletedKey(userId: userId)
            )
        }
        UserDefaults.standard.removeObject(forKey: MacAppState.onboardingSystemAudioSetupKey)
        hasCompletedPreAuthOnboarding = false
        hasCompletedPostAuthOnboarding = false
        refreshCombinedOnboardingState()
    }

    private func beginStoredSessionRestoreIfNeeded() {
        guard !hasAttemptedStoredSessionRestore else {
            isCheckingAuth = false
            return
        }

        hasAttemptedStoredSessionRestore = true
        isCheckingAuth = true

        if ProcessInfo.processInfo.environment["WAI_DISABLE_STORED_SESSION_RESTORE"] == "1" {
            isCheckingAuth = false
            return
        }

        // Restore tokens before onboarding so authenticated users can complete
        // the dictation sandbox with a configured API client.
        let envAccess = ProcessInfo.processInfo.environment["WAICOMPUTER_ACCESS_TOKEN"]
        let envRefresh = ProcessInfo.processInfo.environment["WAICOMPUTER_REFRESH_TOKEN"]

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
            let response = try await apiClient.login(email: email, password: password, locale: authLocale)
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

    func register(email: String, password: String, acceptedLegalTerms: Bool) async {
        isLoading = true
        error = nil

        do {
            let response = try await apiClient.register(
                email: email,
                password: password,
                region: installedBillingRegion()?.rawValue,
                locale: authLocale,
                acceptedLegalTerms: acceptedLegalTerms
            )
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

    func requestMagicLink(email: String, acceptedLegalTerms: Bool = false) async {
        isLoading = true
        error = nil

        do {
            _ = try await apiClient.requestMagicLink(
                email: email,
                client: "macos",
                region: installedBillingRegion()?.rawValue,
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

    private var authLocale: String {
        LanguageManager.shared.preferredLocale.language.languageCode?.identifier == "ru" ? "ru" : "en"
    }

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
            if let rt = response.refreshToken {
                await apiClient.setRefreshToken(rt)
            }
            persistSession(accessToken: response.accessToken, refreshToken: response.refreshToken)
            magicLinkSent = false
            await loadCurrentUser()
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

        await clearLocalSession(removeUserData: true, preserveOnboardingState: true)
        relaunchIfLive()
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
        relaunchIfLive()
        return nil
    }

    /// After a logout/delete-account flow that calls clearLocalSession with
    /// removeUserData=true, the persistent-domain wipe leaves stale state in
    /// any live @StateObject ViewModels (language store, hotkey choice, beta
    /// channel toggle, dictation history, etc.) until the process restarts.
    /// Relaunching here gives users a clean post-sign-out state. Normal logout
    /// preserves onboarding completion; account deletion still resets it.
    /// Skip in test mode so the harness can keep running.
    private func relaunchIfLive() {
        guard testingMode == .live else { return }
        MacPrivacySettings.restartForPermissionRefresh()
    }

    private func persistSession(accessToken: String, refreshToken: String?) {
        do {
            try SessionStore.shared.save(accessToken: accessToken, refreshToken: refreshToken)
        } catch {
            SentryHelper.captureError(error, extras: ["action": "sessionSave"])
        }
    }

    private func clearLocalSession(
        removeUserData: Bool = false,
        preserveOnboardingState: Bool = false
    ) async {
        let currentUserId = currentUser?.id
        let onboardingSnapshot = preserveOnboardingState
            ? MacOnboardingDefaultsSnapshot.capture(userId: currentUserId)
            : nil

        dictationManager.disable()
        dictationManager.updateEnabled(false)
        await apiClient.setAccessToken(nil)
        await apiClient.setRefreshToken(nil)
        SessionStore.shared.clear()
        var cleanupFailure: String?

        if removeUserData {
            do {
                try clearLocalUserData()
                onboardingSnapshot?.restore()
            } catch {
                SentryHelper.captureError(error, extras: ["action": "clearLocalUserData"])
                cleanupFailure = "Signed out, but WaiComputer could not remove all local app data. Quit WaiComputer and remove its local data manually before sharing this Mac."
            }
        }

        SentryHelper.clearUser()
        currentUser = nil
        isAuthenticated = false
        magicLinkSent = false
        passwordResetSent = false
        hasAttemptedStoredSessionRestore = false
        if removeUserData, preserveOnboardingState {
            hasCompletedPreAuthOnboarding = Self.preAuthOnboardingCompleted()
            hasCompletedPostAuthOnboarding = false
            refreshCombinedOnboardingState()
        } else if removeUserData {
            UserDefaults.standard.removeObject(forKey: MacAppState.onboardingCompletedKey)
            UserDefaults.standard.removeObject(forKey: MacAppState.onboardingCurrentPageKey)
            UserDefaults.standard.removeObject(forKey: MacAppState.preAuthOnboardingCompletedKey)
            UserDefaults.standard.removeObject(forKey: MacAppState.preAuthOnboardingCurrentPageKey)
            UserDefaults.standard.removeObject(forKey: MacAppState.postAuthOnboardingCurrentPageKey)
            UserDefaults.standard.removeObject(forKey: MacAppState.onboardingMicAcknowledgedKey)
            UserDefaults.standard.removeObject(forKey: MacAppState.onboardingSystemAudioSetupKey)
            MacAppState.legacyOnboardingCompletedKeys.forEach {
                UserDefaults.standard.removeObject(forKey: $0)
            }
            hasCompletedPreAuthOnboarding = false
            hasCompletedPostAuthOnboarding = false
            hasCompletedOnboarding = false
        }
        error = cleanupFailure
    }

    private func clearLocalUserData() throws {
        dictationManager.historyStore?.clearLocalCache()
        dictationManager.dictionaryStore?.clearLocalCache()
        try RecordingBackupStore.removeAllRecordings()
        try MacLocalUserDataStore.removeWaiComputerSupportDirectories()
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
        hasCompletedPostAuthOnboarding = false
        refreshCombinedOnboardingState()
    }

    func loadCurrentUser() async {
        do {
            let user = try await apiClient.getCurrentUser()
            currentUser = user
            isAuthenticated = true
            if UserDefaults.standard.bool(forKey: MacAppState.onboardingCompletedKey) {
                UserDefaults.standard.set(
                    true,
                    forKey: MacAppState.preAuthOnboardingCompletedKey
                )
                UserDefaults.standard.set(
                    true,
                    forKey: MacAppState.postAuthOnboardingCompletedKey(userId: user.id)
                )
            }
            // Server-side voice enrollment is the cross-device source of truth for
            // "already onboarded": a returning, already-enrolled account must not be
            // shown the post-auth voice onboarding again on a fresh install (102).
            if user.hasEnrolledVoice {
                UserDefaults.standard.set(
                    true,
                    forKey: MacAppState.postAuthOnboardingCompletedKey(userId: user.id)
                )
            }
            hasCompletedPreAuthOnboarding = Self.preAuthOnboardingCompleted()
            hasCompletedPostAuthOnboarding =
                ProcessInfo.processInfo.environment["WAI_SKIP_ONBOARDING"] == "1"
                || UserDefaults.standard.bool(
                    forKey: MacAppState.postAuthOnboardingCompletedKey(userId: user.id)
                )
            refreshCombinedOnboardingState()
            SentryHelper.setUser(id: user.id)
            await syncDownloadRegionToServerIfNeeded()
            await PendingRecordingSyncCoordinator.shared.scheduleSync(
                using: apiClient,
                recoverAbandonedLocalRecordings: true
            )
            dictationManager.configure(
                apiClient: apiClient,
                canStart: { [weak recordingViewModel] in
                    guard let recordingViewModel else { return false }
                    return Self.canStartDictationDuringRecording(phase: recordingViewModel.phase)
                },
                canStartReason: { [weak recordingViewModel] in
                    guard let recordingViewModel else { return "recording_view_model_unavailable" }
                    return Self.dictationStartGateReason(phase: recordingViewModel.phase)
                }
            )
            dictationManager.historyStore?.attach(apiClient: apiClient)
            dictationManager.dictionaryStore?.attach(apiClient: apiClient)
            Task { [dictationManager] in
                await dictationManager.historyStore?.hydrate()
                await dictationManager.dictionaryStore?.hydrate()
            }
        } catch {
            isAuthenticated = false
            currentUser = nil
            hasCompletedPostAuthOnboarding = false
            refreshCombinedOnboardingState()
            SentryHelper.clearUser()
            dictationManager.disable()
        }
    }

    func resumePendingRecordingSyncIfNeeded() async {
        guard isAuthenticated else { return }
        await PendingRecordingSyncCoordinator.shared.scheduleSync(using: apiClient)
    }

    static func canStartDictationDuringRecording(phase: MacRecordingPhase) -> Bool {
        phase == .idle || phase == .recording
    }

    private static func dictationStartGateReason(phase: MacRecordingPhase) -> String {
        if canStartDictationDuringRecording(phase: phase) {
            return "dictation_allowed_recording_phase_\(String(describing: phase))"
        }
        return "recording_phase_\(String(describing: phase))"
    }

    /// Push the build-time WAIDownloadRegion stamp to the server once per
    /// session so backend-side checkout routing (Stripe vs T-Bank) and
    /// currency display reflect the variant the user installed. We only
    /// upgrade `global` → the stamped value; never downgrade or
    /// overwrite a region the user explicitly chose elsewhere.
    private func syncDownloadRegionToServerIfNeeded() async {
        guard let region = installedBillingRegion() else {
            return
        }
        let stamp = region.rawValue
        do {
            let settings = try await apiClient.getSettings()
            if settings.region == stamp { return }
            if settings.region != "global" { return }  // honour explicit user choice
            let request = UpdateSettingsRequest(region: stamp)
            _ = try await apiClient.updateSettings(request)
        } catch {
            // Best-effort sync — log and move on. The next session retries.
            print("Region sync failed: \(error)")
        }
    }

    private func installedBillingRegion() -> BillingDisplayRegion? {
        guard let stamp = Bundle.main
            .object(forInfoDictionaryKey: "WAIDownloadRegion") as? String else {
            return nil
        }
        return BillingDisplayRegion(rawValue: stamp.lowercased())
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
        #if DEBUG
        if let snapshot = MacPermissionTesting.dictationPermissionSnapshot {
            if !snapshot.hasMicrophonePermission {
                missing.insert(.microphone)
            }
            if snapshot.accessibilityStatus != .granted {
                missing.insert(.accessibility)
            }
            updateMissingPermissions(missing)
            return
        }
        #endif

        if AVCaptureDevice.authorizationStatus(for: .audio) != .authorized {
            missing.insert(.microphone)
        }
        if MacInputPermission.postEventStatus() != .granted {
            missing.insert(.accessibility)
        }

        updateMissingPermissions(missing)
    }

    private func updateMissingPermissions(_ missing: Set<MissingPermission>) {
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
    /// Finder so the user can drag it onto the "+" if WaiComputer is missing from
    /// the list.
    func handlePermissionBannerTap(_ kind: MissingPermission) {
        switch kind {
        case .microphone:
            switch AVCaptureDevice.authorizationStatus(for: .audio) {
            case .notDetermined:
                // `AVCaptureDevice.requestAccess(for: .audio)` is the canonical
                // macOS API and triggers the TCC prompt reliably. The previous
                // `AVAudioApplication.requestRecordPermission` path silently
                // failed on macOS 26 (Tahoe), so the in-app "Grant Permission"
                // button appeared to do nothing for some users.
                //
                // Belt-and-suspenders: schedule a fallback that opens System
                // Settings if the prompt did not produce a decision within
                // 1.5s — this covers the rare case where macOS swallows the
                // prompt because the running process already has a stale TCC
                // cache from a prior denial.
                Task {
                    SentryHelper.addBreadcrumb(
                        category: "permission",
                        message: "mic prompt requested (banner)",
                        data: ["status": "notDetermined"]
                    )
                    let granted = await AVCaptureDevice.requestAccess(for: .audio)
                    await MainActor.run {
                        SentryHelper.addBreadcrumb(
                            category: "permission",
                            message: "mic prompt resolved (banner)",
                            data: ["granted": granted]
                        )
                        self.refreshPermissionStatus()
                        if !granted,
                           AVCaptureDevice.authorizationStatus(for: .audio) != .authorized {
                            MacInputPermission.revealAppInFinder()
                            MacPrivacySettings.openMicrophone()
                        }
                    }
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
        inputSource: MacRecordingInputSource = .dual,
        folderId: String? = nil
    ) async {
        completedRecordingContext = nil
        if dictationManager.state != .idle {
            await dictationManager.cancelDictation()
        }

        await recordingViewModel.startRecording(
            apiClient: apiClient,
            type: type,
            inputSource: inputSource,
            folderId: folderId
        )
    }

    func stopRecording() async {
        if completedRecordingContext == nil,
           let recordingId = recordingViewModel.currentRecordingId {
            completedRecordingContext = CompletedRecordingContext(
                recordingId: recordingId,
                transcript: "",
                duration: recordingViewModel.duration,
                recordingType: recordingViewModel.recordingType
            )
        }

        await recordingViewModel.stopRecording()
    }

    func pauseRecording() async {
        await recordingViewModel.pauseRecording()
    }

    func resumeRecording() async {
        await recordingViewModel.resumeRecording()
    }

    func finishCompletedRecordingTransition(recordingId: String) {
        guard completedRecordingContext?.recordingId == recordingId else { return }

        recordingViewModel.resetState()
        completedRecordingContext = nil
    }

    private func handlePendingRecordingSyncDidFinish(recordingId syncedRecordingId: String) {
        finishCompletedRecordingTransition(recordingId: syncedRecordingId)
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

    func uiTestSearchResponse(query: String) -> SearchResponse? {
        #if DEBUG
        guard testingMode.isMainView,
              !query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        else { return nil }
        return MacUITestFixtures.searchResponse
        #else
        return nil
        #endif
    }

    func uiTestUnifiedSearchResponse(query: String) -> UnifiedSearchResponse? {
        #if DEBUG
        guard testingMode.isMainView,
              !query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        else { return nil }
        return MacUITestFixtures.unifiedSearchResponse
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
        if id == MacUITestFixtures.processingRecording.id {
            return MacUITestFixtures.processingRecordingDetail
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
