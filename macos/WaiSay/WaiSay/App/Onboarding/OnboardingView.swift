import SwiftUI
import AVFoundation

struct OnboardingView: View {
    @EnvironmentObject var appState: MacAppState
    @EnvironmentObject var dictationManager: DictationManager
    @Environment(\.scenePhase) private var scenePhase
    @State private var currentPage: Int
    @State private var hasMicrophonePermission = OnboardingView.hasMicrophonePermission
    @State private var hasInputMonitoringPermission = GlobalHotkeyManager.hasInputMonitoringPermission
    @State private var hasPastePermission = TextInserter.hasEventPostingPermission
    @State private var inputMonitoringNeedsReview = false
    @State private var pasteNeedsReview = false
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
                            hasInputMonitoringPermission: hasInputMonitoringPermission,
                            hasPastePermission: hasPastePermission,
                            inputMonitoringNeedsReview: inputMonitoringNeedsReview,
                            pasteNeedsReview: pasteNeedsReview,
                            requestMicrophonePermission: requestMicrophonePermission,
                            requestInputMonitoringPermission: requestInputMonitoringPermission,
                            requestPastePermission: requestPastePermission,
                            openInputMonitoringSettings: openInputMonitoringSettings,
                            openPasteSettings: openPasteSettings,
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
        return "Grant Missing"
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
        hasMicrophonePermission && hasInputMonitoringPermission && hasPastePermission
    }

    private var permissionRestartRecommended: Bool {
        (inputMonitoringNeedsReview && !hasInputMonitoringPermission) ||
            (pasteNeedsReview && !hasPastePermission)
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
            hasInputMonitoringPermission = snapshot.hasInputMonitoringPermission
            hasPastePermission = snapshot.hasPastePermission
            inputMonitoringNeedsReview = snapshot.inputMonitoringNeedsReview
            pasteNeedsReview = snapshot.pasteNeedsReview
            return
        }
        #endif

        hasMicrophonePermission = Self.hasMicrophonePermission
        hasInputMonitoringPermission = GlobalHotkeyManager.hasInputMonitoringPermission
        hasPastePermission = TextInserter.hasEventPostingPermission
        if hasInputMonitoringPermission {
            inputMonitoringNeedsReview = false
        }
        if hasPastePermission {
            pasteNeedsReview = false
        }
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

    private func requestInputMonitoringPermission() {
        startPermissionPolling()
        inputMonitoringNeedsReview = true
        #if DEBUG
        if MacPermissionTesting.forcesMissingDictationPermissions {
            return
        }
        #endif
        _ = GlobalHotkeyManager.requestInputMonitoringPermission()
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) {
            refreshPermissions()
            if !hasInputMonitoringPermission {
                MacPrivacySettings.openInputMonitoring()
            }
        }
    }

    private func requestPastePermission() {
        startPermissionPolling()
        pasteNeedsReview = true
        #if DEBUG
        if MacPermissionTesting.forcesMissingDictationPermissions {
            return
        }
        #endif
        _ = TextInserter.requestEventPostingPermission()
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) {
            refreshPermissions()
            if !hasPastePermission {
                TextInserter.openEventPostingSettings()
            }
        }
    }

    private func openInputMonitoringSettings() {
        startPermissionPolling()
        inputMonitoringNeedsReview = true
        #if DEBUG
        if MacPermissionTesting.forcesMissingDictationPermissions {
            return
        }
        #endif
        _ = GlobalHotkeyManager.requestInputMonitoringPermission()
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) {
            MacPrivacySettings.openInputMonitoring()
        }
    }

    private func openPasteSettings() {
        startPermissionPolling()
        pasteNeedsReview = true
        #if DEBUG
        if MacPermissionTesting.forcesMissingDictationPermissions {
            return
        }
        #endif
        _ = TextInserter.requestEventPostingPermission()
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) {
            TextInserter.openEventPostingSettings()
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
        } else if !hasInputMonitoringPermission {
            requestInputMonitoringPermission()
        } else if !hasPastePermission {
            requestPastePermission()
        }
    }
}

private struct OnboardingPermissionSlide: View {
    @EnvironmentObject var dictationManager: DictationManager

