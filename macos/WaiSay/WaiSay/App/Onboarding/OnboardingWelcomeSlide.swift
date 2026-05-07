import SwiftUI

struct OnboardingWelcomeSlide: View {
    let isActive: Bool

    var body: some View {
        VStack(spacing: 24) {
            Spacer(minLength: 0)

            Image("BrandIcon")
                .resizable()
                .interpolation(.high)
                .scaledToFit()
                .frame(width: 104, height: 104)
                .shadow(color: .black.opacity(0.10), radius: 12, x: 0, y: 8)
                .opacity(isActive ? 1 : 0)
                .offset(y: isActive ? 0 : 12)
                .animation(.easeOut(duration: 0.45).delay(0.05), value: isActive)

            VStack(spacing: 12) {
                Text("Welcome to WaiSay")
                    .font(.system(size: 32, weight: .bold))
                    .foregroundStyle(Palette.textPrimary)
                Text("Voice-type into any app and capture meetings — set up in 90 seconds.")
                    .font(.system(size: 15))
                    .foregroundStyle(Palette.textSecondary)
                    .multilineTextAlignment(.center)
                    .lineSpacing(3)
                    .frame(maxWidth: 520)
            }
            .opacity(isActive ? 1 : 0)
            .offset(y: isActive ? 0 : 16)
            .animation(.easeOut(duration: 0.45).delay(0.12), value: isActive)

            Spacer()
        }
        .padding(.horizontal, Spacing.xl)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

#Preview {
    OnboardingWelcomeSlide(isActive: true)
        .frame(width: 880, height: 580)
}
