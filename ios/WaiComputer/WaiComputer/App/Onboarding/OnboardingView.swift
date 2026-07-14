import SwiftUI
import AVFoundation
import UIKit
import WaiComputerKit

struct OnboardingView: View {
    @EnvironmentObject var appState: AppState
    @EnvironmentObject private var languageManager: LanguageManager
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass

    @State private var currentPage: Int
    @State private var permissionRequested = false
    @State private var isRequestingPermission = false
    @State private var microphoneStatus: AVAudioApplication.recordPermission =
        AVAudioApplication.shared.recordPermission
    @State private var permissionPollTimer: Timer?

    /// Persists which page the user reached, so relaunching mid-onboarding
    /// resumes where they left off. Cleared when onboarding completes. Mirrors
    /// macOS `OnboardingView` page-progress resume.
    static let currentPageKey = "iosOnboardingCurrentPage"

    private let pages = OnboardingPage.allCases
    private let haptic = UIImpactFeedbackGenerator(style: .light)

    init() {
        _currentPage = State(initialValue: Self.initialCurrentPage())
    }

    private var currentPageEnum: OnboardingPage { pages[currentPage] }
    private var isLastPage: Bool { currentPage == pages.count - 1 }
    private var isPermissionPage: Bool { currentPageEnum == .permission }
    private var isVoiceSetupPage: Bool { currentPageEnum == .voiceSetup }
    private var hasMicrophonePermission: Bool { microphoneStatus == .granted }
    private var canSkipCurrentPage: Bool {
        OnboardingPermissionGate.canSkip(
            from: currentPageEnum,
            hasMicrophonePermission: hasMicrophonePermission
        )
    }

    var body: some View {
        onboardingContent
        .background(Color(uiColor: .systemBackground).ignoresSafeArea())
        .accessibilityIdentifier("onboarding-view")
        .onAppear {
            haptic.prepare()
            currentPage = Self.clampedPageIndex(currentPage, pageCount: pages.count)
            refreshMicrophoneStatus()
            _ = applyPermissionGate()
            persistCurrentPage()
            startPermissionPollingIfNeeded()
        }
        .onDisappear(perform: stopPermissionPolling)
        .onChange(of: currentPage) { _, _ in
            if applyPermissionGate() {
                return
            }
            haptic.impactOccurred()
            persistCurrentPage()
            // Reset permission state when leaving the permission page so the
            // user can revisit it cleanly via swipe back.
            if !isPermissionPage {
                permissionRequested = false
                stopPermissionPolling()
            } else {
                refreshMicrophoneStatus()
                startPermissionPollingIfNeeded()
            }
        }
        .onChange(of: scenePhase) { _, newPhase in
            // Returning from Settings (where the user may have flipped the
            // mic switch) must re-read the live status and resume the poll.
            if newPhase == .active {
                refreshMicrophoneStatus()
                _ = applyPermissionGate()
                startPermissionPollingIfNeeded()
            }
        }
    }

    @ViewBuilder
    private var onboardingContent: some View {
        if horizontalSizeClass == .regular {
            regularOnboardingLayout
        } else {
            compactOnboardingLayout
        }
    }

    private var compactOnboardingLayout: some View {
        VStack(spacing: 0) {
            slideArea
                .frame(maxWidth: .infinity, maxHeight: .infinity)

            VStack(spacing: Spacing.lg) {
                if isPermissionPage {
                    permissionStatusView
                }
                pageIndicator(isRegular: false)
                footerControls
            }
            .padding(.horizontal, Spacing.xl)
            .padding(.bottom, Spacing.xl)
            .padding(.top, Spacing.md)
        }
        .accessibilityIdentifier("onboarding-compact-layout")
    }

    private var regularOnboardingLayout: some View {
        VStack(spacing: Spacing.lg) {
            pageIndicator(isRegular: true)
                .padding(.top, Spacing.lg)

            regularSlidePanel

            regularFooterPanel
                .padding(.bottom, Spacing.xl)
        }
        .padding(.horizontal, Spacing.huge)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .accessibilityIdentifier("onboarding-regular-layout")
    }

    private var regularSlidePanel: some View {
        slideArea
            .frame(maxWidth: 760)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .accessibilityIdentifier("onboarding-regular-slide-panel")
    }

    private var regularFooterPanel: some View {
        VStack(spacing: Spacing.md) {
            if isPermissionPage {
                permissionStatusView
            }
            footerControls
        }
        .frame(maxWidth: 760)
        .accessibilityIdentifier("onboarding-regular-footer-panel")
    }

    // MARK: - Slide area

    private var slideArea: some View {
        TabView(selection: $currentPage) {
            ForEach(pages.indices, id: \.self) { index in
                Group {
                    if pages[index] == .voiceSetup {
                        OnboardingVoiceSetupSlide(
                            isActive: index == currentPage,
                            hasMicrophonePermission: hasMicrophonePermission,
                            onAdvance: completeOnboarding
                        )
                    } else {
                        OnboardingSlide(page: pages[index], isActive: index == currentPage)
                    }
                }
                .tag(index)
            }
        }
        .tabViewStyle(.page(indexDisplayMode: .never))
    }

