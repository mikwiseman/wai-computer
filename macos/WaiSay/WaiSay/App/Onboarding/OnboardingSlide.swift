import SwiftUI

struct OnboardingSlide: View {
    let page: OnboardingPage
    let isActive: Bool

    private var content: OnboardingPage.Content { page.content }

    var body: some View {
        VStack(spacing: Spacing.xl) {
            Spacer(minLength: Spacing.xxxl)

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
            }
            .frame(maxWidth: 460)
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
        if content.useAppIcon {
            Image("BrandIcon")
                .resizable()
                .interpolation(.high)
                .scaledToFit()
                .frame(width: 104, height: 104)
                .shadow(color: .black.opacity(0.10), radius: 12, x: 0, y: 8)
        } else if let symbol = content.symbol {
            Image(systemName: symbol)
                .font(.system(size: 80, weight: .light))
                .foregroundStyle(Palette.accent)
                .frame(width: 104, height: 104)
        }
    }
}

#Preview("Welcome") {
    OnboardingSlide(page: .welcome, isActive: true)
        .frame(width: 720, height: 540)
}

#Preview("Dictate") {
    OnboardingSlide(page: .dictate, isActive: true)
        .frame(width: 720, height: 540)
}
