import SwiftUI
import AVFoundation
import Carbon
import WaiComputerKit

struct OnboardingView: View {
    @EnvironmentObject var appState: MacAppState
    @EnvironmentObject var dictationManager: DictationManager
    @EnvironmentObject var languageManager: LanguageManager
    @Environment(\.scenePhase) private var scenePhase
    @State private var currentPage: Int
    @State private var microphonePermissionStatus = OnboardingView.initialMicrophonePermissionStatus
    @State private var accessibilityStatus: MacInputPermission.Status = .denied
    @State private var systemAudioReadiness = OnboardingView.initialSystemAudioReadiness
    @State private var systemAudioPreflightPassedInCurrentProcess = false
    @State private var isRequestingSystemAudioPermission = false
    @State private var permissionPollTimer: Timer?
    /// Set when the user clicks Grant for a permission whose state is
    /// already `.denied` — that path opens System Settings instead of
    /// triggering an in-process prompt. Per Apple's documented TCC
    /// behavior, decisions made in Settings while the app is running do
    /// not propagate to the cached authorization status; the app needs a
    /// restart. We use this flag to surface a one-tap restart affordance
    /// when scenePhase becomes active again with status still denied.
    @State private var triggeredOpenMicrophoneSettings = false
    @State private var triggeredOpenAccessibilitySettings = false
    @State private var triggeredOpenSystemAudioSettings = false

    private let phase: OnboardingPhase
    private let pages: [OnboardingPage]
    @EnvironmentObject var languageStore: DictationLanguageStore

    init(phase: OnboardingPhase = .preAuth) {
        self.phase = phase
        let pages = phase.pages
        self.pages = pages
        _currentPage = State(initialValue: Self.initialCurrentPage(for: phase, pages: pages))
    }

    private var isLastPage: Bool { currentPage == pages.count - 1 }

    var body: some View {
        VStack(spacing: 0) {
            pageIndicator
                .padding(.top, 18)
                .padding(.bottom, 8)

            slideArea

            footerControls
                .padding(.horizontal, Spacing.xxl)
                .padding(.bottom, Spacing.xxl)
                .padding(.top, Spacing.md)
        }
        .frame(minWidth: 800, minHeight: 640)
        .background(Color(NSColor.windowBackgroundColor).ignoresSafeArea())
        .onAppear {
            currentPage = Self.clampedPageIndex(currentPage, pageCount: pages.count)
            persistCurrentPage()
            refreshPermissions()
            startPermissionPollingIfNeeded()
        }
        .onChange(of: currentPage) { _, _ in
            persistCurrentPage()
        }
        .onDisappear(perform: stopPermissionPolling)
        .onChange(of: scenePhase) { _, newPhase in
            if newPhase == .active {
                refreshPermissions()
                startPermissionPollingIfNeeded()
            }
        }
    }

    // MARK: - Slide area

    private var slideArea: some View {
        GeometryReader { geo in
            HStack(spacing: 0) {
                ForEach(pages.indices, id: \.self) { index in
                    Group {
                        switch pages[index] {
                        case .welcome:
                            OnboardingWelcomeSlide(isActive: index == currentPage)
                        case .valueProps:
                            OnboardingValuePropsSlide(isActive: index == currentPage)
                        case .permission:
                            OnboardingPermissionSlide(
                                isActive: index == currentPage,
                                hasMicrophonePermission: hasMicrophonePermission,
                                microphoneStatus: microphonePermissionStatus,
                                accessibilityStatus: accessibilityStatus,
                                systemAudioStatus: systemAudioStatus,
                                systemAudioReadiness: systemAudioReadiness,
                                isRequestingSystemAudioPermission: isRequestingSystemAudioPermission,
                                showSettingsRestartHint: showSettingsRestartHint,
                                requestMicrophonePermission: requestMicrophonePermission,
                                openAccessibilitySettings: openAccessibilitySettings,
                                requestSystemAudioPermission: requestSystemAudioPermission,
                                restartForPermissionRefresh: MacPrivacySettings.restartForPermissionRefresh
                            )
                            .environmentObject(dictationManager)
                        case .languages:
                            OnboardingLanguagesSlide(
                                isActive: index == currentPage,
                                store: languageStore
                            )
                        case .hotkey:
                            OnboardingHotkeyPickerSlide(
                                isActive: index == currentPage,
                                dictationManager: dictationManager,
                                onSelect: advanceOrComplete
                            )
                        case .voiceSetup:
                            OnboardingVoiceSetupSlide(
                                isActive: index == currentPage,
                                hasMicrophonePermission: hasMicrophonePermission,
                                onAdvance: advanceOrComplete
                            )
                            .environmentObject(appState)
                        case .sandbox:
                            OnboardingDictationSandboxSlide(
                                isActive: index == currentPage,
                                dictationManager: dictationManager,
                                onContinue: advanceOrComplete
                            )
                        }
                    }
                    .frame(width: geo.size.width)
                    .accessibilityHidden(index != currentPage)
                }
            }
            .frame(width: geo.size.width * CGFloat(pages.count), alignment: .leading)
            .offset(x: -geo.size.width * CGFloat(currentPage))
            .animation(.easeInOut(duration: 0.35), value: currentPage)
        }
        .clipped()
    }