    private func advanceToNextPage() {
        withAnimation(.easeInOut(duration: 0.3)) {
            currentPage = min(currentPage + 1, pages.count - 1)
        }
    }

    // MARK: - Page indicator

    /// Breadcrumb label + chevron indicator (mirrors macOS), localized to the
    /// in-app language. Replaces the capsule-dot indicator.
    @ViewBuilder
    private func pageIndicator(isRegular: Bool) -> some View {
        if isRegular {
            pageIndicatorRow(isRegular: true)
                .frame(maxWidth: .infinity)
                .accessibilityIdentifier("onboarding-page-indicator")
        } else {
            ScrollView(.horizontal, showsIndicators: false) {
                pageIndicatorRow(isRegular: false)
                    .padding(.horizontal, Spacing.xl)
            }
            .frame(maxWidth: .infinity)
            .accessibilityIdentifier("onboarding-page-indicator")
        }
    }

    private func pageIndicatorRow(isRegular: Bool) -> some View {
        HStack(spacing: isRegular ? 6 : Spacing.xs) {
            ForEach(pages.indices, id: \.self) { index in
                if index > 0 {
                    Image(systemName: "chevron.right")
                        .font(.system(size: isRegular ? 10 : 9, weight: .medium))
                        .foregroundStyle(Palette.textTertiary.opacity(0.5))
                }
                VStack(spacing: isRegular ? 6 : 5) {
                    Text(pages[index].breadcrumbLabel(language: languageManager.current).uppercased())
                        .font(.system(size: isRegular ? 11 : 10, weight: .medium))
                        .tracking(isRegular ? 1.3 : 1.1)
                        .foregroundStyle(index == currentPage ? Palette.textPrimary : Palette.textTertiary)
                        .lineLimit(1)
                        .fixedSize(horizontal: true, vertical: false)
                    Rectangle()
                        .fill(index == currentPage ? Palette.accent : Color.clear)
                        .frame(height: 1.5)
                }
                .padding(.horizontal, isRegular ? Spacing.md : Spacing.sm)
                .animation(.easeInOut(duration: 0.25), value: currentPage)
            }
        }
    }

    // MARK: - Permission status feedback

    @ViewBuilder
    private var permissionStatusView: some View {
        if permissionRequested || hasMicrophonePermission {
            switch microphoneStatus {
            case .granted:
                Label(
                    t("Microphone enabled", "Микрофон включен"),
                    systemImage: "checkmark.circle.fill"
                )
                .font(Typography.label)
                .foregroundStyle(Palette.success)
                .accessibilityIdentifier("onboarding-mic-status-granted")
            case .denied:
                VStack(spacing: Spacing.sm) {
                    Label(
                        t("Microphone access denied", "Доступ к микрофону запрещен"),
                        systemImage: "exclamationmark.triangle.fill"
                    )
                    .font(Typography.label)
                    .foregroundStyle(Palette.danger)
                    Button(t("Open Settings", "Открыть настройки"), action: openSystemSettings)
                        .buttonStyle(WaiGhostButtonStyle())
                        .accessibilityIdentifier("onboarding-mic-open-settings")
                }
                .accessibilityIdentifier("onboarding-mic-status-denied")
            default:
                EmptyView()
            }
        }
    }

    // MARK: - Footer

    @ViewBuilder
    private var footerControls: some View {
        // Voice setup screen ships its own primary/skip controls (record, re-record,
        // submit, skip). Hiding this footer prevents two competing CTAs.
        if isVoiceSetupPage {
            EmptyView()
        } else {
            HStack {
                if !isLastPage, canSkipCurrentPage {
                    Button(t("Skip", "Пропустить")) {
                        withAnimation(.easeInOut(duration: 0.3)) {
                            currentPage = OnboardingPermissionGate.skipDestination(
                                from: currentPageEnum,
                                hasMicrophonePermission: hasMicrophonePermission
                            ).rawValue
                        }
                    }
                    .buttonStyle(WaiGhostButtonStyle())
                    .accessibilityIdentifier("onboarding-skip-button")
                } else {
                    Spacer().frame(width: 1)
                }

                Spacer()

                primaryButton
            }
        }
    }

    private var primaryButton: some View {
        Button(action: handlePrimaryTap) {
            HStack(spacing: Spacing.xs) {
                if isRequestingPermission {
                    ProgressView()
                        .tint(.white)
                        .scaleEffect(0.8)
                }
                Text(primaryButtonTitle)
            }
            .frame(minWidth: 140)
        }
        .buttonStyle(WaiPrimaryButtonStyle())
        .disabled(isRequestingPermission)
        .accessibilityIdentifier(primaryButtonAccessibilityId)
    }

    private var primaryButtonTitle: String {
        if isPermissionPage && !hasMicrophonePermission && microphoneStatus == .undetermined {
            return t("Allow microphone", "Разрешить микрофон")
        }
        return isLastPage
            ? t("Get Started", "Начать")
            : t("Continue", "Продолжить")
    }

