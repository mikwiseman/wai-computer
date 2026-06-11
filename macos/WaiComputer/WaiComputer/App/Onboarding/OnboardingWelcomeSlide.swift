import SwiftUI
import AppKit
import WaiComputerKit

struct OnboardingWelcomeSlide: View {
    let isActive: Bool
    @EnvironmentObject private var languageManager: LanguageManager

    var body: some View {
        VStack(spacing: 24) {
            Spacer(minLength: 0)

            Image(nsImage: NSApp.applicationIconImage)
                .resizable()
                .scaledToFit()
                .frame(width: 104, height: 104)
                .shadow(color: .black.opacity(0.10), radius: 12, x: 0, y: 8)
                .opacity(isActive ? 1 : 0)
                .offset(y: isActive ? 0 : 12)
                .animation(.easeOut(duration: 0.45).delay(0.05), value: isActive)

            VStack(spacing: 12) {
                Text(t("Welcome to WaiComputer", "Добро пожаловать в WaiComputer"))
                    .font(.system(size: 32, weight: .bold))
                    .foregroundStyle(Palette.textPrimary)
                    .accessibilityIdentifier("onboarding-welcome-title")
                Text(t(
                    "Record, upload, save links, and chat with Wai from one Inbox — set up in 90 seconds.",
                    "Записывай, загружай файлы, сохраняй ссылки и общайся с Wai из одного Инбокса — настройка займет около 90 секунд."
                ))
                    .font(.system(size: 15))
                    .foregroundStyle(Palette.textSecondary)
                    .multilineTextAlignment(.center)
                    .lineSpacing(3)
                    .frame(maxWidth: 520)
            }
            .opacity(isActive ? 1 : 0)
            .offset(y: isActive ? 0 : 16)
            .animation(.easeOut(duration: 0.45).delay(0.12), value: isActive)

            languagePicker
                .opacity(isActive ? 1 : 0)
                .offset(y: isActive ? 0 : 16)
                .animation(.easeOut(duration: 0.45).delay(0.18), value: isActive)

            Spacer()
        }
        .padding(.horizontal, Spacing.xl)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var languagePicker: some View {
        VStack(spacing: 10) {
            Text(t("Choose app language", "Выбери язык приложения"))
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(Palette.textTertiary)
                .textCase(.uppercase)
                .tracking(0.8)
                .accessibilityIdentifier("onboarding-language-prompt")

            HStack(spacing: 0) {
                languageButton("English", language: .english, identifier: "onboarding-language-english")
                languageButton("Русский", language: .russian, identifier: "onboarding-language-russian")
            }
            .frame(width: 240)
            .padding(2)
            .background(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .fill(Color.secondary.opacity(0.12))
            )

            Text(t(
                "You can change this anytime in Settings.",
                "Язык можно изменить позже в настройках."
            ))
            .font(.system(size: 12))
            .foregroundStyle(Palette.textTertiary)
        }
    }

    private var selectedOnboardingLanguage: LanguageManager.SupportedLanguage {
        switch OnboardingL10n.language(for: languageManager.current) {
        case .english:
            return .english
        case .russian:
            return .russian
        }
    }

    @ViewBuilder
    private func languageButton(
        _ title: String,
        language: LanguageManager.SupportedLanguage,
        identifier: String
    ) -> some View {
        let selected = selectedOnboardingLanguage == language
        Button(title) {
            languageManager.setLanguage(language)
        }
        .buttonStyle(.plain)
        .font(.system(size: 13, weight: .medium))
        .foregroundStyle(selected ? Palette.textPrimary : Palette.textSecondary)
        .frame(maxWidth: .infinity)
        .padding(.vertical, 6)
        .background(
            RoundedRectangle(cornerRadius: 6, style: .continuous)
                .fill(selected ? Color(NSColor.windowBackgroundColor) : Color.clear)
        )
        .accessibilityIdentifier(identifier)
        .accessibilityLabel(title)
        .accessibilityAddTraits(selected ? .isSelected : [])
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

#Preview {
    OnboardingWelcomeSlide(isActive: true)
        .frame(width: 880, height: 580)
        .environmentObject(LanguageManager.shared)
}