    // MARK: - Page indicator

    private var pageIndicator: some View {
        HStack(spacing: 6) {
            ForEach(pages.indices, id: \.self) { index in
                if index > 0 {
                    Image(systemName: "chevron.right")
                        .font(.system(size: 10, weight: .medium))
                        .foregroundStyle(Palette.textTertiary.opacity(0.5))
                }
                VStack(spacing: 6) {
                    Text(pages[index].breadcrumbLabel(language: languageManager.current).uppercased())
                        .font(.system(size: 11, weight: .medium))
                        .tracking(1.3)
                        .foregroundStyle(index == currentPage ? Palette.textPrimary : Palette.textTertiary)
                    Rectangle()
                        .fill(index == currentPage ? Palette.accent : Color.clear)
                        .frame(height: 1.5)
                }
                .padding(.horizontal, 12)
                .animation(.easeInOut(duration: 0.25), value: currentPage)
            }
        }
        .accessibilityIdentifier("onboarding-page-indicator")
    }

    // MARK: - Footer

    private var isPermissionPage: Bool {
        pages[currentPage] == .permission
    }

    private var isSandboxPage: Bool {
        pages[currentPage] == .sandbox
    }

    @ViewBuilder
    private var footerControls: some View {
        HStack(spacing: 12) {
            if currentPage > 0 {
                Button(t("Back", "Назад")) {
                    withAnimation(.easeInOut(duration: 0.3)) {
                        currentPage = max(currentPage - 1, 0)
                    }
                }
                .buttonStyle(WaiGhostButtonStyle())
                .accessibilityIdentifier("onboarding-back-button")
            }

            Spacer()

            // Skip is an explicit opt-out of setup; normal recording should be
            // ready before the user reaches the main UI.
            Button(isPermissionPage || isSandboxPage ? t("Skip for Now", "Пропустить пока") : t("Skip", "Пропустить")) {
                completeOnboarding()
            }
            .buttonStyle(WaiGhostButtonStyle())
            .accessibilityIdentifier("onboarding-skip-button")

            // Sandbox slide owns its own Continue CTA (gated on a successful
            // dictation). Footer hides the primary button there to avoid two
            // competing CTAs.
            if !isSandboxPage {
                Button(action: handlePrimaryTap) {
                    Text(primaryButtonTitle)
                        .frame(minWidth: 160)
                }
                .buttonStyle(WaiPrimaryButtonStyle(isDisabled: false))
                .accessibilityIdentifier(primaryButtonAccessibilityId)
                .keyboardShortcut(.defaultAction)
            }
        }
    }

    private var primaryButtonTitle: String {
        if isPermissionPage {
            return OnboardingPermissionPrimaryActionPolicy.primaryButtonTitle(
                microphoneStatus: microphonePermissionStatus,
                accessibilityStatus: Self.permissionActionStatus(for: accessibilityStatus),
                systemAudioReadiness: systemAudioReadiness,
                restartRecommended: permissionRestartRecommended,
                language: languageManager.current
            )
        }
        return t("Continue", "Продолжить")
    }