    private var primaryButtonAccessibilityId: String {
        if isPermissionPage && !hasMicrophonePermission && microphoneStatus == .undetermined {
            return "onboarding-allow-mic-button"
        }
        return isLastPage ? "onboarding-get-started-button" : "onboarding-continue-button"
    }

    private func handlePrimaryTap() {
        if isPermissionPage && !hasMicrophonePermission && microphoneStatus == .undetermined {
            requestMicrophonePermission()
            return
        }

        if isLastPage {
            completeOnboarding()
        } else {
            withAnimation(.easeInOut(duration: 0.3)) {
                currentPage += 1
            }
        }
    }

    private func completeOnboarding() {
        // Record whether the mic was acknowledged at completion so the rest of
        // the app can skip a redundant permission nudge. Mirrors macOS.
        UserDefaults.standard.set(hasMicrophonePermission, forKey: IOSOnboardingKeys.micAcknowledged)
        UserDefaults.standard.removeObject(forKey: Self.currentPageKey)
        appState.completeOnboarding()
    }

    private func requestMicrophonePermission() {
        isRequestingPermission = true
        startPermissionPolling()
        Task {
            let granted = await AudioManager.shared.requestPermission()
            await MainActor.run {
                permissionRequested = true
                isRequestingPermission = false
                refreshMicrophoneStatus()
                if granted {
                    // Permission acquired — move straight to the next step.
                    advanceToNextPage()
                }
                // On denial we keep the user on the page; permissionStatusView
                // surfaces the denied state + an Open Settings affordance.
            }
        }
    }

    private func openSystemSettings() {
        guard let url = URL(string: UIApplication.openSettingsURLString) else { return }
        UIApplication.shared.open(url)
    }

    // MARK: - Permission status + polling

    private func refreshMicrophoneStatus() {
        let status = AVAudioApplication.shared.recordPermission
        microphoneStatus = status
        if status == .granted {
            stopPermissionPolling()
        }
    }

    @discardableResult
    private func applyPermissionGate() -> Bool {
        let gatedPage = OnboardingPermissionGate.gatedPage(
            current: currentPageEnum,
            hasMicrophonePermission: hasMicrophonePermission
        )
        guard gatedPage.rawValue != currentPage else { return false }
        currentPage = gatedPage.rawValue
        return true
    }

    /// Poll the live mic authorization once per second while the user is on the
    /// permission page and has not yet granted. Catches the case where the user
    /// flips the switch in Settings and returns, and auto-advances on grant.
    private func startPermissionPollingIfNeeded() {
        guard isPermissionPage, !hasMicrophonePermission else { return }
        startPermissionPolling()
    }

    private func startPermissionPolling() {
        stopPermissionPolling()
        permissionPollTimer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { _ in
            Task { @MainActor in
                let wasGranted = hasMicrophonePermission
                refreshMicrophoneStatus()
                if !wasGranted, hasMicrophonePermission, isPermissionPage {
                    advanceToNextPage()
                }
            }
        }
    }

    private func stopPermissionPolling() {
        permissionPollTimer?.invalidate()
        permissionPollTimer = nil
    }

    // MARK: - Page-progress resume

    private static func initialCurrentPage() -> Int {
        let stored = UserDefaults.standard.integer(forKey: currentPageKey)
        return clampedPageIndex(stored, pageCount: OnboardingPage.allCases.count)
    }

    private static func clampedPageIndex(_ value: Int, pageCount: Int) -> Int {
        min(max(value, 0), max(pageCount - 1, 0))
    }

    private func persistCurrentPage() {
        UserDefaults.standard.set(
            Self.clampedPageIndex(currentPage, pageCount: pages.count),
            forKey: Self.currentPageKey
        )
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

enum OnboardingPermissionGate {
    static func gatedPage(
        current: OnboardingPage,
        hasMicrophonePermission: Bool
    ) -> OnboardingPage {
        if !hasMicrophonePermission, current.rawValue > OnboardingPage.permission.rawValue {
            return .permission
        }
        return current
    }

    static func skipDestination(
        from current: OnboardingPage,
        hasMicrophonePermission: Bool
    ) -> OnboardingPage {
        if !hasMicrophonePermission, current.rawValue < OnboardingPage.permission.rawValue {
            return .permission
        }
        return .voiceSetup
    }

    static func canSkip(
        from current: OnboardingPage,
        hasMicrophonePermission: Bool
    ) -> Bool {
        current != .permission || hasMicrophonePermission
    }
}

/// UserDefaults keys shared with the rest of the iOS app. The mic-acknowledged
/// key matches the macOS key string so behavior is consistent cross-platform.
enum IOSOnboardingKeys {
    static let micAcknowledged = "onboardingMicAcknowledged"
}

#Preview {
    OnboardingView()
        .environmentObject(AppState())
        .environmentObject(LanguageManager.shared)
}
