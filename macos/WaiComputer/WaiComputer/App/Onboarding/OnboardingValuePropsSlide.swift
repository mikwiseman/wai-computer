import SwiftUI
import WaiComputerKit

struct OnboardingValuePropsSlide: View {
    let isActive: Bool
    @EnvironmentObject private var languageManager: LanguageManager

    var body: some View {
        VStack(spacing: 32) {
            Spacer(minLength: 0)

            VStack(spacing: 8) {
                Text(t("One Inbox for everything", "Один Инбокс для всего"))
                    .font(Typography.displayLarge)
                    .foregroundStyle(Palette.textPrimary)
                Text(t("Capture, organize, and give Wai tasks without switching sections.", "Сохраняй, раскладывай и давай Wai задачи без лишних разделов."))
                    .font(.system(size: 14))
                    .foregroundStyle(Palette.textSecondary)
            }

            HStack(alignment: .top, spacing: 16) {
                valueCard(
                    icon: "tray.full",
                    title: t("Inbox", "Инбокс"),
                    primary: t("Recordings, files, notes, and chats", "Записи, файлы, заметки и чаты"),
                    detail: t(
                        "Everything lands in one place first. Filter by type when you need focus.",
                        "Всё сначала попадает в одно место. Фильтры помогают сфокусироваться по типу."
                    )
                )
                valueCard(
                    icon: "folder",
                    title: t("Folders", "Папки"),
                    primary: t("Organize recordings and materials", "Разложи записи и материалы"),
                    detail: t(
                        "Folders work across the Inbox, so projects are not split by media type.",
                        "Папки работают поверх Инбокса, поэтому проекты не делятся по типу медиа."
                    )
                )
                valueCard(
                    icon: "bubble.left.and.bubble.right",
                    title: "Wai",
                    primary: t("Give Wai tasks over what you saved", "Давай Wai задачи по тому, что сохранено"),
                    detail: t(
                        "Use Wai for summaries, decisions, repeated themes, or answers from your saved context.",
                        "Используй Wai для саммари, решений, повторяющихся тем или ответов из сохраненного контекста."
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
                RoundedRectangle(cornerRadius: Radius.lg, style: .continuous)
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
        .padding(18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: Radius.lg, style: .continuous)
                .fill(Color(NSColor.windowBackgroundColor))
        )
        .overlay(
            RoundedRectangle(cornerRadius: Radius.lg, style: .continuous)
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
