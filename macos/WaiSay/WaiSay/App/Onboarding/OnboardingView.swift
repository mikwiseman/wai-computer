import SwiftUI
import AVFoundation

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
            slideArea

            VStack(spacing: Spacing.lg) {
                pageIndicator
                footerControls
            }
            .padding(.horizontal, Spacing.xxl)
            .padding(.bottom, Spacing.xxl)
            .padding(.top, Spacing.lg)
        }
        .frame(minWidth: 760, minHeight: 620)
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
        HStack(spacing: Spacing.sm) {
            ForEach(pages.indices, id: \.self) { index in
                Capsule()
                    .fill(index == currentPage ? Palette.accent : Palette.border)
                    .frame(width: index == currentPage ? 22 : 6, height: 6)
                    .animation(.easeInOut(duration: 0.25), value: currentPage)
            }
        }
        .accessibilityIdentifier("onboarding-page-indicator")
    }

    // MARK: - Footer

    @ViewBuilder
    private var footerControls: some View {
        HStack {
            if !isLastPage || !dictationPermissionsReady {
                Button(isLastPage ? "Skip for Now" : "Skip") {
                    if isLastPage {
                        completeOnboarding()
                    } else {
                        withAnimation(.easeInOut(duration: 0.3)) {
                            currentPage = pages.count - 1
                        }
                    }
                }
                .buttonStyle(WaiGhostButtonStyle())
                .accessibilityIdentifier("onboarding-skip-button")
            } else {
                Spacer().frame(width: 1)
            }

            Spacer()

            Button(action: handlePrimaryTap) {
                Text(primaryButtonTitle)
                    .frame(minWidth: 160)
            }
            .buttonStyle(WaiPrimaryButtonStyle(isDisabled: false))
            .accessibilityIdentifier(primaryButtonAccessibilityId)
            .keyboardShortcut(.defaultAction)
        }
    }

    private var primaryButtonTitle: String {
        guard isLastPage else { return "Continue" }
        if dictationPermissionsReady {
            return "Get Started"
        }
        if permissionRestartRecommended {
            return "Restart WaiSay"
        }
        return "Open Settings"
    }

    private var primaryButtonAccessibilityId: String {
        return isLastPage ? "onboarding-get-started-button" : "onboarding-continue-button"
    }

    private func handlePrimaryTap() {
        if isLastPage {
            refreshPermissions()
            if dictationPermissionsReady {
                completeOnboarding()
            } else if permissionRestartRecommended {
                MacPrivacySettings.restartForPermissionRefresh()
            } else {
                requestNextMissingPermission()
            }
        } else {
            withAnimation(.easeInOut(duration: 0.3)) {
                currentPage += 1
            }
        }
    }

    private func completeOnboarding() {
        UserDefaults.standard.set(hasMicrophonePermission, forKey: MacAppState.onboardingMicAcknowledgedKey)
        appState.completeOnboarding()
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
        VStack(spacing: Spacing.md) {
            Spacer(minLength: Spacing.md)

            Image("BrandIcon")
                .resizable()
                .interpolation(.high)
                .scaledToFit()
                .frame(width: 76, height: 76)

            VStack(spacing: Spacing.xs) {
                Text(content.eyebrow.uppercased())
                    .font(Typography.labelSmall)
                    .tracking(1.6)
                    .foregroundStyle(Palette.accent)

                Text(content.title)
                    .font(Typography.displaySmall)
                    .multilineTextAlignment(.center)
                    .foregroundStyle(Palette.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)

                Text(permissionBody)
                    .font(Typography.body)
                    .lineSpacing(3)
                    .multilineTextAlignment(.center)
                    .foregroundStyle(Palette.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .frame(maxWidth: 520)

            VStack(spacing: Spacing.sm) {
                microphoneRow
                inputMonitoringRow
                automaticPasteRow

                HStack {
                    Toggle("Enable Dictation", isOn: Binding(
                        get: { dictationManager.isFeatureEnabled },
                        set: { dictationManager.updateEnabled($0) }
                    ))
                    .font(Typography.body)

                    Spacer()

                    Picker("Hotkey", selection: Binding(
                        get: { dictationManager.selectedHotkey },
                        set: { dictationManager.updateHotkey($0) }
                    )) {
                        ForEach(DictationHotkey.allCases) { hotkey in
                            Text(hotkey.label).tag(hotkey)
                        }
                    }
                    .labelsHidden()
                    .frame(width: 180)
                    .disabled(!dictationManager.isFeatureEnabled)
                }
                .padding(.vertical, Spacing.sm)
            }
            .padding(Spacing.md)
            .frame(maxWidth: 560)
            .background(Palette.surfaceSubtle)
            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))

            Spacer(minLength: Spacing.md)
        }
        .padding(.horizontal, Spacing.xl)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .opacity(isActive ? 1 : 0)
        .offset(y: isActive ? 0 : 16)
        .animation(.easeOut(duration: 0.45).delay(0.1), value: isActive)
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
        VStack(alignment: .leading, spacing: Spacing.xs) {
            HStack(spacing: Spacing.md) {
                statusIcon
                    .frame(width: 22)

                VStack(alignment: .leading, spacing: 2) {
                    Text(title)
                        .font(Typography.body)
                        .foregroundStyle(Palette.textPrimary)
                    Text(detail)
                        .font(Typography.caption)
                        .foregroundStyle(Palette.textSecondary)
                }

                Spacer()

                trailingControls
            }

            if status == .staleNeedsRestart {
                Text(MacPrivacySettings.permissionRestartHint + " " + MacPrivacySettings.duplicatePermissionHint)
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.leading, 34)
            }
        }
        .frame(minHeight: status == .staleNeedsRestart ? 58 : 38)
    }

    @ViewBuilder
    private var statusIcon: some View {
        switch status {
        case .granted:
            Image(systemName: "checkmark.circle.fill")
                .foregroundStyle(.green)
        case .denied:
            Image(systemName: "circle")
                .foregroundStyle(Palette.textTertiary)
        case .staleNeedsRestart:
            Image(systemName: "arrow.clockwise.circle.fill")
                .foregroundStyle(Palette.accent)
        }
    }

    @ViewBuilder
    private var trailingControls: some View {
        if status == .granted {
            Text("Granted")
                .font(Typography.bodySmall)
                .foregroundStyle(.green)
        } else if status == .staleNeedsRestart {
            HStack(spacing: Spacing.sm) {
                Text("Restart Required")
                    .font(Typography.bodySmall)
                    .foregroundStyle(Palette.accent)
                    .accessibilityIdentifier("\(identifierBase)-restart-required")

                if let secondaryAction {
                    Button(secondaryAction.label) { secondaryAction.run() }
                        .font(Typography.bodySmall)
                        .accessibilityIdentifier("\(identifierBase)-\(secondaryAction.identifier)")
                }

                if let restartAction {
                    Button(restartAction.label) { restartAction.run() }
                        .font(Typography.bodySmall)
                        .accessibilityIdentifier("\(identifierBase)-\(restartAction.identifier)")
                }
            }
        } else {
            HStack(spacing: Spacing.sm) {
                if let primaryAction {
                    Button(primaryAction.label) { primaryAction.run() }
                        .font(Typography.bodySmall)
                        .accessibilityIdentifier("\(identifierBase)-\(primaryAction.identifier)")
                }
                if let secondaryAction {
                    Button(secondaryAction.label) { secondaryAction.run() }
                        .font(Typography.bodySmall)
                        .accessibilityIdentifier("\(identifierBase)-\(secondaryAction.identifier)")
                }
                if let recheckAction {
                    Button(recheckAction.label) { recheckAction.run() }
                        .font(Typography.bodySmall)
                        .accessibilityIdentifier("\(identifierBase)-\(recheckAction.identifier)")
                }
            }
        }
    }
}
