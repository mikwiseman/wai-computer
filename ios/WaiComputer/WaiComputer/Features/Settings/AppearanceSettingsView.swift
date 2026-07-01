import SwiftUI
import WaiComputerKit

/// Appearance preferences: Theme (System/Light/Dark) + accent color.
///
/// Mirrors the macOS `MacSettingsView.appearanceSection`. The selections write
/// the same `IOSThemePreferences` AppStorage keys that the app root reads to
/// apply `.preferredColorScheme` + `.tint`, so changes take effect live.
struct AppearanceSettingsView: View {
    @EnvironmentObject var languageManager: LanguageManager
    @Environment(\.horizontalSizeClass) private var appearanceHorizontalSizeClass
    @AppStorage(IOSThemePreferences.appearanceKey) private var appearanceModeRawValue = IOSThemePreferences.defaultAppearance.rawValue
    @AppStorage(IOSThemePreferences.accentKey) private var accentChoiceRawValue = IOSThemePreferences.defaultAccent.rawValue

    private var selectedAppearanceMode: IOSAppearanceMode {
        IOSAppearanceMode(rawValue: appearanceModeRawValue) ?? IOSThemePreferences.defaultAppearance
    }

    private var selectedAccentChoice: IOSAccentChoice {
        IOSAccentChoice(rawValue: accentChoiceRawValue) ?? IOSThemePreferences.defaultAccent
    }

    var body: some View {
        Group {
            if appearanceHorizontalSizeClass == .regular {
                appearanceRegularLayout
            } else {
                appearanceCompactList
            }
        }
        .navigationTitle(t("Appearance", "Внешний вид"))
        .navigationBarTitleDisplayMode(appearanceHorizontalSizeClass == .regular ? .inline : .large)
    }

