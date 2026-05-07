import SwiftUI

/// Onboarding language picker slide. Sits between Allow and Hotkey so the
/// user can narrow STT to specific languages (lower latency, fewer
/// false-positive switches) or leave on auto-detect (multi). Reuses the
/// LanguagePickerView from Settings — single source of truth.
struct OnboardingLanguagesSlide: View {
    let isActive: Bool
    @ObservedObject var store: DictationLanguageStore

    var body: some View {
        VStack(spacing: 24) {
            Spacer(minLength: 0)

            VStack(spacing: 10) {
                Text("Pick your languages")
                    .font(.system(size: 30, weight: .bold))
                    .foregroundStyle(Palette.textPrimary)
                Text("One for the lowest latency, several to switch fluidly, or auto-detect any language. You can change this later in Settings.")
                    .font(.system(size: 14))
                    .foregroundStyle(Palette.textSecondary)
                    .multilineTextAlignment(.center)
                    .lineSpacing(3)
                    .frame(maxWidth: 540)
            }

            ScrollView {
                LanguagePickerView(store: store)
                    .padding(.horizontal, 4)
            }
            .frame(maxWidth: 520, maxHeight: 360)
            .padding(20)
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
        .padding(.horizontal, Spacing.xl)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .opacity(isActive ? 1 : 0)
        .offset(y: isActive ? 0 : 16)
        .animation(.easeOut(duration: 0.45).delay(0.1), value: isActive)
    }
}
