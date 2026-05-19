import SwiftUI
import AVFoundation
import Carbon
import WaiComputerKit

struct OnboardingView: View {
    @EnvironmentObject var appState: MacAppState
    @EnvironmentObject var dictationManager: DictationManager
    @Environment(\.scenePhase) private var scenePhase
    @State private var currentPage: Int
    @State private var hasMicrophonePermission = OnboardingView.hasMicrophonePermission
    @State private var accessibilityStatus: MacInputPermission.Status = .denied
    @State private var systemAudioStatus = OnboardingView.systemAudioPermissionStatus
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

    private let pages = OnboardingPage.allCases
    @EnvironmentObject var languageStore: DictationLanguageStore

    init() {
        _currentPage = State(initialValue: Self.initialCurrentPage())
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
            currentPage = Self.clampedPageIndex(currentPage)
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
                                accessibilityStatus: accessibilityStatus,
                                systemAudioStatus: systemAudioStatus,
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
                                dictationManager: dictationManager
                            )
                        case .voiceSetup:
                            OnboardingVoiceSetupSlide(
                                isActive: index == currentPage,
                                hasMicrophonePermission: hasMicrophonePermission,
                                onAdvance: advanceToNextPage
                            )
                            .environmentObject(appState)
                        case .sandbox:
                            OnboardingDictationSandboxSlide(
                                isActive: index == currentPage,
                                dictationManager: dictationManager,
                                onContinue: completeOnboarding
                            )
                        }
                    }
                    .frame(width: geo.size.width)
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
                    Text(pages[index].breadcrumbLabel.uppercased())
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
            // Help pill anchored to footer-leading so it never overlaps Skip.
            Button(action: openHelp) {
                HStack(spacing: 6) {
                    ZStack {
                        Circle()
                            .stroke(Palette.textTertiary, lineWidth: 1)
                            .frame(width: 16, height: 16)
                        Image(systemName: "questionmark")
                            .font(.system(size: 9, weight: .bold))
                            .foregroundStyle(Palette.textTertiary)
                    }
                    Text("Help")
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(Palette.textSecondary)
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .background(
                    RoundedRectangle(cornerRadius: 999, style: .continuous)
                        .fill(Color(NSColor.windowBackgroundColor))
                )
                .overlay(
                    RoundedRectangle(cornerRadius: 999, style: .continuous)
                        .strokeBorder(Palette.border, lineWidth: 1)
                )
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("onboarding-help-button")

            Spacer()

            // Skip is an explicit opt-out of setup; normal recording should be
            // ready before the user reaches the main UI.
            Button(isPermissionPage || isSandboxPage ? "Skip for Now" : "Skip") {
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
            if dictationPermissionsReady {
                return "Continue"
            }
            if permissionRestartRecommended {
                return "Restart WaiComputer"
            }
            if hasMicrophonePermission,
               accessibilityStatus == .granted,
               systemAudioStatus == .denied {
                return "Set Up System Audio"
            }
            return "Open Settings"
        }
        return "Continue"
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
            withAnimation(.easeInOut(duration: 0.3)) {
                currentPage = min(currentPage + 1, pages.count - 1)
            }
        }
    }

    private func completeOnboarding() {
        UserDefaults.standard.set(hasMicrophonePermission, forKey: MacAppState.onboardingMicAcknowledgedKey)
        appState.completeOnboarding()
    }

    private func advanceToNextPage() {
        withAnimation(.easeInOut(duration: 0.3)) {
            currentPage = min(currentPage + 1, pages.count - 1)
        }
    }

    private func openHelp() {
        if let url = URL(string: "https://wai.computer/help") {
            NSWorkspace.shared.open(url)
        }
    }

    private static func initialCurrentPage() -> Int {
        clampedPageIndex(UserDefaults.standard.integer(forKey: MacAppState.onboardingCurrentPageKey))
    }

    private static func clampedPageIndex(_ value: Int) -> Int {
        min(max(value, 0), OnboardingPage.allCases.count - 1)
    }

    private func persistCurrentPage() {
        UserDefaults.standard.set(Self.clampedPageIndex(currentPage), forKey: MacAppState.onboardingCurrentPageKey)
    }

    private var dictationPermissionsReady: Bool {
        hasMicrophonePermission && accessibilityStatus == .granted && systemAudioStatus == .granted
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

    private static var hasMicrophonePermission: Bool {
        #if DEBUG
        if let snapshot = MacPermissionTesting.dictationPermissionSnapshot {
            return snapshot.hasMicrophonePermission
        }
        #endif
        return AVCaptureDevice.authorizationStatus(for: .audio) == .authorized
    }

    private static var systemAudioPermissionStatus: MacInputPermission.Status {
        #if DEBUG
        if let snapshot = MacPermissionTesting.dictationPermissionSnapshot {
            return snapshot.systemAudioStatus
        }
        #endif

        guard #available(macOS 14.2, *) else {
            return .granted
        }
        return UserDefaults.standard.bool(forKey: MacAppState.onboardingSystemAudioSetupKey) ? .granted : .denied
    }

    private func refreshPermissions() {
        #if DEBUG
        if let snapshot = MacPermissionTesting.dictationPermissionSnapshot {
            hasMicrophonePermission = snapshot.hasMicrophonePermission
            accessibilityStatus = snapshot.accessibilityStatus
            systemAudioStatus = snapshot.systemAudioStatus
            return
        }
        #endif

        hasMicrophonePermission = Self.hasMicrophonePermission
        accessibilityStatus = MacInputPermission.accessibilityStatus()
        let refreshedSystemAudioStatus = Self.systemAudioPermissionStatus
        systemAudioStatus = triggeredOpenSystemAudioSettings && refreshedSystemAudioStatus != .granted
            ? .staleNeedsRestart
            : refreshedSystemAudioStatus
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
        MacInputPermission.revealAppInFinder()
        MacPrivacySettings.openAccessibility()
    }

    /// Triggers the macOS System Audio Recording prompt before the first real
    /// meeting recording. Apple exposes no standalone authorization API for Core
    /// Audio taps, so the supported preflight is a short tap start/stop.
    private func requestSystemAudioPermission() {
        startPermissionPolling()
        #if DEBUG
        if MacPermissionTesting.forcesMissingDictationPermissions {
            return
        }
        #endif

        guard #available(macOS 14.2, *) else {
            UserDefaults.standard.set(true, forKey: MacAppState.onboardingSystemAudioSetupKey)
            systemAudioStatus = .granted
            refreshPermissions()
            return
        }
        guard !isRequestingSystemAudioPermission else { return }
        isRequestingSystemAudioPermission = true

        Task {
            let capture = SystemAudioCapture()
            do {
                try await capture.startRecording()
                try? await Task.sleep(for: .milliseconds(250))
                await capture.stopRecording()
                await MainActor.run {
                    UserDefaults.standard.set(true, forKey: MacAppState.onboardingSystemAudioSetupKey)
                    triggeredOpenSystemAudioSettings = false
                    systemAudioStatus = .granted
                    isRequestingSystemAudioPermission = false
                    refreshPermissions()
                }
            } catch {
                await capture.stopRecording()
                await MainActor.run {
                    UserDefaults.standard.set(false, forKey: MacAppState.onboardingSystemAudioSetupKey)
                    triggeredOpenSystemAudioSettings = true
                    systemAudioStatus = .staleNeedsRestart
                    isRequestingSystemAudioPermission = false
                    MacInputPermission.revealAppInFinder()
                    MacPrivacySettings.openSystemAudio()
                }
            }
        }
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
        } else if systemAudioStatus != .granted {
            requestSystemAudioPermission()
        }
    }
}