    private var appearanceCompactList: some View {
        List {
            Section {
                appearanceModePicker
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
        .accessibilityIdentifier("settings-appearance-compact-list")
    }

    private var appearanceRegularLayout: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Spacing.xl) {
                appearanceRegularHeader

                LazyVGrid(
                    columns: [GridItem(.adaptive(minimum: 320), spacing: Spacing.lg, alignment: .top)],
                    alignment: .leading,
                    spacing: Spacing.lg
                ) {
                    appearanceRegularThemePanel
                    appearanceRegularAccentPanel
                    appearanceRegularPreviewPanel
                }
            }
            .padding(.horizontal, Spacing.xxl)
            .padding(.vertical, Spacing.xxl)
            .frame(maxWidth: 920, alignment: .topLeading)
            .frame(maxWidth: .infinity, alignment: .top)
        }
        .background(Color(uiColor: .systemGroupedBackground))
        .accessibilityIdentifier("settings-appearance-regular-layout")
    }

    private var appearanceRegularHeader: some View {
        HStack(alignment: .center, spacing: Spacing.md) {
            Image(systemName: "paintpalette")
                .font(.system(size: 18, weight: .semibold))
                .foregroundStyle(Palette.accent)
                .frame(width: 42, height: 42)
                .background(Color(uiColor: .secondarySystemGroupedBackground))
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: 8, style: .continuous)
                        .strokeBorder(Palette.border, lineWidth: 1)
                )
                .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: Spacing.xs) {
                Text(t("Appearance", "Внешний вид"))
                    .font(Typography.displayMedium)
                    .foregroundStyle(Palette.textPrimary)
                Text(t(
                    "Theme and accent color for the whole app.",
                    "Тема и акцентный цвет для всего приложения."
                ))
                .font(Typography.bodySmall)
                .foregroundStyle(Palette.textSecondary)
            }
        }
        .accessibilityIdentifier("settings-appearance-regular-header")
    }

    private var appearanceRegularThemePanel: some View {
        appearanceRegularPanel(
            title: t("Theme", "Тема"),
            subtitle: t(
                "Follow the system or pin WaiComputer to light or dark.",
                "Следовать системе или закрепить светлую/тёмную тему."
            ),
            systemImage: "circle.lefthalf.filled",
            identifier: "settings-appearance-regular-theme-panel"
        ) {
            appearanceModePicker
        }
    }

    private var appearanceRegularAccentPanel: some View {
        appearanceRegularPanel(
            title: t("Accent color", "Акцентный цвет"),
            subtitle: t(
                "Used for buttons, links, selection states, and highlights.",
                "Используется для кнопок, ссылок, выделений и активных состояний."
            ),
            systemImage: "eyedropper.halffull",
            identifier: "settings-appearance-regular-accent-panel"
        ) {
            LazyVGrid(
                columns: [GridItem(.adaptive(minimum: 132), spacing: Spacing.sm)],
                alignment: .leading,
                spacing: Spacing.sm
            ) {
                ForEach(IOSAccentChoice.allCases) { choice in
                    accentChoiceButton(choice)
                }
            }
        }
    }

    private var appearanceRegularPreviewPanel: some View {
        appearanceRegularPanel(
            title: t("Preview", "Предпросмотр"),
            subtitle: t(
                "Live sample of the current appearance.",
                "Живой пример текущего оформления."
            ),
            systemImage: "rectangle.and.pencil.and.ellipsis",
            identifier: "settings-appearance-regular-preview-panel"
        ) {
            VStack(alignment: .leading, spacing: Spacing.md) {
                themePreview
                Text(t(
                    "Uses adaptive iOS system colors so the accent works in Light, Dark, and increased contrast modes.",
                    "Использует адаптивные цвета iOS, чтобы акцент работал в светлой, тёмной и контрастной темах."
                ))
                .font(Typography.caption)
                .foregroundStyle(Palette.textTertiary)
                .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private var appearanceModePicker: some View {
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

    private func accentChoiceButton(_ choice: IOSAccentChoice) -> some View {
        let isSelected = selectedAccentChoice == choice
        return Button {
            accentChoiceRawValue = choice.rawValue
        } label: {
            HStack(spacing: Spacing.sm) {
                Circle()
                    .fill(choice.previewColor)
                    .frame(width: 14, height: 14)
                    .overlay(Circle().strokeBorder(Palette.border, lineWidth: 1))
                    .accessibilityHidden(true)

                Text(accentTitle(choice))
                    .font(Typography.bodySmall)
                    .foregroundStyle(Palette.textPrimary)
                    .lineLimit(1)

                Spacer(minLength: Spacing.xs)

                if isSelected {
                    Image(systemName: "checkmark")
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundStyle(selectedAccentChoice.previewColor)
                        .accessibilityHidden(true)
                }
            }
            .padding(.horizontal, Spacing.sm)
            .padding(.vertical, Spacing.sm)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(isSelected ? selectedAccentChoice.previewColor.opacity(0.12) : Color(uiColor: .tertiarySystemGroupedBackground))
            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .strokeBorder(isSelected ? selectedAccentChoice.previewColor : Palette.border, lineWidth: isSelected ? 1.5 : 1)
            )
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

    private func appearanceRegularPanel<Content: View>(
        title: String,
        subtitle: String?,
        systemImage: String,
        identifier: String,
        @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            HStack(alignment: .top, spacing: Spacing.md) {
                Image(systemName: systemImage)
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(Palette.accent)
                    .frame(width: 30, height: 30)
                    .background(Palette.accentSubtle)
                    .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                    .accessibilityHidden(true)

                VStack(alignment: .leading, spacing: Spacing.xs) {
                    Text(title)
                        .font(Typography.headingLarge)
                        .foregroundStyle(Palette.textPrimary)
                    if let subtitle {
                        Text(subtitle)
                            .font(Typography.caption)
                            .foregroundStyle(Palette.textSecondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }

            Divider()
            content()
        }
        .padding(Spacing.lg)
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .background(Color(uiColor: .secondarySystemGroupedBackground))
        .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .strokeBorder(Palette.border, lineWidth: 1)
        )
        .accessibilityIdentifier(identifier)
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
