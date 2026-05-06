import SwiftUI
import AVFoundation
import Carbon

struct OnboardingView: View {
    @EnvironmentObject var appState: MacAppState
    @EnvironmentObject var dictationManager: DictationManager
    @Environment(\.scenePhase) private var scenePhase
    @State private var currentPage: Int
    @State private var hasMicrophonePermission = OnboardingView.hasMicrophonePermission
    @State private var inputMonitoringStatus: MacInputPermission.Status = .denied
    @State private var pasteStatus: MacInputPermission.Status = .denied
    @State private var permissionPollTimer: Timer?

    private let pages = OnboardingPage.allCases

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
                    if pages[index] == .permission {
                        OnboardingPermissionSlide(
                            isActive: index == currentPage,
                            hasMicrophonePermission: hasMicrophonePermission,
                            inputMonitoringStatus: inputMonitoringStatus,
                            pasteStatus: pasteStatus,
                            requestMicrophonePermission: requestMicrophonePermission,
                            openInputMonitoringSettings: openInputMonitoringSettings,
                            openPasteSettings: openPasteSettings,
                            recheckPermissions: refreshPermissions,
                            restartForPermissionRefresh: MacPrivacySettings.restartForPermissionRefresh
                        )
                        .environmentObject(dictationManager)
                        .frame(width: geo.size.width)
                    } else if pages[index] == .verify {
                        OnboardingVerifySlide(
                            isActive: index == currentPage,
                            onConfirm: completeOnboarding
                        )
                        .environmentObject(dictationManager)
                        .frame(width: geo.size.width)
                    } else {
                        OnboardingSlide(page: pages[index], isActive: index == currentPage)
                        .frame(width: geo.size.width)
                    }
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

