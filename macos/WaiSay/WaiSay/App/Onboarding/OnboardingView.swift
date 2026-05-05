import SwiftUI
import AVFoundation

struct OnboardingView: View {
    @EnvironmentObject var appState: MacAppState
    @EnvironmentObject var dictationManager: DictationManager
    @State private var currentPage: Int = 0
    @State private var hasMicrophonePermission = OnboardingView.hasMicrophonePermission
    @State private var hasInputMonitoringPermission = GlobalHotkeyManager.hasInputMonitoringPermission
    @State private var hasPastePermission = TextInserter.hasEventPostingPermission
    @State private var permissionPollTimer: Timer?

    private let pages = OnboardingPage.allCases

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
        .accessibilityIdentifier("onboarding-view")
        .onAppear {
            refreshPermissions()
            startPermissionPollingIfNeeded()
        }
        .onDisappear(perform: stopPermissionPolling)
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
                            requestMicrophonePermission: requestMicrophonePermission,
                            requestInputMonitoringPermission: requestInputMonitoringPermission,
                            requestPastePermission: requestPastePermission
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
            if !isLastPage {
                Button("Skip") {
                    withAnimation(.easeInOut(duration: 0.3)) {
                        currentPage = pages.count - 1
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
        isLastPage ? (dictationPermissionsReady ? "Get Started" : "Finish Setup") : "Continue"
    }

    private var primaryButtonAccessibilityId: String {
        return isLastPage ? "onboarding-get-started-button" : "onboarding-continue-button"
    }

    private func handlePrimaryTap() {
        if isLastPage {
            UserDefaults.standard.set(hasMicrophonePermission, forKey: MacAppState.onboardingMicAcknowledgedKey)
            appState.completeOnboarding()
        } else {
            withAnimation(.easeInOut(duration: 0.3)) {
                currentPage += 1
            }
        }
    }

    private var dictationPermissionsReady: Bool {
        #if SPARKLE
        hasMicrophonePermission && hasInputMonitoringPermission && hasPastePermission
        #else
        hasMicrophonePermission && hasInputMonitoringPermission
        #endif
    }

    private static var hasMicrophonePermission: Bool {
        AVCaptureDevice.authorizationStatus(for: .audio) == .authorized
    }

    private func refreshPermissions() {
        hasMicrophonePermission = Self.hasMicrophonePermission
        hasInputMonitoringPermission = GlobalHotkeyManager.hasInputMonitoringPermission
        hasPastePermission = TextInserter.hasEventPostingPermission
        dictationManager.refreshPermissionState()
        if dictationPermissionsReady {
            stopPermissionPolling()
        }
    }

    private func requestMicrophonePermission() {
        startPermissionPolling()
        Task {
            _ = await AVAudioApplication.requestRecordPermission()
            await MainActor.run {
                refreshPermissions()
            }
        }
    }

    private func requestInputMonitoringPermission() {
        startPermissionPolling()
        _ = GlobalHotkeyManager.requestInputMonitoringPermission()
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) {
            refreshPermissions()
            if !hasInputMonitoringPermission {
                MacPrivacySettings.openInputMonitoring()
            }
        }
    }

    private func requestPastePermission() {
        startPermissionPolling()
        _ = TextInserter.requestEventPostingPermission()
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) {
            refreshPermissions()
            if !hasPastePermission {
                TextInserter.openEventPostingSettings()
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
}

private struct OnboardingPermissionSlide: View {
    @EnvironmentObject var dictationManager: DictationManager

    let isActive: Bool
    let hasMicrophonePermission: Bool
    let hasInputMonitoringPermission: Bool
    let hasPastePermission: Bool
    let requestMicrophonePermission: () -> Void
    let requestInputMonitoringPermission: () -> Void
    let requestPastePermission: () -> Void

    private var content: OnboardingPage.Content { OnboardingPage.permission.content }

    var body: some View {
        VStack(spacing: Spacing.md) {
            Spacer(minLength: Spacing.md)

            Image(systemName: content.symbol ?? "lock.shield")
                .font(.system(size: 54, weight: .light))
                .foregroundStyle(Palette.accent)
                .frame(width: 68, height: 68)

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

                Text(content.body)
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
                    grantAction: requestMicrophonePermission
                )

                permissionRow(
                    title: "Input Monitoring",
                    detail: "Use the hotkey from any app",
                    isGranted: hasInputMonitoringPermission,
                    grantAction: requestInputMonitoringPermission,
                    settingsAction: MacPrivacySettings.openInputMonitoring
                )

                #if SPARKLE
                permissionRow(
                    title: "Paste Permission",
                    detail: "Insert dictated text automatically",
                    isGranted: hasPastePermission,
                    grantAction: requestPastePermission,
                    settingsAction: TextInserter.openEventPostingSettings
                )
                #endif

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

    @ViewBuilder
    private func permissionRow(
        title: String,
        detail: String,
        isGranted: Bool,
        grantAction: @escaping () -> Void,
        settingsAction: (() -> Void)? = nil
    ) -> some View {
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
            } else {
                Button("Grant") {
                    grantAction()
                }
                .font(Typography.bodySmall)

                if let settingsAction {
                    Button("Open Settings") {
                        settingsAction()
                    }
                    .font(Typography.bodySmall)
                }
            }
        }
        .frame(minHeight: 38)
    }
}
