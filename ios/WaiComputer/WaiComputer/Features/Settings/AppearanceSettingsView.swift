import SwiftUI
import WaiComputerKit

/// Appearance preferences: Theme (System/Pearl/Midnight) + accent color.
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
        .background(Palette.canvas)
        .accessibilityIdentifier("settings-appearance-regular-layout")
    }

    private var appearanceRegularHeader: some View {
        HStack(alignment: .center, spacing: Spacing.md) {
            Image(systemName: "paintpalette")
                .font(.system(size: 18, weight: .semibold))
                .foregroundStyle(Palette.accent)
                .frame(width: 42, height: 42)
                .background(Palette.panelRaised)
                .clipShape(RoundedRectangle(cornerRadius: Radius.md, style: .continuous))
                .overlay(
                    RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
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
                "Follow the system, choose airy Pearl, or focus in Midnight.",
                "Следовать системе, выбрать воздушную Жемчужную тему или сфокусироваться в Полночи."
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
                    "Adaptive iOS colors keep every accent legible in Pearl, Midnight, and increased contrast modes.",
                    "Адаптивные цвета iOS сохраняют читаемость акцента в Жемчужной теме, Полночи и повышенной контрастности."
                ))
                .font(Typography.caption)
                .foregroundStyle(Palette.textTertiary)
                .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private var appearanceModePicker: some View {
        LazyVGrid(
            columns: [GridItem(.adaptive(minimum: 92), spacing: Spacing.sm)],
            spacing: Spacing.sm
        ) {
            ForEach(IOSAppearanceMode.allCases) { mode in
                appearanceModeButton(mode)
            }
        }
        .accessibilityIdentifier("settings-appearance-mode-picker")
    }

    private func appearanceModeButton(_ mode: IOSAppearanceMode) -> some View {
        let isSelected = selectedAppearanceMode == mode
        return Button {
            appearanceModeRawValue = mode.rawValue
        } label: {
            VStack(alignment: .leading, spacing: Spacing.md) {
                Image(systemName: appearanceIcon(mode))
                    .font(.system(size: 18, weight: .medium))
                    .foregroundStyle(isSelected ? Palette.accent : Palette.textSecondary)
                    .accessibilityHidden(true)

                Text(appearanceTitle(mode))
                    .font(Typography.headingSmall)
                    .foregroundStyle(isSelected ? Palette.accent : Palette.textPrimary)
                    .lineLimit(1)
            }
            .padding(Spacing.md)
            .frame(maxWidth: .infinity, minHeight: 82, alignment: .leading)
            .background(isSelected ? Palette.accentSubtle : Palette.panelRaised)
            .clipShape(RoundedRectangle(cornerRadius: Radius.lg, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: Radius.lg, style: .continuous)
                    .strokeBorder(isSelected ? Palette.accent : Palette.border, lineWidth: isSelected ? 1.5 : 1)
            )
        }
        .buttonStyle(.plain)
        .accessibilityLabel(appearanceTitle(mode))
        .accessibilityValue(isSelected ? t("Selected", "Выбрано") : t("Not selected", "Не выбрано"))
        .accessibilityIdentifier("settings-appearance-mode-\(mode.rawValue)")
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
            .clipShape(RoundedRectangle(cornerRadius: Radius.md, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
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
            RoundedRectangle(cornerRadius: Radius.md, style: .continuous)
                .fill(selectedAccentChoice.previewColor)
                .frame(width: 40, height: 40)
                .overlay(
                    Image(systemName: "paintpalette.fill")
                        .foregroundStyle(selectedAccentChoice.onAccentColor)
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
        .padding(Spacing.md)
        .background(Palette.panelRaised)
        .clipShape(RoundedRectangle(cornerRadius: Radius.lg, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: Radius.lg, style: .continuous)
                .strokeBorder(Palette.border, lineWidth: 1)
        )
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
                    .clipShape(RoundedRectangle(cornerRadius: Radius.sm, style: .continuous))
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

            Rectangle()
                .fill(Palette.border)
                .frame(height: 1)
            content()
        }
        .padding(Spacing.lg)
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .background(Palette.panel)
        .clipShape(RoundedRectangle(cornerRadius: Radius.lg, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: Radius.lg, style: .continuous)
                .strokeBorder(Palette.border, lineWidth: 1)
        )
        .waiShadow(.raised)
        .accessibilityIdentifier(identifier)
    }

    private func appearanceTitle(_ mode: IOSAppearanceMode) -> String {
        switch mode {
        case .system:
            return t("System", "Системная")
        case .light:
            return t("Pearl", "Жемчужная")
        case .dark:
            return t("Midnight", "Полночь")
        }
    }

    private func appearanceIcon(_ mode: IOSAppearanceMode) -> String {
        switch mode {
        case .system: return "macbook.and.iphone"
        case .light: return "sun.max"
        case .dark: return "moon.stars"
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