    private var isVerifyPage: Bool {
        pages[currentPage] == .verify
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

            // Skip drops the user into the main UI. Missing permissions
            // surface as a banner there, so skipping is safe.
            Button(isPermissionPage || isVerifyPage ? "Skip for Now" : "Skip") {
                completeOnboarding()
            }
            .buttonStyle(WaiGhostButtonStyle())
            .accessibilityIdentifier("onboarding-skip-button")

            // Verify slide owns its own Continue CTA. Footer hides the
            // primary button there to avoid two competing CTAs.
            if !isVerifyPage {
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
                return "Restart WaiSay"
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

    private func openHelp() {
        if let url = URL(string: "https://say.waiwai.is/help") {
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
        hasMicrophonePermission &&
            inputMonitoringStatus == .granted &&
            pasteStatus == .granted
    }

    private var permissionRestartRecommended: Bool {
        inputMonitoringStatus == .staleNeedsRestart || pasteStatus == .staleNeedsRestart
    }

    private static var hasMicrophonePermission: Bool {
        #if DEBUG
        if let snapshot = MacPermissionTesting.dictationPermissionSnapshot {
            return snapshot.hasMicrophonePermission
        }
        #endif
        return AVCaptureDevice.authorizationStatus(for: .audio) == .authorized
    }

    private func refreshPermissions() {
        #if DEBUG
        if let snapshot = MacPermissionTesting.dictationPermissionSnapshot {
            hasMicrophonePermission = snapshot.hasMicrophonePermission
            inputMonitoringStatus = snapshot.inputMonitoringStatus
            pasteStatus = snapshot.pasteStatus
            return
        }
        #endif

        hasMicrophonePermission = Self.hasMicrophonePermission
        inputMonitoringStatus = MacInputPermission.listenEventStatus()
        pasteStatus = MacInputPermission.postEventStatus()
        dictationManager.refreshPermissionState()
        if dictationPermissionsReady {
            stopPermissionPolling()
        }
    }

    private func requestMicrophonePermission() {
        startPermissionPolling()
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized:
            refreshPermissions()
        case .notDetermined:
            Task {
                _ = await AVAudioApplication.requestRecordPermission()
                await MainActor.run {
                    refreshPermissions()
                    if !hasMicrophonePermission {
                        MacPrivacySettings.openMicrophone()
                    }
                }
            }
        case .denied, .restricted:
            MacPrivacySettings.openMicrophone()
            refreshPermissions()
        @unknown default:
            MacPrivacySettings.openMicrophone()
            refreshPermissions()
        }
    }

    /// Single entry point for the Input Monitoring row's primary action.
    ///
    /// When the permission has never been requested, `requestListenEventAccess`
    /// brings up the system consent sheet. If the user has previously denied or
    /// the system prompt does not appear (`returns false`), we open System
    /// Settings ourselves so the user has a clear path. We never preemptively
    /// flip the row into the "Restart Required" state — the polling loop will
    /// promote it via `MacInputPermission.listenEventStatus()` only when the
    /// kernel cache and the live probe disagree.
    private func openInputMonitoringSettings() {
        startPermissionPolling()
        #if DEBUG
        if MacPermissionTesting.forcesMissingDictationPermissions {
            return
        }
        #endif
        let prompted = GlobalHotkeyManager.requestInputMonitoringPermission()
        if !prompted {
            MacPrivacySettings.openInputMonitoring()
        } else {
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {
                refreshPermissions()
                if inputMonitoringStatus != .granted {
                    MacPrivacySettings.openInputMonitoring()
                }
            }
        }
    }

    private func openPasteSettings() {
        startPermissionPolling()
        #if DEBUG
        if MacPermissionTesting.forcesMissingDictationPermissions {
            return
        }
        #endif
        let prompted = TextInserter.requestEventPostingPermission()
        if !prompted {
            TextInserter.openEventPostingSettings()
        } else {
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {
                refreshPermissions()
                if pasteStatus != .granted {
                    TextInserter.openEventPostingSettings()
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
        } else if inputMonitoringStatus != .granted {
            openInputMonitoringSettings()
        } else if pasteStatus != .granted {
            openPasteSettings()
        }
    }
}

private struct OnboardingPermissionSlide: View {
    @EnvironmentObject var dictationManager: DictationManager

    let isActive: Bool
    let hasMicrophonePermission: Bool
    let inputMonitoringStatus: MacInputPermission.Status
    let pasteStatus: MacInputPermission.Status
    let requestMicrophonePermission: () -> Void
    let openInputMonitoringSettings: () -> Void
    let openPasteSettings: () -> Void
    let recheckPermissions: () -> Void
    let restartForPermissionRefresh: () -> Void

    private var content: OnboardingPage.Content { OnboardingPage.permission.content }

    var body: some View {
        HStack(spacing: 0) {
            // Left pane — title, body, permission cards
            VStack(alignment: .leading, spacing: 24) {
                Spacer(minLength: 0)
                VStack(alignment: .leading, spacing: 8) {
                    Text("Give WaiSay permissions")
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
                    inputMonitoringRow
                    automaticPasteRow
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
        } else if inputMonitoringStatus != .granted {
            PermissionPreviewSettings(
                paneTitle: "Input Monitoring",
                rowLabel: "WaiSay"
            )
        } else if pasteStatus != .granted {
            PermissionPreviewSettings(
                paneTitle: "Accessibility",
                rowLabel: "WaiSay"
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
        if inputMonitoringStatus == .staleNeedsRestart || pasteStatus == .staleNeedsRestart {
            return "WaiSay is enabled in System Settings. Restart WaiSay so macOS applies the new permission to this running app."
        }
        return content.body
    }

    @ViewBuilder
    private var microphoneRow: some View {
        PermissionRow(
            title: "Microphone",
            detail: "Record meetings and dictation",
            status: hasMicrophonePermission ? .granted : .denied,
            identifierBase: "onboarding-permission-microphone",
            primaryAction: PermissionRow.Action(label: "Grant", identifier: "grant", run: requestMicrophonePermission),
            secondaryAction: nil,
            recheckAction: nil,
            restartAction: nil
        )
    }

    private struct PermissionActions {
        var primary: PermissionRow.Action?
        var secondary: PermissionRow.Action?
        var recheck: PermissionRow.Action?
        var restart: PermissionRow.Action?
    }

    private func inputMonitoringActions() -> PermissionActions {
        switch inputMonitoringStatus {
        case .granted:
            return PermissionActions()
        case .denied:
            return PermissionActions(
                primary: PermissionRow.Action(label: "Grant", identifier: "grant", run: openInputMonitoringSettings),
                secondary: PermissionRow.Action(label: "Settings", identifier: "settings", run: { MacPrivacySettings.openInputMonitoring() })
            )
        case .staleNeedsRestart:
            return PermissionActions(
                secondary: PermissionRow.Action(label: "Settings", identifier: "settings", run: { MacPrivacySettings.openInputMonitoring() }),
                restart: PermissionRow.Action(label: "Restart WaiSay", identifier: "restart", run: restartForPermissionRefresh)
            )
        }
    }

    private func pasteActions() -> PermissionActions {
        switch pasteStatus {
        case .granted:
            return PermissionActions()
        case .denied:
            return PermissionActions(
                primary: PermissionRow.Action(label: "Grant", identifier: "grant", run: openPasteSettings),
                secondary: PermissionRow.Action(label: "Settings", identifier: "settings", run: { TextInserter.openEventPostingSettings() })
            )
        case .staleNeedsRestart:
            return PermissionActions(
                secondary: PermissionRow.Action(label: "Settings", identifier: "settings", run: { TextInserter.openEventPostingSettings() }),
                restart: PermissionRow.Action(label: "Restart WaiSay", identifier: "restart", run: restartForPermissionRefresh)
            )
        }
    }

    @ViewBuilder
    private var inputMonitoringRow: some View {
        let actions = inputMonitoringActions()
        PermissionRow(
            title: "Input Monitoring",
            detail: "Use the hotkey from any app",
            status: inputMonitoringStatus,
            identifierBase: "onboarding-permission-input-monitoring",
            primaryAction: actions.primary,
            secondaryAction: actions.secondary,
            recheckAction: actions.recheck,
            restartAction: actions.restart
        )
    }

    @ViewBuilder
    private var automaticPasteRow: some View {
        let actions = pasteActions()

        PermissionRow(
            title: "Automatic Paste",
            detail: "Insert dictated text automatically",
            status: pasteStatus,
            identifierBase: "onboarding-permission-automatic-paste",
            primaryAction: actions.primary,
            secondaryAction: actions.secondary,
            recheckAction: actions.recheck,
            restartAction: actions.restart
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
    let secondaryAction: Action?
    let recheckAction: Action?
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
                        Text("\u{201C}WaiSay\u{201D} would like to")
                            .font(.system(size: 13, weight: .semibold))
                        Text("access the microphone.")
                            .font(.system(size: 13, weight: .semibold))
                        Text("WaiSay needs access to your")
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

// MARK: - Hotkey verification slide

/// Live key-press tester after the permissions step — proves the hotkey is
/// actually wired up before the user lands in the main UI. Uses
/// `NSEvent.addLocalMonitorForEvents`, which works while the onboarding window
/// has focus and does not depend on Input Monitoring permission yet — useful
/// because the user just granted it and TCC may not have caught up.
private struct OnboardingVerifySlide: View {
    @EnvironmentObject var dictationManager: DictationManager

    let isActive: Bool
    let onConfirm: () -> Void

    @State private var pressedAtLeastOnce = false
    @State private var pressFlash = false
    @State private var localMonitor: Any?

    var body: some View {
        VStack(spacing: 32) {
            Spacer(minLength: 0)

            VStack(spacing: 10) {
                Text("Test the keyboard shortcut")
                    .font(.system(size: 32, weight: .bold))
                    .foregroundStyle(Palette.textPrimary)
                    .multilineTextAlignment(.center)

                HStack(spacing: 6) {
                    Text("We recommend the")
                    keyChip(dictationManager.selectedHotkey.shortLabel, highlight: false)
                    Text("key.")
                }
                .font(.system(size: 14))
                .foregroundStyle(Palette.textSecondary)
            }

            VStack(spacing: 18) {
                Text(pressedAtLeastOnce
                     ? "Looks good — release the key when you\u{2019}re ready."
                     : "Press the shortcut now to test.")
                    .font(.system(size: 14, weight: .medium))
                    .foregroundStyle(Palette.textSecondary)

                keyVisualization

                HStack(spacing: 12) {
                    // Inline hotkey picker — lets the user change the key
                    // right here if the test fails. Avoids the broken
                    // "open Settings" jump that doesn't exist during
                    // pre-auth onboarding.
                    Picker("", selection: Binding(
                        get: { dictationManager.selectedHotkey },
                        set: { dictationManager.updateHotkey($0) }
                    )) {
                        ForEach(DictationHotkey.allCases) { hotkey in
                            Text(hotkey.label).tag(hotkey)
                        }
                    }
                    .labelsHidden()
                    .pickerStyle(.menu)
                    .frame(maxWidth: 220)
                    .accessibilityIdentifier("onboarding-verify-hotkey-picker")

                    Button(action: onConfirm) {
                        Text("Continue")
                            .font(.system(size: 13, weight: .semibold))
                            .foregroundStyle(.white)
                            .padding(.horizontal, 24)
                            .padding(.vertical, 8)
                            .background(
                                RoundedRectangle(cornerRadius: 999, style: .continuous)
                                    .fill(pressedAtLeastOnce ? Color.black : Palette.textTertiary)
                            )
                    }
                    .buttonStyle(.plain)
                    .disabled(!pressedAtLeastOnce)
                    .accessibilityIdentifier("onboarding-verify-continue")
                }
            }
            .padding(28)
            .frame(maxWidth: 540)
            .background(
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .fill(Color(NSColor.windowBackgroundColor))
            )
            .overlay(
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .strokeBorder(Palette.border, lineWidth: 1)
            )

            Spacer(minLength: 0)
        }
        .padding(.horizontal, 48)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .opacity(isActive ? 1 : 0)
        .offset(y: isActive ? 0 : 16)
        .animation(.easeOut(duration: 0.45).delay(0.1), value: isActive)
        .onAppear {
            if isActive { installLocalMonitor() }
        }
        .onDisappear { removeLocalMonitor() }
        .onChange(of: isActive) { _, newValue in
            if newValue {
                installLocalMonitor()
            } else {
                removeLocalMonitor()
                // When user navigates away from verify, drop the press flash
                // (but keep `pressedAtLeastOnce` so a partial confirmation
                // survives a quick back-and-forth).
                pressFlash = false
            }
        }
    }

    private func installLocalMonitor() {
        guard localMonitor == nil else { return }
        localMonitor = NSEvent.addLocalMonitorForEvents(matching: .flagsChanged) { event in
            let isHotkey = matchesSelectedHotkey(keyCode: event.keyCode, flags: event.modifierFlags)
            if isHotkey {
                pressFlash = true
                pressedAtLeastOnce = true
            } else if pressFlash {
                pressFlash = false
            }
            return event
        }
    }

    private func removeLocalMonitor() {
        if let monitor = localMonitor {
            NSEvent.removeMonitor(monitor)
            localMonitor = nil
        }
    }

    private func matchesSelectedHotkey(keyCode: UInt16, flags: NSEvent.ModifierFlags) -> Bool {
        let clean = flags.intersection(.deviceIndependentFlagsMask)
        switch dictationManager.selectedHotkey {
        case .rightOption:
            return keyCode == UInt16(kVK_RightOption) && clean.contains(.option)
        case .leftOption:
            return keyCode == UInt16(kVK_Option) && clean.contains(.option)
        case .rightCommand:
            return keyCode == UInt16(kVK_RightCommand) && clean.contains(.command)
        case .fn:
            return clean.contains(.function)
        case .controlOption:
            return clean.contains(.control) && clean.contains(.option)
        }
    }

    @ViewBuilder
    private var keyVisualization: some View {
        let shouldHighlight = pressFlash
        ZStack {
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .fill(shouldHighlight ? Palette.accent : Color.white)
                .frame(width: 96, height: 96)
                .shadow(color: .black.opacity(0.18), radius: 14, y: 6)
                .overlay(
                    RoundedRectangle(cornerRadius: 14, style: .continuous)
                        .strokeBorder(Color.black.opacity(0.08), lineWidth: 1)
                )
            VStack(spacing: 4) {
                Text(dictationManager.selectedHotkey.shortLabel)
                    .font(.system(size: 22, weight: .semibold))
                    .foregroundStyle(shouldHighlight ? .white : Palette.textPrimary)
            }
        }
        .animation(.easeInOut(duration: 0.12), value: shouldHighlight)
        .frame(maxWidth: .infinity)
        .padding(.vertical, 4)
    }

    @ViewBuilder
    private func keyChip(_ label: String, highlight: Bool) -> some View {
        Text(label)
            .font(.system(size: 12, weight: .medium, design: .monospaced))
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(
                RoundedRectangle(cornerRadius: 4, style: .continuous)
                    .fill(highlight ? Palette.accent.opacity(0.15) : Color.gray.opacity(0.12))
            )
    }
}
