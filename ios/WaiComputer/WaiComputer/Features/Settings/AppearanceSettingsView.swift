import SwiftUI
import WaiComputerKit

/// Appearance preferences: Theme (System/Light/Dark) + accent color.
///
/// Mirrors the macOS `MacSettingsView.appearanceSection`. The selections write
/// the same `IOSThemePreferences` AppStorage keys that the app root reads to
/// apply `.preferredColorScheme` + `.tint`, so changes take effect live.
struct AppearanceSettingsView: View {
    @EnvironmentObject var languageManager: LanguageManager
    @AppStorage(IOSThemePreferences.appearanceKey) private var appearanceModeRawValue = IOSThemePreferences.defaultAppearance.rawValue
    @AppStorage(IOSThemePreferences.accentKey) private var accentChoiceRawValue = IOSThemePreferences.defaultAccent.rawValue

    private var selectedAppearanceMode: IOSAppearanceMode {
        IOSAppearanceMode(rawValue: appearanceModeRawValue) ?? IOSThemePreferences.defaultAppearance
    }

    private var selectedAccentChoice: IOSAccentChoice {
        IOSAccentChoice(rawValue: accentChoiceRawValue) ?? IOSThemePreferences.defaultAccent
    }

    var body: some View {
        List {
            Section {
                Picker(selection: Binding(
                    get: { selectedAppearanceMode.rawValue },
                    set: { appearanceModeRawValue = $0 }
                )) {
                    ForEach(IOSAppearanceMode.allCases) { mode in
                        Text(appearanceTitle(mode)).tag(mode.rawValue)
                    }
                } label: {
                    Text(t("Theme", "Тема"))
                }
                .pickerStyle(.segmented)
                .accessibilityIdentifier("settings-appearance-mode-picker")
            } header: {
                Text(t("Theme", "Тема"))
            }

            Section {
                ForEach(IOSAccentChoice.allCases) { choice in
                    accentRow(choice)
                }
            } header: {
                Text(t("Accent color", "Акцентный цвет"))
            } footer: {
                Text(t(
                    "Sets the app-wide tint used for buttons, links, and highlights.",
                    "Задаёт цвет акцента для кнопок, ссылок и выделений во всём приложении."
                ))
            }

            Section {
                themePreview
            }
        }
        .navigationTitle(t("Appearance", "Внешний вид"))
        .navigationBarTitleDisplayMode(.inline)
    }

    private func accentRow(_ choice: IOSAccentChoice) -> some View {
        let isSelected = selectedAccentChoice == choice
        return Button {
            accentChoiceRawValue = choice.rawValue
        } label: {
            HStack(spacing: Spacing.md) {
                Circle()
                    .fill(choice.previewColor)
                    .frame(width: 18, height: 18)
                    .overlay(Circle().strokeBorder(Palette.border, lineWidth: 1))
                    .accessibilityHidden(true)

                Text(accentTitle(choice))
                    .font(Typography.body)
                    .foregroundStyle(Palette.textPrimary)

                Spacer()

                if isSelected {
                    Image(systemName: "checkmark")
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(choice.previewColor)
                        .accessibilityHidden(true)
                }
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(accentTitle(choice))
        .accessibilityValue(isSelected ? t("Selected", "Выбрано") : t("Not selected", "Не выбрано"))
        .accessibilityIdentifier("settings-accent-\(choice.rawValue)")
    }

    private var themePreview: some View {
        HStack(spacing: Spacing.md) {
            RoundedRectangle(cornerRadius: 8)
                .fill(selectedAccentChoice.previewColor)
                .frame(width: 40, height: 40)
                .overlay(
                    Image(systemName: "paintpalette.fill")
                        .foregroundStyle(.white)
                )
                .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: Spacing.xs) {
                Text(t("Preview", "Предпросмотр"))
                    .font(Typography.headingMedium)
                Text("\(appearanceTitle(selectedAppearanceMode)) · \(accentTitle(selectedAccentChoice))")
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textTertiary)
            }

            Spacer()

            Button(t("Primary", "Основная")) {}
                .buttonStyle(.borderedProminent)
                .tint(selectedAccentChoice.previewColor)
                .disabled(true)
                .accessibilityHidden(true)
        }
        .padding(.vertical, Spacing.xs)
    }

    private func appearanceTitle(_ mode: IOSAppearanceMode) -> String {
        switch mode {
        case .system:
            return t("System", "Системная")
        case .light:
            return t("Light", "Светлая")
        case .dark:
            return t("Dark", "Тёмная")
        }
    }

    private func accentTitle(_ choice: IOSAccentChoice) -> String {
        switch choice {
        case .system:
            return t("System", "Системный")
        case .amber:
            return t("Amber", "Янтарный")
        case .blue:
            return t("Blue", "Синий")
        case .green:
            return t("Green", "Зелёный")
        case .violet:
            return t("Violet", "Фиолетовый")
        case .rose:
            return t("Rose", "Розовый")
        case .graphite:
            return t("Graphite", "Графит")
        }
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}
