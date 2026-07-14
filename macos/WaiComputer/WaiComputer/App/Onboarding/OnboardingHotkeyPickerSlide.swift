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
                    .font(Typography.body)
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

    private func hotkeyChip(_ hotkey: DictationHotkey) -> some View {
        OnboardingHotkeyChip(
            rawValue: hotkey.rawValue,
            shortLabel: hotkey.onboardingShortLabel(language: languageManager.current),
            longLabel: hotkey.onboardingLabel(language: languageManager.current),
            isSelected: dictationManager.selectedHotkey == hotkey,
            selectedValueLabel: t("Selected", "Выбрано"),
            onSelect: { dictationManager.updateHotkey(hotkey) }
        )
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

/// One hotkey chip with the shared hover affordance (surface-tint on
/// pointer-over) used across the app's other clickable rows/chips.
private struct OnboardingHotkeyChip: View {
    let rawValue: String
    let shortLabel: String
    let longLabel: String
    let isSelected: Bool
    let selectedValueLabel: String
    let onSelect: () -> Void
    @State private var isHovered = false

    var body: some View {
        Button(action: onSelect) {
            VStack(spacing: 10) {
                Text(shortLabel)
                    .font(.system(size: 18, weight: .semibold, design: .monospaced))
                    .foregroundStyle(isSelected ? Palette.onAccent : Palette.textPrimary)
                    .padding(.horizontal, 14)
                    .padding(.vertical, 8)
                    .background(
                        RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                            .fill(isSelected ? Palette.accent : Palette.surfaceSubtle)
                    )

                Text(longLabel)
                    .font(Typography.label)
                    .foregroundStyle(isSelected ? Palette.textPrimary : Palette.textSecondary)
            }
            .padding(.vertical, 16)
            .padding(.horizontal, 12)
            .frame(maxWidth: .infinity)
            .background(
                RoundedRectangle(cornerRadius: Radius.lg, style: .continuous)
                    .fill(cardFill)
            )
            .overlay(
                RoundedRectangle(cornerRadius: Radius.lg, style: .continuous)
                    .strokeBorder(isSelected ? Palette.accent : Palette.border, lineWidth: isSelected ? 2 : 1)
            )
        }
        .buttonStyle(.plain)
        .onHover { isHovered = $0 }
        .accessibilityIdentifier("onboarding-hotkey-\(rawValue)")
        .accessibilityValue(isSelected ? selectedValueLabel : "")
        .accessibilityAddTraits(isSelected ? .isSelected : [])
    }

    private var cardFill: Color {
        if !isSelected, isHovered {
            return Palette.surfaceHover
        }
        return Color(NSColor.windowBackgroundColor)
    }
}