private struct OnboardingPermissionSlide: View {
    @EnvironmentObject var dictationManager: DictationManager

    let isActive: Bool
    let hasMicrophonePermission: Bool
    let accessibilityStatus: MacInputPermission.Status
    let systemAudioStatus: MacInputPermission.Status
    let isRequestingSystemAudioPermission: Bool
    let showSettingsRestartHint: Bool
    let requestMicrophonePermission: () -> Void
    let openAccessibilitySettings: () -> Void
    let requestSystemAudioPermission: () -> Void
    let restartForPermissionRefresh: () -> Void

    var body: some View {
        HStack(spacing: 0) {
            // Left pane — title, body, permission cards
            VStack(alignment: .leading, spacing: 24) {
                Spacer(minLength: 0)
                VStack(alignment: .leading, spacing: 8) {
                    Text("Give WaiComputer permissions")
                        .font(.system(size: 32, weight: .bold))
                        .foregroundStyle(Palette.textPrimary)
                        .fixedSize(horizontal: false, vertical: true)
                    Text("on your computer")
                        .font(.system(size: 32, weight: .bold))
                        .foregroundStyle(Palette.textPrimary)
                }
                Text(permissionBody)
                    .font(.system(size: 14))
                    .foregroundStyle(Palette.textSecondary)
                    .lineSpacing(3)
                    .fixedSize(horizontal: false, vertical: true)

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
                            Text("Already granted? Restart WaiComputer to apply")
                                .font(.system(size: 12, weight: .medium))
                                .underline()
                        }
                        .foregroundStyle(Palette.accent)
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("onboarding-permission-restart-hint")
                    .transition(.opacity.combined(with: .move(edge: .top)))
                }
                Spacer(minLength: 0)
            }
            .frame(maxWidth: 480, alignment: .leading)
            .padding(.horizontal, 48)
            .frame(maxHeight: .infinity)

