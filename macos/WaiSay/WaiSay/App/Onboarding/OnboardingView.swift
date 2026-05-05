import SwiftUI

struct OnboardingView: View {
    @EnvironmentObject var appState: MacAppState
    @State private var currentPage: Int = 0
    @State private var permissionRequested = false

    private let pages = OnboardingPage.allCases

    private var currentPageEnum: OnboardingPage { pages[currentPage] }
    private var isLastPage: Bool { currentPage == pages.count - 1 }
    private var isPermissionPage: Bool { currentPageEnum == .permission }

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
        .frame(minWidth: 720, minHeight: 540)
        .background(Color(NSColor.windowBackgroundColor).ignoresSafeArea())
        .accessibilityIdentifier("onboarding-view")
    }

    // MARK: - Slide area

    private var slideArea: some View {
        GeometryReader { geo in
            HStack(spacing: 0) {
                ForEach(pages.indices, id: \.self) { index in
                    OnboardingSlide(page: pages[index], isActive: index == currentPage)
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
            // On macOS, calling AVCaptureDevice.requestAccess(for: .audio) here
            // would write a TCC entry without the user actually exercising the
            // microphone, which the system can flag. Instead we record intent
            // and let the real system prompt fire on the first capture attempt.
            UserDefaults.standard.set(true, forKey: MacAppState.onboardingMicAcknowledgedKey)
            permissionRequested = true
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
}
