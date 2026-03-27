import SwiftUI
import WaiComputerKit

extension Notification.Name {
    static let importAudioFile = Notification.Name("importAudioFile")
    static let showNewRecording = Notification.Name("showNewRecording")
}

@main
struct WaiComputerMacApp: App {
    @StateObject private var recordingViewModel: MacRecordingViewModel
    @StateObject private var appState: MacAppState
    @StateObject private var dictationManager: DictationManager

    init() {
        #if !DEBUG
        SentryHelper.start(dsn: "<SENTRY_DSN>")
        #endif

        let testingMode = MacTestingMode.current
        let recordingViewModel = MacRecordingViewModel(testingMode: testingMode)
        let dictation = DictationManager()

        _recordingViewModel = StateObject(wrappedValue: recordingViewModel)
        _dictationManager = StateObject(wrappedValue: dictation)
        _appState = StateObject(
            wrappedValue: MacAppState(
                recordingViewModel: recordingViewModel,
                dictationManager: dictation,
                testingMode: testingMode
            )
        )
    }

    var body: some Scene {
        WindowGroup {
            MacContentView()
                .environmentObject(appState)
                .environmentObject(recordingViewModel)
                .environmentObject(dictationManager)
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

            // Remove the default "New Window" from the Window menu
            CommandGroup(replacing: .windowList) {}
        }

        // Menu bar extra
        MenuBarExtra("WaiComputer", systemImage: isRecordingActivityVisible ? "waveform.circle.fill" : "brain.head.profile") {
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

        let baseURL = URL(string: "https://wai.computer")!
        apiClient = APIClient(baseURL: baseURL)

        #if DEBUG
        if testingMode.isRecordingFlow || testingMode.isMainView {
            currentUser = MacUITestFixtures.user
            isAuthenticated = true
            isCheckingAuth = false
            return
        }
        if testingMode.isAuthFlow {
            isCheckingAuth = false
            return
        }
        #endif

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
            KeychainHelper.save(key: KeychainHelper.accessTokenKey, value: response.accessToken)
            if let rt = response.refreshToken {
                await apiClient.setRefreshToken(rt)
                KeychainHelper.save(key: KeychainHelper.refreshTokenKey, value: rt)
            }
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
        // Best-effort server logout with refresh token revocation
        let rt = await apiClient.getRefreshToken()
        do {
            _ = try await apiClient.logout(refreshToken: rt)
        } catch {
            NSLog("[Auth] Server logout failed (proceeding with local logout): %@", error.localizedDescription)
        }

        dictationManager.disable()
        await apiClient.setAccessToken(nil)
        await apiClient.setRefreshToken(nil)
        KeychainHelper.delete(key: KeychainHelper.accessTokenKey)
        KeychainHelper.delete(key: KeychainHelper.refreshTokenKey)
        // Clean up legacy UserDefaults if still present
        UserDefaults.standard.removeObject(forKey: "accessToken")
        SentryHelper.clearUser()
        currentUser = nil
        isAuthenticated = false
    }

    /// Called when auto-refresh fails — transition to login screen
    private func handleAuthenticationFailed() {
        KeychainHelper.delete(key: KeychainHelper.accessTokenKey)
        KeychainHelper.delete(key: KeychainHelper.refreshTokenKey)
        UserDefaults.standard.removeObject(forKey: "accessToken")
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
        return [MacUITestFixtures.recording]
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