            // Right pane — illustrated visual aid (warm beige)
            currentPermissionPreview
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(Color(red: 0.98, green: 0.96, blue: 0.92))
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .opacity(isActive ? 1 : 0)
        .offset(y: isActive ? 0 : 16)
        .animation(.easeOut(duration: 0.45).delay(0.1), value: isActive)
    }

    @ViewBuilder
    private var currentPermissionPreview: some View {
        // Show the visual aid for whichever permission row is currently active
        if !hasMicrophonePermission {
            PermissionPreviewMicrophone()
        } else if accessibilityStatus != .granted {
            PermissionPreviewSettings(
                paneTitle: "Accessibility",
                rowLabel: "WaiComputer"
            )
        } else if systemAudioStatus != .granted {
            PermissionPreviewSettings(
                paneTitle: "Screen & System Audio Recording",
                rowLabel: "WaiComputer"
            )
        } else {
            VStack(spacing: 16) {
                Image(systemName: "checkmark.circle.fill")
                    .font(.system(size: 64))
                    .foregroundStyle(.green)
                Text("All set")
                    .font(.system(size: 22, weight: .semibold))
                    .foregroundStyle(Palette.textPrimary)
            }
        }
    }

    private var permissionBody: String {
        if accessibilityStatus == .staleNeedsRestart {
            return "WaiComputer is enabled in System Settings. Restart WaiComputer so macOS applies the new permission to this running app."
        }
        if systemAudioStatus == .staleNeedsRestart {
            return "Enable WaiComputer in System Settings, then restart so macOS applies System Audio Recording to this running app."
        }
        return "Grant Microphone for recording, Accessibility for the global hotkey and text insertion, and System Audio so meeting recordings capture what plays on your Mac."
    }

    @ViewBuilder
    private var microphoneRow: some View {
        PermissionRow(
            title: "Microphone",
            detail: "Record meetings and dictation",
            status: hasMicrophonePermission ? .granted : .denied,
            identifierBase: "onboarding-permission-microphone",
            primaryAction: PermissionRow.Action(label: "Grant", identifier: "grant", run: requestMicrophonePermission),
            restartAction: nil
        )
    }

    @ViewBuilder
    private var accessibilityRow: some View {
        let primary: PermissionRow.Action? = accessibilityStatus == .denied
            ? PermissionRow.Action(label: "Grant", identifier: "grant", run: openAccessibilitySettings)
            : nil
        let restart: PermissionRow.Action? = accessibilityStatus == .staleNeedsRestart
            ? PermissionRow.Action(label: "Restart WaiComputer", identifier: "restart", run: restartForPermissionRefresh)
            : nil
        PermissionRow(
            title: "Accessibility",
            detail: "Listen for the global hotkey and paste dictated text",
            status: accessibilityStatus,
            identifierBase: "onboarding-permission-accessibility",
            primaryAction: primary,
            restartAction: restart
        )
    }

    @ViewBuilder
    private var systemAudioRow: some View {
        let primary: PermissionRow.Action? = systemAudioStatus == .denied
            ? PermissionRow.Action(
                label: isRequestingSystemAudioPermission ? "Setting Up..." : "Set Up",
                identifier: "setup",
                run: requestSystemAudioPermission
            )
            : nil
        let restart: PermissionRow.Action? = systemAudioStatus == .staleNeedsRestart
            ? PermissionRow.Action(label: "Restart WaiComputer", identifier: "restart", run: restartForPermissionRefresh)
            : nil
        PermissionRow(
            title: "System Audio",
            detail: "Capture audio from calls and meetings",
            status: systemAudioStatus,
            identifierBase: "onboarding-permission-system-audio",
            primaryAction: primary,
            restartAction: restart
        )
    }
}