    private var primaryButtonAccessibilityId: String {
        // Tests still reference `onboarding-get-started-button` for the
        // permission page; keep that identifier stable.
        if isPermissionPage {
            return "onboarding-get-started-button"
        }
        return "onboarding-continue-button"
    }

    private func handlePrimaryTap() {
        if isPermissionPage {
            refreshPermissions()
            if dictationPermissionsReady {
                // Advance to the verify slide.
                withAnimation(.easeInOut(duration: 0.3)) {
                    currentPage = min(currentPage + 1, pages.count - 1)
                }
            } else if permissionRestartRecommended {
                MacPrivacySettings.restartForPermissionRefresh()
            } else {
                requestNextMissingPermission()
            }
        } else {
            advanceOrComplete()
        }
    }

    private func completeOnboarding() {
        UserDefaults.standard.set(hasMicrophonePermission, forKey: MacAppState.onboardingMicAcknowledgedKey)
        switch phase {
        case .preAuth:
            appState.completePreAuthOnboarding()
        case .postAuth:
            appState.completePostAuthOnboarding()
        }
    }

    private func advanceToNextPage() {
        withAnimation(.easeInOut(duration: 0.3)) {
            currentPage = min(currentPage + 1, pages.count - 1)
        }
    }

    private func advanceOrComplete() {
        if isLastPage {
            completeOnboarding()
        } else {
            advanceToNextPage()
        }
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }

    private static func initialCurrentPage(for phase: OnboardingPhase, pages: [OnboardingPage]) -> Int {
        let defaults = UserDefaults.standard
        if defaults.object(forKey: phase.currentPageKey) == nil,
           case .preAuth = phase,
           defaults.object(forKey: MacAppState.onboardingCurrentPageKey) != nil {
            let legacyPage = defaults.integer(forKey: MacAppState.onboardingCurrentPageKey)
            guard legacyPage < pages.count else { return 0 }
            return clampedPageIndex(
                legacyPage,
                pageCount: pages.count
            )
        }
        return clampedPageIndex(
            defaults.integer(forKey: phase.currentPageKey),
            pageCount: pages.count
        )
    }

    private static func clampedPageIndex(_ value: Int, pageCount: Int? = nil) -> Int {
        min(max(value, 0), max((pageCount ?? OnboardingPage.allCases.count) - 1, 0))
    }

    private func persistCurrentPage() {
        UserDefaults.standard.set(
            Self.clampedPageIndex(currentPage, pageCount: pages.count),
            forKey: phase.currentPageKey
        )
    }

    private var dictationPermissionsReady: Bool {
        hasMicrophonePermission
            && accessibilityStatus == .granted
    }

    private var hasMicrophonePermission: Bool {
        microphonePermissionStatus == .granted
    }

    private var systemAudioStatus: MacInputPermission.Status {
        Self.permissionStatus(for: systemAudioReadiness)
    }

    /// True when the user clicked Grant for a denied permission (which
    /// opens System Settings) and returned to the app without the cached
    /// status updating. Per Apple's TCC docs, the running process needs
    /// to restart for Settings-side changes to take effect.
    private var showSettingsRestartHint: Bool {
        let micStuck = triggeredOpenMicrophoneSettings && !hasMicrophonePermission
        let axStuck = triggeredOpenAccessibilitySettings && accessibilityStatus != .granted
        let systemAudioStuck = triggeredOpenSystemAudioSettings && systemAudioStatus != .granted
        return micStuck || axStuck || systemAudioStuck
    }

    private var permissionRestartRecommended: Bool {
        accessibilityStatus == .staleNeedsRestart || systemAudioStatus == .staleNeedsRestart
    }

    private static var initialMicrophonePermissionStatus: OnboardingPermissionPrimaryActionPolicy.MicrophoneStatus {
        #if DEBUG
        if let snapshot = MacPermissionTesting.dictationPermissionSnapshot {
            return snapshot.microphoneStatus
        }
        #endif
        return permissionStatus(for: AVCaptureDevice.authorizationStatus(for: .audio))
    }

    private static func permissionStatus(
        for authorizationStatus: AVAuthorizationStatus
    ) -> OnboardingPermissionPrimaryActionPolicy.MicrophoneStatus {
        switch authorizationStatus {
        case .authorized:
            return .granted
        case .notDetermined:
            return .requestable
        case .denied, .restricted:
            return .settingsRequired
        @unknown default:
            return .settingsRequired
        }
    }

