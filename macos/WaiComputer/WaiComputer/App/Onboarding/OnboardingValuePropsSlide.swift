import SwiftUI
import WaiComputerKit

struct OnboardingValuePropsSlide: View {
    let isActive: Bool
    @EnvironmentObject private var languageManager: LanguageManager

    var body: some View {
        VStack(spacing: 32) {
            Spacer(minLength: 0)

            VStack(spacing: 8) {
                Text(t("Two ways to use WaiComputer", "WaiComputer помогает в двух сценариях"))
                    .font(.system(size: 30, weight: .bold))
                    .foregroundStyle(Palette.textPrimary)
                Text(t("Pick either or use both. You can change anytime.", "Можно включить один сценарий или оба. Настройки всегда можно изменить."))
                    .font(.system(size: 14))
                    .foregroundStyle(Palette.textSecondary)
            }

            HStack(alignment: .top, spacing: 20) {
                valueCard(
                    icon: "keyboard.badge.eye",
                    title: t("Dictate", "Диктовка"),
                    primary: t("Voice-type into any app", "Пиши голосом в любом приложении"),
                    detail: t(
                        "Hold a hotkey, speak, release. Text appears at your cursor — in Slack, Notion, Mail, anywhere.",
                        "Зажми горячую клавишу, произнеси фразу и отпусти. Текст появится там, где стоит курсор: в Slack, Notion, Mail и других приложениях."
                    )
                )
                valueCard(
                    icon: "waveform",
                    title: t("Record", "Запись"),
                    primary: t("Capture meetings & notes", "Сохраняй встречи и голосовые заметки"),
                    detail: t(
                        "Hit record in WaiComputer. Get a full transcript, AI summary, and action items when you're done.",
                        "Нажми запись в WaiComputer. После встречи появятся расшифровка, краткая сводка и список задач."
                    )
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

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

#Preview {
    OnboardingValuePropsSlide(isActive: true)
        .frame(width: 880, height: 580)
        .environmentObject(LanguageManager.shared)
}