private struct PermissionRow: View {
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
                Text(MacPrivacySettings.permissionRestartHint + " " + MacPrivacySettings.duplicatePermissionHint)
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
                Text("Restart Required")
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
}

// MARK: - Permission preview illustrations (right pane)

/// Stylized macOS system dialog asking for Microphone access. Acts as a
/// visual hint so the user knows exactly what window appears after pressing
/// Allow on the left card. Pure SwiftUI — no PNG asset required.
private struct PermissionPreviewMicrophone: View {
    @State private var pulse = false

    var body: some View {
        ZStack {
            VStack(spacing: 0) {
                // Window chrome (looks like a system alert)
                VStack(spacing: 14) {
                    HStack(spacing: 6) {
                        Spacer()
                        Image(systemName: "questionmark.circle.fill")
                            .font(.system(size: 14))
                            .foregroundStyle(.gray.opacity(0.5))
                    }

                    ZStack {
                        RoundedRectangle(cornerRadius: 10, style: .continuous)
                            .fill(Color.blue.opacity(0.85))
                            .frame(width: 56, height: 56)
                        Image(systemName: "mic.fill")
                            .font(.system(size: 22, weight: .semibold))
                            .foregroundStyle(.white)
                    }

                    VStack(spacing: 6) {
                        Text("\u{201C}WaiComputer\u{201D} would like to")
                            .font(.system(size: 13, weight: .semibold))
                        Text("access the microphone.")
                            .font(.system(size: 13, weight: .semibold))
                        Text("WaiComputer needs access to your")
                            .font(.system(size: 11))
                            .foregroundStyle(.gray)
                            .padding(.top, 4)
                        Text("microphone to record dictation!")
                            .font(.system(size: 11))
                            .foregroundStyle(.gray)
                    }
                    .multilineTextAlignment(.center)

                    HStack(spacing: 6) {
                        ZStack {
                            RoundedRectangle(cornerRadius: 6, style: .continuous)
                                .fill(Color.gray.opacity(0.18))
                            Text("Don\u{2019}t Allow")
                                .font(.system(size: 12, weight: .medium))
                                .foregroundStyle(.black.opacity(0.75))
                        }
                        .frame(height: 28)

                        ZStack {
                            RoundedRectangle(cornerRadius: 6, style: .continuous)
                                .fill(Color.gray.opacity(0.28))
                            Text("OK")
                                .font(.system(size: 12, weight: .medium))
                                .foregroundStyle(.black.opacity(0.85))
                        }
                        .frame(height: 28)
                        .overlay(
                            // Cursor + hand pointing to OK
                            HStack {
                                Spacer()
                                Image(systemName: "hand.point.up.left.fill")
                                    .font(.system(size: 18))
                                    .rotationEffect(.degrees(-25))
                                    .foregroundStyle(.black.opacity(0.85))
                                    .offset(x: 18, y: 10)
                                    .scaleEffect(pulse ? 1.05 : 1.0)
                                    .animation(.easeInOut(duration: 1.2).repeatForever(autoreverses: true), value: pulse)
                            }
                        )
                    }
                }
                .padding(20)
                .frame(width: 270)
                .background(
                    RoundedRectangle(cornerRadius: 14, style: .continuous)
                        .fill(Color.white)
                )
                .shadow(color: .black.opacity(0.18), radius: 22, y: 10)
            }
        }
        .onAppear { pulse = true }
    }
}