    private static func permissionActionStatus(
        for status: MacInputPermission.Status
    ) -> OnboardingPermissionPrimaryActionPolicy.AccessibilityStatus {
        switch status {
        case .granted:
            return .granted
        case .denied:
            return .denied
        case .staleNeedsRestart:
            return .staleNeedsRestart
        }
    }

    private static var initialSystemAudioReadiness: SystemAudioReadinessPolicy.Status {
        #if DEBUG
        if let snapshot = MacPermissionTesting.dictationPermissionSnapshot {
            return SystemAudioReadinessPolicy.readiness(from: snapshot.systemAudioStatus)
        }
        #endif

        return currentSystemAudioReadiness(
            preflightPassedInCurrentProcess: false,
            openedSettingsDuringCurrentAttempt: false
        )
    }

    private static var isSystemAudioCaptureSupported: Bool {
        if #available(macOS 14.2, *) {
            return true
        }
        return false
    }

    private static func currentSystemAudioReadiness(
        preflightPassedInCurrentProcess: Bool,
        openedSettingsDuringCurrentAttempt: Bool
    ) -> SystemAudioReadinessPolicy.Status {
        SystemAudioReadinessPolicy.status(
            isSupported: isSystemAudioCaptureSupported,
            preflightPassedInCurrentProcess: preflightPassedInCurrentProcess,
            openedSettingsDuringCurrentAttempt: openedSettingsDuringCurrentAttempt
        )
    }

    private static func permissionStatus(for readiness: SystemAudioReadinessPolicy.Status) -> MacInputPermission.Status {
        SystemAudioReadinessPolicy.permissionStatus(for: readiness)
    }

    private func refreshPermissions() {
        #if DEBUG
        if let snapshot = MacPermissionTesting.dictationPermissionSnapshot {
            microphonePermissionStatus = snapshot.microphoneStatus
            accessibilityStatus = snapshot.accessibilityStatus
            systemAudioReadiness = SystemAudioReadinessPolicy.readiness(from: snapshot.systemAudioStatus)
            return
        }
        #endif

        microphonePermissionStatus = Self.permissionStatus(for: AVCaptureDevice.authorizationStatus(for: .audio))
        accessibilityStatus = MacInputPermission.accessibilityStatus()
        systemAudioReadiness = Self.currentSystemAudioReadiness(
            preflightPassedInCurrentProcess: systemAudioPreflightPassedInCurrentProcess,
            openedSettingsDuringCurrentAttempt: triggeredOpenSystemAudioSettings
        )
        dictationManager.refreshPermissionState()
        if dictationPermissionsReady {
            stopPermissionPolling()
        }
    }

    private func requestMicrophonePermission() {
        startPermissionPolling()
        let initialStatus = AVCaptureDevice.authorizationStatus(for: .audio)
        if initialStatus == .authorized {
            refreshPermissions()
            return
        }

        // `AVCaptureDevice.requestAccess` is the canonical macOS API for
        // microphone capture authorization. For `.notDetermined` it triggers
        // the system prompt and updates the in-process status cache when the
        // user clicks Allow — `AVAudioApplication.requestRecordPermission`
        // sometimes silently fails on macOS 26 (Tahoe). For `.denied` it
        // returns false without prompting; we fall through to opening
        // Settings + revealing in Finder. Per Apple's documented TCC
        // behavior, decisions made in Settings while the app is running
        // do not propagate to the cached status — the user must restart
        // the app, which is what `triggeredOpenMicrophoneSettings` arms.
        Task {
            let granted = await AVCaptureDevice.requestAccess(for: .audio)
            await MainActor.run {
                refreshPermissions()
                if !granted {
                    triggeredOpenMicrophoneSettings = true
                    MacInputPermission.revealAppInFinder()
                    MacPrivacySettings.openMicrophone()
                }
            }
        }
    }

    /// Single Accessibility grant flow: covers both the global hotkey
    /// monitor (NSEvent.addGlobalMonitorForEvents needs Accessibility) and
    /// ⌘V paste (CGEvent.post is governed by the same TCC service on
    /// macOS 11+). Reveals WaiComputer.app in Finder so the user can drag onto
    /// the "+" if Settings shows an empty Accessibility list.
    private func openAccessibilitySettings() {
        startPermissionPolling()
        #if DEBUG
        if MacPermissionTesting.forcesMissingDictationPermissions {
            return
        }
        #endif
        triggeredOpenAccessibilitySettings = true
        _ = GlobalHotkeyManager.requestAccessibilityPermission()
        // Open System Settings directly. The Finder reveal is intentionally not
        // part of the grant flow anymore — it spawned a third window on top of
        // the system prompt + Settings (108); it stays available only as an
        // explicit recovery action when Settings shows a duplicate/empty row.
        MacPrivacySettings.openAccessibility()
    }

    /// Triggers the macOS System Audio Recording prompt before the first real
    /// meeting recording. Apple exposes no standalone authorization API for Core
    /// Audio taps, so the supported preflight is a short tap start plus a buffer
    /// delivery check. A silent buffer is accepted; no buffers means the process
    /// still cannot receive system audio and the user must grant/restart.
    private func requestSystemAudioPermission() {
        startPermissionPolling()
        #if DEBUG
        if MacPermissionTesting.forcesMissingDictationPermissions {
            return
        }
        #endif

        guard #available(macOS 14.2, *) else {
            UserDefaults.standard.set(false, forKey: MacAppState.onboardingSystemAudioSetupKey)
            systemAudioPreflightPassedInCurrentProcess = false
            systemAudioReadiness = .unsupported
            refreshPermissions()
            return
        }
        guard !isRequestingSystemAudioPermission else { return }
        isRequestingSystemAudioPermission = true

        Task {
            do {
                let receivedBuffers = try await SystemAudioPermissionPreflight.receivedBuffers()

                await MainActor.run {
                    if receivedBuffers {
                        SentryHelper.addBreadcrumb(
                            category: "permission",
                            message: "system audio preflight received buffers",
                            data: ["timeoutMs": Int(SystemAudioPermissionPreflight.defaultTimeout * 1000)]
                        )
                        systemAudioPreflightPassedInCurrentProcess = true
                        UserDefaults.standard.set(true, forKey: MacAppState.onboardingSystemAudioSetupKey)
                        triggeredOpenSystemAudioSettings = false
                        isRequestingSystemAudioPermission = false
                        refreshPermissions()
                    } else {
                        SentryHelper.addBreadcrumb(
                            category: "permission",
                            message: "system audio preflight produced no buffers",
                            level: .warning,
                            data: ["timeoutMs": Int(SystemAudioPermissionPreflight.defaultTimeout * 1000)]
                        )
                        markSystemAudioSetupFailed()
                    }
                }
            } catch {
                await MainActor.run {
                    SentryHelper.captureError(
                        error,
                        extras: ["action": "systemAudioPreflight"]
                    )
                    markSystemAudioSetupFailed()
                }
            }
        }
    }

    private func markSystemAudioSetupFailed() {
        systemAudioPreflightPassedInCurrentProcess = false
        UserDefaults.standard.set(false, forKey: MacAppState.onboardingSystemAudioSetupKey)
        triggeredOpenSystemAudioSettings = true
        isRequestingSystemAudioPermission = false
        refreshPermissions()
        MacInputPermission.revealAppInFinder()
        MacPrivacySettings.openSystemAudio()
    }

    private func startPermissionPollingIfNeeded() {
        if !dictationPermissionsReady {
            startPermissionPolling()
        }
    }

    private func startPermissionPolling() {
        stopPermissionPolling()
        permissionPollTimer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { _ in
            DispatchQueue.main.async {
                refreshPermissions()
            }
        }
    }

    private func stopPermissionPolling() {
        permissionPollTimer?.invalidate()
        permissionPollTimer = nil
    }

    private func requestNextMissingPermission() {
        if !hasMicrophonePermission {
            requestMicrophonePermission()
        } else if accessibilityStatus != .granted {
            openAccessibilitySettings()
        }
    }
}


