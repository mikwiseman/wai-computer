import SwiftUI
import WaiComputerKit

struct OnboardingSlide: View {
    let page: OnboardingPage
    let isActive: Bool

    @EnvironmentObject private var languageManager: LanguageManager

    private var content: OnboardingPage.Content { page.content(language: languageManager.current) }

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

            // Welcome and the dedicated language slide both let the user pick
            // the app language inline so they can read the rest of onboarding
            // in their own language. Mirrors macOS OnboardingWelcomeSlide.
            if page == .welcome || page == .language {
                OnboardingLanguageToggle(showHint: page == .welcome)
                    .opacity(isActive ? 1 : 0)
                    .offset(y: isActive ? 0 : 16)
                    .animation(.easeOut(duration: 0.45).delay(0.18), value: isActive)
            }

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
                .frame(width: 96, height: 96)
                .shadow(color: .black.opacity(0.10), radius: 12, x: 0, y: 8)
        } else if let symbol = content.symbol {
            Image(systemName: symbol)
                .font(.system(size: 72, weight: .light))
                .foregroundStyle(Palette.accent)
                .frame(width: 96, height: 96)
        }
    }
}

/// EN/RU segmented control that switches the in-app language via
/// `LanguageManager`. Used inline on the welcome slide and on the dedicated
/// language slide. Ports the picker logic from macOS OnboardingWelcomeSlide.
struct OnboardingLanguageToggle: View {
    var showHint: Bool = true
    @EnvironmentObject private var languageManager: LanguageManager

    var body: some View {
        VStack(spacing: Spacing.sm) {
            Text(t("Choose app language", "Выбери язык приложения"))
                .font(Typography.labelSmall)
                .tracking(0.8)
                .textCase(.uppercase)
                .foregroundStyle(Palette.textTertiary)
                .accessibilityIdentifier("onboarding-language-prompt")

            HStack(spacing: 0) {
                languageButton("English", language: .english, identifier: "onboarding-language-english")
                languageButton("Русский", language: .russian, identifier: "onboarding-language-russian")
            }
            .frame(maxWidth: 260)
            .padding(2)
            .waiGlassChrome(cornerRadius: Radius.md, interactive: true)

            if showHint {
                Text(t(
                    "You can change this anytime in Settings.",
                    "Язык можно изменить позже в настройках."
                ))
                .font(Typography.caption)
                .foregroundStyle(Palette.textTertiary)
            }
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
        .font(Typography.headingSmall)
        .foregroundStyle(selected ? Palette.textPrimary : Palette.textSecondary)
        .frame(maxWidth: .infinity)
        .padding(.vertical, Spacing.sm)
        .background(
            RoundedRectangle(cornerRadius: Radius.sm, style: .continuous)
                .fill(selected ? Palette.panel : Color.clear)
        )
        .accessibilityIdentifier(identifier)
        .accessibilityLabel(title)
        .accessibilityAddTraits(selected ? .isSelected : [])
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

#Preview("Welcome") {
    OnboardingSlide(page: .welcome, isActive: true)
        .environmentObject(LanguageManager.shared)
}

#Preview("Language") {
    OnboardingSlide(page: .language, isActive: true)
        .environmentObject(LanguageManager.shared)
}

#Preview("Permission") {
    OnboardingSlide(page: .permission, isActive: true)
        .environmentObject(LanguageManager.shared)
}
