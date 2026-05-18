import SwiftUI
import UIKit

struct OnboardingView: View {
    @EnvironmentObject var appState: AppState
    @State private var currentPage: Int = 0
    @State private var permissionRequested = false
    @State private var isRequestingPermission = false

    private let pages = OnboardingPage.allCases
    private let haptic = UIImpactFeedbackGenerator(style: .light)

    private var currentPageEnum: OnboardingPage { pages[currentPage] }
    private var isLastPage: Bool { currentPage == pages.count - 1 }
    private var isPermissionPage: Bool { currentPageEnum == .permission }
    private var isVoiceSetupPage: Bool { currentPageEnum == .voiceSetup }

    var body: some View {
        VStack(spacing: 0) {
            slideArea
                .frame(maxWidth: .infinity, maxHeight: .infinity)

            VStack(spacing: Spacing.lg) {
                pageIndicator
                footerControls
            }
            .padding(.horizontal, Spacing.xl)
            .padding(.bottom, Spacing.xl)
            .padding(.top, Spacing.md)
        }
        .background(Color(uiColor: .systemBackground).ignoresSafeArea())
        .accessibilityIdentifier("onboarding-view")
        .onAppear { haptic.prepare() }
    }

    // MARK: - Slide area

    private var slideArea: some View {
        TabView(selection: $currentPage) {
            ForEach(pages.indices, id: \.self) { index in
                Group {
                    if pages[index] == .voiceSetup {
                        OnboardingVoiceSetupSlide(
                            isActive: index == currentPage,
                            onAdvance: advanceToNextPage
                        )
                    } else {
                        OnboardingSlide(page: pages[index], isActive: index == currentPage)
                    }
                }
                .tag(index)
            }
        }
        .tabViewStyle(.page(indexDisplayMode: .never))
        .onChange(of: currentPage) { _, _ in
            haptic.impactOccurred()
            // Reset permission state when leaving the permission page so the
            // user can revisit it cleanly via swipe back.
            if !isPermissionPage { permissionRequested = false }
        }
    }

    private func advanceToNextPage() {
        withAnimation(.easeInOut(duration: 0.3)) {
            currentPage = min(currentPage + 1, pages.count - 1)
        }
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
        // Voice setup screen ships its own primary/skip controls (record, re-record,
        // submit, skip). Hiding this footer prevents two competing CTAs.
        if isVoiceSetupPage {
            EmptyView()
        } else {
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
        if isPermissionPage && !permissionRequested {
            return "Allow microphone"
        }
        return isLastPage ? "Get Started" : "Continue"
    }

    private var primaryButtonAccessibilityId: String {
        if isPermissionPage && !permissionRequested {
            return "onboarding-allow-mic-button"
        }
        return isLastPage ? "onboarding-get-started-button" : "onboarding-continue-button"
    }

    private func handlePrimaryTap() {
        if isPermissionPage && !permissionRequested {
            requestMicrophonePermission()
            return
        }

        if isLastPage {
            appState.completeOnboarding()
        } else {
            withAnimation(.easeInOut(duration: 0.3)) {
                currentPage += 1
            }
        }
    }

    private func requestMicrophonePermission() {
        isRequestingPermission = true
        Task {
            _ = await AudioManager.shared.requestPermission()
            await MainActor.run {
                permissionRequested = true
                isRequestingPermission = false
            }
        }
    }
}

#Preview {
    OnboardingView()
        .environmentObject(AppState())
}
