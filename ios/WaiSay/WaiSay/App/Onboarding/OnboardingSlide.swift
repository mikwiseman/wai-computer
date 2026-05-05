import SwiftUI

struct OnboardingSlide: View {
    let page: OnboardingPage
    let isActive: Bool

    private var content: OnboardingPage.Content { page.content }

    var body: some View {
        VStack(spacing: Spacing.xl) {
            Spacer(minLength: Spacing.huge)

            iconView
                .opacity(isActive ? 1 : 0)
                .offset(y: isActive ? 0 : 12)
                .animation(.easeOut(duration: 0.45).delay(0.05), value: isActive)

            VStack(spacing: Spacing.md) {
                Text(content.eyebrow.uppercased())
                    .font(Typography.labelSmall)
                    .tracking(1.6)
                    .foregroundStyle(Palette.accent)

                Text(content.title)
                    .font(Typography.displayMedium)
                    .multilineTextAlignment(.center)
                    .foregroundStyle(Palette.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)

                Text(content.body)
                    .font(Typography.bodyLarge)
                    .lineSpacing(4)
                    .multilineTextAlignment(.center)
                    .foregroundStyle(Palette.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.horizontal, Spacing.xs)
            }
            .opacity(isActive ? 1 : 0)
            .offset(y: isActive ? 0 : 16)
            .animation(.easeOut(duration: 0.45).delay(0.12), value: isActive)

            Spacer()
        }
        .padding(.horizontal, Spacing.xl)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    @ViewBuilder
    private var iconView: some View {
        if content.useTriangleIcon {
            WaiTriangleIcon(size: 96)
        } else if let symbol = content.symbol {
            Image(systemName: symbol)
                .font(.system(size: 72, weight: .light))
                .foregroundStyle(Palette.accent)
                .frame(width: 96, height: 96)
        }
    }
}

#Preview("Welcome") {
    OnboardingSlide(page: .welcome, isActive: true)
}

#Preview("Permission") {
    OnboardingSlide(page: .permission, isActive: true)
}