    let isActive: Bool
    let hasMicrophonePermission: Bool
    let hasInputMonitoringPermission: Bool
    let hasPastePermission: Bool
    let inputMonitoringNeedsReview: Bool
    let pasteNeedsReview: Bool
    let requestMicrophonePermission: () -> Void
    let requestInputMonitoringPermission: () -> Void
    let requestPastePermission: () -> Void
    let openInputMonitoringSettings: () -> Void
    let openPasteSettings: () -> Void
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
                permissionRow(
                    title: "Microphone",
                    detail: "Record meetings and dictation",
                    isGranted: hasMicrophonePermission,
                    identifierBase: "onboarding-permission-microphone",
                    grantAction: requestMicrophonePermission
                )

                permissionRow(
                    title: "Input Monitoring",
                    detail: "Use the hotkey from any app",
                    isGranted: hasInputMonitoringPermission,
                    needsReview: inputMonitoringNeedsReview,
                    identifierBase: "onboarding-permission-input-monitoring",
                    grantAction: requestInputMonitoringPermission,
                    settingsAction: openInputMonitoringSettings,
                    restartAction: restartForPermissionRefresh
                )

                permissionRow(
                    title: "Automatic Paste",
                    detail: "Insert dictated text automatically",
                    isGranted: hasPastePermission,
                    needsReview: pasteNeedsReview,
                    identifierBase: "onboarding-permission-automatic-paste",
                    grantAction: requestPastePermission,
                    settingsAction: openPasteSettings,
                    restartAction: restartForPermissionRefresh
                )

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
        if (inputMonitoringNeedsReview && !hasInputMonitoringPermission) ||
            (pasteNeedsReview && !hasPastePermission) {
            return "After you turn WaiSay on in System Settings, restart WaiSay so macOS applies voice access to this running app."
        }
        return content.body
    }

    @ViewBuilder
    private func permissionRow(
        title: String,
        detail: String,
        isGranted: Bool,
        needsReview: Bool = false,
        identifierBase: String,
        grantAction: @escaping () -> Void,
        settingsAction: (() -> Void)? = nil,
        restartAction: (() -> Void)? = nil
    ) -> some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            HStack(spacing: Spacing.md) {
                Image(systemName: isGranted ? "checkmark.circle.fill" : "circle")
                    .foregroundStyle(isGranted ? .green : Palette.textTertiary)
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

                if isGranted {
                    Text("Granted")
                        .font(Typography.bodySmall)
                        .foregroundStyle(.green)
                } else if needsReview {
                    Label("Restart Required", systemImage: "arrow.clockwise.circle.fill")
                        .font(Typography.bodySmall)
                        .foregroundStyle(Palette.accent)
                        .accessibilityIdentifier("\(identifierBase)-restart-required")
                } else {
                    Button("Grant") {
                        grantAction()
                    }
                    .font(Typography.bodySmall)
                    .accessibilityIdentifier("\(identifierBase)-grant")

                    if let settingsAction {
                        Button("Settings") {
                            settingsAction()
                        }
                        .font(Typography.bodySmall)
                        .accessibilityIdentifier("\(identifierBase)-settings")
                    }
                }
            }

            if !isGranted && needsReview {
                VStack(alignment: .leading, spacing: Spacing.xs) {
                    Text(MacPrivacySettings.permissionRestartHint + " " + MacPrivacySettings.duplicatePermissionHint)
                        .font(Typography.caption)
                        .foregroundStyle(Palette.textTertiary)
                        .fixedSize(horizontal: false, vertical: true)

                    HStack(spacing: Spacing.sm) {
                        if let settingsAction {
                            Button("Settings") {
                                settingsAction()
                            }
                            .font(Typography.bodySmall)
                            .accessibilityIdentifier("\(identifierBase)-settings")
                        }

                        if let restartAction {
                            Button("Restart WaiSay") {
                                restartAction()
                            }
                            .font(Typography.bodySmall)
                            .accessibilityIdentifier("\(identifierBase)-restart")
                        }
                    }
                }
                .padding(.leading, 34)
            }
        }
        .frame(minHeight: needsReview ? 58 : 38)
    }
}