private struct OnboardingPermissionSlide: View {
    @EnvironmentObject var dictationManager: DictationManager
    @EnvironmentObject private var languageManager: LanguageManager

    let isActive: Bool
    let hasMicrophonePermission: Bool
    let microphoneStatus: OnboardingPermissionPrimaryActionPolicy.MicrophoneStatus
    let accessibilityStatus: MacInputPermission.Status
    let systemAudioStatus: MacInputPermission.Status
    let systemAudioReadiness: SystemAudioReadinessPolicy.Status
    let isRequestingSystemAudioPermission: Bool
    let showSettingsRestartHint: Bool
    let requestMicrophonePermission: () -> Void
    let openAccessibilitySettings: () -> Void
    let requestSystemAudioPermission: () -> Void
    let restartForPermissionRefresh: () -> Void

    var body: some View {
        HStack(alignment: .center, spacing: 36) {
            ScrollView(showsIndicators: false) {
                VStack(alignment: .leading, spacing: 22) {
                    VStack(alignment: .leading, spacing: 8) {
                        Text(t("Give WaiComputer permissions", "Разрешения для WaiComputer"))
                            .font(.system(size: 32, weight: .bold))
                            .foregroundStyle(Palette.textPrimary)
                            .fixedSize(horizontal: false, vertical: true)
                        Text(t("on this Mac", "на этом Mac"))
                            .font(.system(size: 32, weight: .bold))
                            .foregroundStyle(Palette.textPrimary)
                    }

                    VStack(spacing: 12) {
                        microphoneRow
                        accessibilityRow
                        systemAudioRow
                    }

                    if showSettingsRestartHint {
                        Button(action: restartForPermissionRefresh) {
                            HStack(spacing: 6) {
                                Image(systemName: "arrow.clockwise.circle.fill")
                                    .font(.system(size: 13))
                                Text(t(
                                    "Already granted? Restart WaiComputer to apply",
                                    "Уже разрешено? Перезапусти WaiComputer"
                                ))
                                    .font(.system(size: 12, weight: .medium))
                                    .underline()
                            }
                            .foregroundStyle(Palette.accent)
                        }
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("onboarding-permission-restart-hint")
                        .transition(.opacity.combined(with: .move(edge: .top)))
                    }
                }
            }
            .frame(maxWidth: 500, maxHeight: 510, alignment: .center)
            .scrollBounceBehavior(.basedOnSize)

            permissionExplanationPanel
                .frame(maxWidth: 360, alignment: .leading)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(.horizontal, 48)
        .opacity(isActive ? 1 : 0)
        .offset(y: isActive ? 0 : 16)
        .animation(.easeOut(duration: 0.45).delay(0.1), value: isActive)
    }

    @ViewBuilder
    private var permissionExplanationPanel: some View {
        VStack(alignment: .leading, spacing: 18) {
            ZStack {
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .fill(Palette.accent.opacity(0.12))
                    .frame(width: 64, height: 64)
                Image(systemName: permissionPanelIcon)
                    .font(.system(size: 28, weight: .semibold))
                    .foregroundStyle(Palette.accent)
            }

            VStack(alignment: .leading, spacing: 8) {
                Text(permissionPanelTitle)
                    .font(.system(size: 20, weight: .semibold))
                    .foregroundStyle(Palette.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)
                Text(permissionBody)
                    .font(.system(size: 14))
                    .foregroundStyle(Palette.textSecondary)
                    .lineSpacing(3)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Divider()

            VStack(alignment: .leading, spacing: 10) {
                explanationRow(
                    icon: "mic.fill",
                    text: t("Your voice for dictation, notes, and meetings", "Твой голос для диктовки, заметок и встреч")
                )
                explanationRow(
                    icon: "keyboard",
                    text: t("Global push-to-talk and text insertion", "Глобальная клавиша диктовки и вставка текста")
                )
                explanationRow(
                    icon: "waveform",
                    text: t("Other speakers and app audio in meeting recordings", "Голоса других участников и звук приложений в записях встреч")
                )
            }
        }
        .padding(22)
        .background(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .fill(Palette.surfaceSubtle)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .strokeBorder(Palette.border, lineWidth: 1)
        )
    }

    @ViewBuilder
    private func explanationRow(icon: String, text: String) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: icon)
                .font(.system(size: 14, weight: .medium))
                .foregroundStyle(Palette.accent)
                .frame(width: 18, height: 18)
            Text(text)
                .font(.system(size: 13))
                .foregroundStyle(Palette.textSecondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private var permissionPanelIcon: String {
        if !hasMicrophonePermission { return "mic.fill" }
        if accessibilityStatus != .granted { return "keyboard" }
        if systemAudioReadiness == .unsupported { return "exclamationmark.triangle.fill" }
        if systemAudioStatus != .granted { return "waveform" }
        return "checkmark.circle.fill"
    }

    private var permissionPanelTitle: String {
        if !hasMicrophonePermission {
            return t("Start with Microphone", "Сначала микрофон")
        }
        if accessibilityStatus != .granted {
            return t("Then Accessibility", "Затем Универсальный доступ")
        }
        if systemAudioReadiness == .unsupported {
            return t("System Audio unavailable", "Звук Mac недоступен")
        }
        if systemAudioStatus != .granted {
            return t("Finish with System Audio", "И звук Mac")
        }
        return t("All permissions are ready", "Все разрешения готовы")
    }

    private var permissionBody: String {
        if accessibilityStatus == .staleNeedsRestart {
            return t(
                "WaiComputer is enabled in System Settings. Restart WaiComputer so macOS applies the new permission to this running app.",
                "WaiComputer включен в системных настройках. Перезапусти приложение, чтобы macOS применила разрешение к текущему процессу."
            )
        }
        if systemAudioStatus == .staleNeedsRestart {
            return t(
                "Enable WaiComputer in the System Audio Recording Only section of System Settings, then restart so macOS applies the permission.",
                "Включи WaiComputer в нижнем разделе «Только запись системного звука», затем перезапусти приложение."
            )
        }
        if systemAudioReadiness == .unsupported {
            return t(
                "System Audio Recording requires macOS 14.2 or later. Microphone dictation can still work, but meeting recordings cannot capture app audio on this Mac.",
                "Запись звука Mac требует macOS 14.2 или новее. Диктовка через микрофон может работать, но записи встреч не смогут сохранять звук приложений на этом Mac."
            )
        }
        return t(
            "Grant Microphone for your voice, Accessibility for the global dictation hotkey and text insertion, and System Audio so meeting recordings capture other speakers and audio playing on your Mac.",
            "Разреши микрофон для своего голоса, Универсальный доступ для глобальной клавиши и вставки текста, а звук Mac — чтобы записи встреч сохраняли других участников и аудио из приложений."
        )
    }

    @ViewBuilder
    private var microphoneRow: some View {
        let actionLabel = OnboardingPermissionPrimaryActionPolicy.microphoneRowActionLabel(
            microphoneStatus: microphoneStatus,
            language: languageManager.current
        )
        PermissionRow(
            title: t("Microphone", "Микрофон"),
            detail: t("Record your voice for dictation, notes, and meetings", "Микрофон нужен для диктовки, заметок и встреч"),
            status: hasMicrophonePermission ? .granted : .denied,
            identifierBase: "onboarding-permission-microphone",
            primaryAction: actionLabel.map {
                PermissionRow.Action(label: $0, identifier: "grant", run: requestMicrophonePermission)
            },
            restartAction: nil
        )
    }

    @ViewBuilder
    private var accessibilityRow: some View {
        let primary: PermissionRow.Action? = accessibilityStatus == .denied
            ? PermissionRow.Action(label: t("Grant", "Разрешить"), identifier: "grant", run: openAccessibilitySettings)
            : nil
        let restart: PermissionRow.Action? = accessibilityStatus == .staleNeedsRestart
            ? PermissionRow.Action(label: t("Restart WaiComputer", "Перезапустить WaiComputer"), identifier: "restart", run: restartForPermissionRefresh)
            : nil
        PermissionRow(
            title: t("Accessibility", "Универсальный доступ"),
            detail: t(
                "Listen for the global hotkey and paste dictated text",
                "Глобальная клавиша и автоматическая вставка текста"
            ),
            status: accessibilityStatus,
            identifierBase: "onboarding-permission-accessibility",
            primaryAction: primary,
            restartAction: restart
        )
    }

    @ViewBuilder
    private var systemAudioRow: some View {
        let primary: PermissionRow.Action? = systemAudioReadiness == .setupNeeded
            ? PermissionRow.Action(
                label: isRequestingSystemAudioPermission
                    ? t("Setting Up...", "Настраиваем...")
                    : t("Set Up", "Настроить"),
                identifier: "setup",
                run: requestSystemAudioPermission
            )
            : nil
        let restart: PermissionRow.Action? = systemAudioStatus == .staleNeedsRestart
            ? PermissionRow.Action(label: t("Restart WaiComputer", "Перезапустить WaiComputer"), identifier: "restart", run: restartForPermissionRefresh)
            : nil
        PermissionRow(
            title: t("System Audio", "Звук Mac"),
            detail: systemAudioDetail,
            status: systemAudioStatus,
            identifierBase: "onboarding-permission-system-audio",
            primaryAction: primary,
            restartAction: restart
        )
    }

    private var systemAudioDetail: String {
        switch systemAudioReadiness {
        case .unsupported:
            return t(
                "Requires macOS 14.2 or later; app audio cannot be captured here",
                "Требуется macOS 14.2 или новее; звук приложений здесь не записать"
            )
        case .setupNeeded:
            return t(
                "Run a short real capture check before meeting recordings",
                "Короткая проверка реальной записи перед встречами"
            )
        case .restartRequired:
            return t(
                "Enable WaiComputer in Screen & System Audio Recording, then restart",
                "Включи WaiComputer в «Запись экрана и системного звука» и перезапусти"
            )
        case .ready:
            return t(
                "Capture other speakers and app audio in calls and meetings",
                "Запись других участников и звука приложений во встречах"
            )
        }
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

private struct PermissionRow: View {
    @EnvironmentObject private var languageManager: LanguageManager

    struct Action {
        let label: String
        let identifier: String
        let run: () -> Void
    }

    let title: String
    let detail: String
    let status: MacInputPermission.Status
    let identifierBase: String
    let primaryAction: Action?
    let restartAction: Action?

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(alignment: .center, spacing: 12) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(title)
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundStyle(Palette.textPrimary)
                    Text(detail)
                        .font(.system(size: 13))
                        .foregroundStyle(Palette.textSecondary)
                        .lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 16)
                trailingControls
            }
            if status == .staleNeedsRestart {
                Text(t(
                    "After changing this in System Settings, restart WaiComputer so macOS applies it to the running app. If Settings shows duplicate WaiComputer rows, enable the current app bundle.",
                    "После изменения в системных настройках перезапусти WaiComputer, чтобы macOS применила доступ к текущему процессу. Если в настройках несколько строк WaiComputer, включи текущий .app."
                ))
                    .font(.system(size: 12))
                    .foregroundStyle(Palette.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(16)
        .background(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill(Color(NSColor.windowBackgroundColor))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .strokeBorder(Palette.border, lineWidth: 1)
        )
    }

    @ViewBuilder
    private var trailingControls: some View {
        switch status {
        case .granted:
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 22))
                .foregroundStyle(.green)
        case .denied:
            if let primaryAction {
                Button(action: primaryAction.run) {
                    Text(primaryAction.label)
                        .font(.system(size: 13, weight: .medium))
                        .foregroundStyle(.white)
                        .padding(.horizontal, 16)
                        .padding(.vertical, 8)
                        .background(
                            RoundedRectangle(cornerRadius: 999, style: .continuous)
                                .fill(Color.black)
                        )
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("\(identifierBase)-\(primaryAction.identifier)")
            }
        case .staleNeedsRestart:
            HStack(spacing: 6) {
                Text(t("Restart Required", "Нужен перезапуск"))
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(Palette.accent)
                    .accessibilityIdentifier("\(identifierBase)-restart-required")
                if let restartAction {
                    Button(action: restartAction.run) {
                        Text(restartAction.label)
                            .font(.system(size: 13, weight: .medium))
                            .foregroundStyle(.white)
                            .padding(.horizontal, 16)
                            .padding(.vertical, 8)
                            .background(
                                RoundedRectangle(cornerRadius: 999, style: .continuous)
                                    .fill(Color.black)
                            )
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("\(identifierBase)-\(restartAction.identifier)")
                }
            }
        }
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}
