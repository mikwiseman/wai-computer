import SwiftUI
import WaiComputerKit

struct OnboardingWelcomeSlide: View {
    let isActive: Bool
    @EnvironmentObject private var languageManager: LanguageManager

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
                Text(t("Welcome to WaiComputer", "Добро пожаловать в WaiComputer"))
                    .font(.system(size: 32, weight: .bold))
                    .foregroundStyle(Palette.textPrimary)
                Text(t(
                    "Voice-type into any app and capture meetings — set up in 90 seconds.",
                    "Диктуй текст в любом приложении и записывай встречи — настройка займет около 90 секунд."
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

            Picker("", selection: Binding(
                get: { selectedOnboardingLanguage },
                set: { languageManager.setLanguage($0) }
            )) {
                Text("English").tag(LanguageManager.SupportedLanguage.english)
                Text("Русский").tag(LanguageManager.SupportedLanguage.russian)
            }
            .pickerStyle(.segmented)
            .frame(width: 240)
            .accessibilityIdentifier("onboarding-app-language-picker")

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

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

#Preview {
    OnboardingWelcomeSlide(isActive: true)
        .frame(width: 880, height: 580)
        .environmentObject(LanguageManager.shared)
}
