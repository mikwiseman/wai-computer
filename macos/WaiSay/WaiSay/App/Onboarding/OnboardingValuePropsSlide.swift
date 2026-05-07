import SwiftUI

struct OnboardingValuePropsSlide: View {
    let isActive: Bool

    var body: some View {
        VStack(spacing: 32) {
            Spacer(minLength: 0)

            VStack(spacing: 8) {
                Text("Two ways to use WaiSay")
                    .font(.system(size: 30, weight: .bold))
                    .foregroundStyle(Palette.textPrimary)
                Text("Pick either or use both. You can change anytime.")
                    .font(.system(size: 14))
                    .foregroundStyle(Palette.textSecondary)
            }

            HStack(alignment: .top, spacing: 20) {
                valueCard(
                    icon: "keyboard.badge.eye",
                    title: "Dictate",
                    primary: "Voice-type into any app",
                    detail: "Hold a hotkey, speak, release. Text appears at your cursor — in Slack, Notion, Mail, anywhere."
                )
                valueCard(
                    icon: "waveform",
                    title: "Record",
                    primary: "Capture meetings & notes",
                    detail: "Hit record in WaiSay. Get a full transcript, AI summary, and action items when you're done."
                )
            }
            .frame(maxWidth: 760)

            Spacer(minLength: 0)
        }
        .padding(.horizontal, Spacing.xl)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .opacity(isActive ? 1 : 0)
        .offset(y: isActive ? 0 : 16)
        .animation(.easeOut(duration: 0.45).delay(0.1), value: isActive)
    }

    @ViewBuilder
    private func valueCard(icon: String, title: String, primary: String, detail: String) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            ZStack {
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .fill(Palette.accent.opacity(0.12))
                    .frame(width: 52, height: 52)
                Image(systemName: icon)
                    .font(.system(size: 24, weight: .regular))
                    .foregroundStyle(Palette.accent)
            }

            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(.system(size: 20, weight: .semibold))
                    .foregroundStyle(Palette.textPrimary)
                Text(primary)
                    .font(.system(size: 14, weight: .medium))
                    .foregroundStyle(Palette.textPrimary)
            }

            Text(detail)
                .font(.system(size: 13))
                .foregroundStyle(Palette.textSecondary)
                .lineSpacing(3)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(20)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .fill(Color(NSColor.windowBackgroundColor))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .strokeBorder(Palette.border, lineWidth: 1)
        )
    }
}

#Preview {
    OnboardingValuePropsSlide(isActive: true)
        .frame(width: 880, height: 580)
}