/// Stylized macOS System Settings window (Privacy & Security pane) showing
/// a list with the current app's row toggled ON. Used for Input Monitoring
/// and Accessibility steps so the user sees exactly what to look for.
private struct PermissionPreviewSettings: View {
    let paneTitle: String
    let rowLabel: String
    @State private var pulse = false

    var body: some View {
        ZStack {
            VStack(spacing: 0) {
                // Title bar
                HStack(spacing: 6) {
                    Circle().fill(Color.red.opacity(0.85)).frame(width: 9, height: 9)
                    Circle().fill(Color.yellow.opacity(0.85)).frame(width: 9, height: 9)
                    Circle().fill(Color.green.opacity(0.85)).frame(width: 9, height: 9)
                    Spacer()
                    Image(systemName: "chevron.left")
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundStyle(.gray.opacity(0.5))
                    Image(systemName: "chevron.right")
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundStyle(.gray.opacity(0.4))
                    Text(paneTitle)
                        .font(.system(size: 12, weight: .semibold))
                    Spacer()
                }
                .padding(10)
                .background(Color.gray.opacity(0.07))

                Divider()

                // Settings rows
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        Text("Allow the applications below to control your computer.")
                            .font(.system(size: 11))
                            .foregroundStyle(.gray)
                        Spacer()
                    }
                    .padding(.bottom, 2)

                    settingsRow(name: "Screen Studio", on: true)
                    settingsRow(name: "Terminal", on: true)
                    settingsRow(name: rowLabel, on: true, highlight: true)
                    HStack {
                        Text("+")
                            .font(.system(size: 14, weight: .medium))
                            .foregroundStyle(.gray)
                        Text("\u{2013}")
                            .font(.system(size: 14, weight: .medium))
                            .foregroundStyle(.gray.opacity(0.5))
                        Spacer()
                    }
                    .padding(.top, 2)
                }
                .padding(14)
            }
            .frame(width: 320)
            .background(
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .fill(Color.white)
            )
            .shadow(color: .black.opacity(0.18), radius: 22, y: 10)
            .overlay(alignment: .topTrailing) {
                // Cursor pointing at the toggle
                Image(systemName: "cursorarrow")
                    .font(.system(size: 22, weight: .bold))
                    .foregroundStyle(.black)
                    .rotationEffect(.degrees(-15))
                    .offset(x: -18, y: 92)
                    .scaleEffect(pulse ? 1.08 : 1.0)
                    .animation(.easeInOut(duration: 1.2).repeatForever(autoreverses: true), value: pulse)
            }
        }
        .onAppear { pulse = true }
    }

    @ViewBuilder
    private func settingsRow(name: String, on: Bool, highlight: Bool = false) -> some View {
        HStack {
            ZStack {
                RoundedRectangle(cornerRadius: 4, style: .continuous)
                    .fill(Color.gray.opacity(0.2))
                    .frame(width: 18, height: 18)
            }
            Text(name)
                .font(.system(size: 12, weight: highlight ? .semibold : .regular))
            Spacer()
            ZStack(alignment: on ? .trailing : .leading) {
                Capsule()
                    .fill(on ? Color.blue.opacity(0.9) : Color.gray.opacity(0.3))
                    .frame(width: 28, height: 16)
                Circle()
                    .fill(Color.white)
                    .frame(width: 12, height: 12)
                    .padding(2)
                    .shadow(color: .black.opacity(0.2), radius: 1)
            }
        }
        .padding(.vertical, 3)
    }
}
