import SwiftUI
import WaiComputerKit

struct OnboardingHotkeyPickerSlide: View {
    let isActive: Bool
    @ObservedObject var dictationManager: DictationManager
    let onSelect: () -> Void
    @EnvironmentObject private var languageManager: LanguageManager

    var body: some View {
        VStack(spacing: 28) {
            Spacer(minLength: 0)

            VStack(spacing: 10) {
                Text(t("Pick your dictation key", "Выбери клавишу диктовки"))
                    .font(Typography.displayLarge)
                    .foregroundStyle(Palette.textPrimary)
                Text(t(
                    "Hold this key to dictate. Release to insert. We recommend Right Option.",
                    "Зажми эту клавишу, чтобы диктовать. Отпусти — текст вставится. Рекомендуем правый Option."
                ))
                    .font(.system(size: 14))
                    .foregroundStyle(Palette.textSecondary)
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: 540)
            }

            LazyVGrid(
                columns: [
                    GridItem(.adaptive(minimum: 150), spacing: 14),
                ],
                spacing: 14
            ) {
                ForEach(DictationHotkey.allCases) { hotkey in
                    hotkeyChip(hotkey)
                }
            }
            .frame(maxWidth: 640)

            Spacer(minLength: 0)
        }
        .padding(.horizontal, Spacing.xl)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .opacity(isActive ? 1 : 0)
        .offset(y: isActive ? 0 : 16)
        .animation(.easeOut(duration: 0.45).delay(0.1), value: isActive)
    }

    @ViewBuilder
    private func hotkeyChip(_ hotkey: DictationHotkey) -> some View {
        let selected = dictationManager.selectedHotkey == hotkey
        Button {
            dictationManager.updateHotkey(hotkey)
        } label: {
            VStack(spacing: 10) {
                Text(hotkey.onboardingShortLabel(language: languageManager.current))
                    .font(.system(size: 18, weight: .semibold, design: .monospaced))
                    .foregroundStyle(selected ? Palette.onAccent : Palette.textPrimary)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 8)
                    .background(
                        RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                            .fill(selected ? Palette.accent : Color.gray.opacity(0.12))
                    )

                Text(hotkey.onboardingLabel(language: languageManager.current))
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(selected ? Palette.textPrimary : Palette.textSecondary)
            }
            .padding(.vertical, 16)
            .padding(.horizontal, 12)
            .frame(maxWidth: .infinity)
            .background(
                RoundedRectangle(cornerRadius: Radius.lg, style: .continuous)
                    .fill(Color(NSColor.windowBackgroundColor))
            )
            .overlay(
                RoundedRectangle(cornerRadius: Radius.lg, style: .continuous)
                    .strokeBorder(selected ? Palette.accent : Palette.border, lineWidth: selected ? 2 : 1)
            )
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("onboarding-hotkey-\(hotkey.rawValue)")
        .accessibilityValue(selected ? t("Selected", "Выбрано") : "")
        .accessibilityAddTraits(selected ? .isSelected : [])
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}
