import SwiftUI
import WaiComputerKit

/// Onboarding language picker slide. Sits between Allow and Hotkey so the
/// user can narrow STT to specific languages (lower latency, fewer
/// false-positive switches) or leave on auto-detect (multi). Reuses the
/// LanguagePickerView from Settings — single source of truth.
struct OnboardingLanguagesSlide: View {
    let isActive: Bool
    @ObservedObject var store: DictationLanguageStore
    @EnvironmentObject private var languageManager: LanguageManager

    var body: some View {
        VStack(spacing: 24) {
            Spacer(minLength: 0)

            VStack(spacing: 10) {
                Text(t("Choose dictation languages", "Выбери языки диктовки"))
                    .font(.system(size: 30, weight: .bold))
                    .foregroundStyle(Palette.textPrimary)
                Text(t(
                    "One language gives the lowest latency. Auto-detect lets you switch naturally. You can change this later in Settings.",
                    "Один язык дает минимальную задержку. Автоопределение позволяет свободно переключаться. Это можно изменить позже в настройках."
                ))
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

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}
