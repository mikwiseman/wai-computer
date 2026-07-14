import SwiftUI
import WaiComputerKit

/// iOS Settings sub-page for public identity + voice-sharing directory.
///
/// Mirrors `IdentityAndVoiceSection` on macOS. The toggle is disabled until
/// first/last name AND a voice sample exist, and flipping it ON requires
/// confirmation that surfaces exactly what is shared.
struct IdentityAndVoiceSettingsView: View {
    @EnvironmentObject var appState: AppState
    @EnvironmentObject var languageManager: LanguageManager
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass

    @State private var firstName: String = ""
    @State private var lastName: String = ""
    @State private var sharing: VoiceSharingState?
    @State private var loading: Bool = true
    @State private var savingNames: Bool = false
    @State private var toggling: Bool = false
    @State private var error: String?
    @State private var showShareConfirmation: Bool = false

    var body: some View {
        Group {
            if horizontalSizeClass == .regular {
                regularLayout
            } else {
                compactList
            }
        }
        .navigationTitle(t("Identity & Voice", "Личность и голос"))
        .navigationBarTitleDisplayMode(horizontalSizeClass == .regular ? .inline : .large)
        .task { await refresh() }
        .confirmationDialog(
            t("Share your voice in WaiComputer?", "Поделиться голосом в WaiComputer?"),
            isPresented: $showShareConfirmation,
            titleVisibility: .visible
        ) {
            Button(t("Share", "Поделиться")) {
                Task { await flipSharing(to: true) }
            }
            Button(t("Cancel", "Отмена"), role: .cancel) {}
        } message: {
            Text(String(
                format: t(
                    "Other WaiComputer users will see \"%@\" in their recordings when your voice is detected. We share your name and a voice fingerprint only — never your audio or transcripts. You can turn this off any time.",
                    "Другие пользователи WaiComputer увидят «%@» в своих записях, когда распознают твой голос. Мы передаём только имя и голосовой отпечаток — никогда аудио или расшифровки. Это можно отключить в любой момент."
                ),
                sharedNamePreview
            ))
        }
    }

    private var compactList: some View {
        List {
            if loading {
                Section { ProgressView() }
            } else {
                identitySection
                voiceSharingSection
                errorSection
            }
        }
        .accessibilityIdentifier("settings-identity-compact-list")
    }

    private var regularLayout: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: Spacing.xl) {
                regularHeader

                if loading {
                    loadingPanel
                } else {
                    LazyVGrid(
                        columns: [GridItem(.adaptive(minimum: 320), spacing: Spacing.lg, alignment: .top)],
                        alignment: .leading,
                        spacing: Spacing.lg
                    ) {
                        regularIdentityPanel
                        regularVoicePanel
                    }
                    errorSection
                }
            }
            .padding(.horizontal, Spacing.xxl)
            .padding(.vertical, Spacing.xxl)
            .frame(maxWidth: 920, alignment: .topLeading)
            .frame(maxWidth: .infinity, alignment: .top)
        }
        .background(Color(uiColor: .systemGroupedBackground))
        .accessibilityIdentifier("settings-identity-regular-layout")
    }

    private var regularHeader: some View {
        HStack(alignment: .center, spacing: Spacing.md) {
            Image(systemName: "person.wave.2")
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
                Text(t("Identity & Voice", "Личность и голос"))
                    .font(Typography.displayMedium)
                    .foregroundStyle(Palette.textPrimary)
                Text(t(
                    "Your display name and voice-sharing directory status.",
                    "Имя профиля и статус шаринга голоса."
                ))
                .font(Typography.bodySmall)
                .foregroundStyle(Palette.textSecondary)
            }
        }
        .accessibilityIdentifier("settings-identity-regular-header")
    }

    private var loadingPanel: some View {
        regularPanel(
            title: t("Identity & Voice", "Личность и голос"),
            subtitle: nil,
            systemImage: "person.wave.2",
            identifier: "settings-identity-loading-panel"
        ) {
            HStack(spacing: Spacing.sm) {
                ProgressView()
                    .controlSize(.small)
                Text(t("Loading identity settings…", "Загружаем настройки профиля…"))
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textTertiary)
            }
        }
    }

    private var regularIdentityPanel: some View {
        regularPanel(
            title: t("Identity", "Профиль"),
            subtitle: t(
                "Used as your display name in other users' recordings when sharing is on.",
                "Используется как имя в записях других пользователей, когда шаринг включён."
            ),
            systemImage: "person.text.rectangle",
            identifier: "settings-identity-regular-identity-panel"
        ) {
            VStack(alignment: .leading, spacing: Spacing.md) {
                identityFields
                if savingNames {
                    savingRow
                }
            }
        }
    }

    private var regularVoicePanel: some View {
        regularPanel(
            title: t("Voice Sharing", "Шаринг голоса"),
            subtitle: t(
                "Your name and voiceprint stay private until you turn on sharing.",
                "Имя и голосовой отпечаток приватны, пока ты не включишь шаринг."
            ),
            systemImage: "waveform.badge.person.crop",
            identifier: "settings-identity-regular-voice-panel"
        ) {
            VStack(alignment: .leading, spacing: Spacing.md) {
                prerequisiteRows
                Divider()
                voiceSharingRow
            }
        }
    }

    @ViewBuilder
    private var identitySection: some View {
        Section {
            identityFields
            if savingNames {
                savingRow
            }
        } header: {
            Text(t("Identity", "Профиль"))
        } footer: {
            Text(t(
                "Used as your display name in other users' recordings when sharing is on.",
                "Используется как имя в записях других пользователей, когда шаринг включён."
            ))
        }
    }

    @ViewBuilder
    private var voiceSharingSection: some View {
        Section {
            prerequisiteRows
            voiceSharingRow
        } header: {
            Text(t("Voice Sharing", "Шаринг голоса"))
        } footer: {
            Text(t(
                "We never share audio or transcripts.",
                "Мы никогда не передаём аудио или расшифровки."
            ))
        }
    }

    @ViewBuilder
    private var errorSection: some View {
        if let error {
            Text(error)
                .font(Typography.caption)
                .foregroundStyle(Palette.danger)
                .fixedSize(horizontal: false, vertical: true)
                .accessibilityIdentifier("settings-identity-error")
        }
    }

    private var identityFields: some View {
        VStack(alignment: .leading, spacing: Spacing.md) {
            identityField(
                title: t("First name", "Имя"),
                placeholder: t("Required", "Обязательно"),
                text: $firstName,
                identifier: "settings-identity-first-name"
            )
            identityField(
                title: t("Last name", "Фамилия"),
                placeholder: t("Required", "Обязательно"),
                text: $lastName,
                identifier: "settings-identity-last-name"
            )
        }
    }

    private func identityField(
        title: String,
        placeholder: String,
        text: Binding<String>,
        identifier: String
    ) -> some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            Text(title)
                .font(Typography.caption)
                .foregroundStyle(Palette.textTertiary)
            TextField(placeholder, text: text)
                .textFieldStyle(.roundedBorder)
                .textInputAutocapitalization(.words)
                .autocorrectionDisabled(true)
                .onSubmit { Task { await saveNames() } }
                .accessibilityIdentifier(identifier)
        }
        .font(Typography.body)
    }

    @ViewBuilder
    private var prerequisiteRows: some View {
        let state = sharing
        VStack(alignment: .leading, spacing: Spacing.sm) {
            prerequisiteRow(
                title: t("Name", "Имя"),
                isReady: state?.hasFirstName == true && state?.hasLastName == true,
                readyText: t("Ready", "Готово"),
                missingText: t("Missing", "Не заполнено"),
                systemImage: "person.crop.circle"
            )
            prerequisiteRow(
                title: t("Voice sample", "Образец голоса"),
                isReady: state?.hasVoiceprint == true,
                readyText: t("Enrolled", "Записан"),
                missingText: t("Needed", "Нужен"),
                systemImage: "waveform"
            )
        }
        .accessibilityIdentifier("settings-identity-prerequisites")
    }

    private func prerequisiteRow(
        title: String,
        isReady: Bool,
        readyText: String,
        missingText: String,
        systemImage: String
    ) -> some View {
        HStack(spacing: Spacing.sm) {
            Image(systemName: systemImage)
                .font(.system(size: 14, weight: .medium))
                .foregroundStyle(Palette.textSecondary)
                .frame(width: 22, height: 22)
                .accessibilityHidden(true)

            Text(title)
                .font(Typography.body)
                .foregroundStyle(Palette.textPrimary)

            Spacer(minLength: Spacing.md)

            Label(isReady ? readyText : missingText, systemImage: isReady ? "checkmark.circle.fill" : "exclamationmark.circle")
                .labelStyle(.titleAndIcon)
                .font(Typography.caption)
                .foregroundStyle(isReady ? Palette.success : Palette.warning)
        }
    }

    @ViewBuilder
    private var voiceSharingRow: some View {
        HStack(alignment: .center, spacing: Spacing.md) {
            VStack(alignment: .leading, spacing: Spacing.xxs) {
                Text(t(
                    "Share my voice in the WaiComputer directory",
                    "Поделиться голосом в справочнике WaiComputer"
                ))
                .font(Typography.body)
                .foregroundStyle(Palette.textPrimary)
                .fixedSize(horizontal: false, vertical: true)

                Text(toggleSubtitle(sharing))
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Spacer(minLength: Spacing.md)

            Toggle("", isOn: voiceSharingBinding)
                .labelsHidden()
                .toggleStyle(.switch)
                .disabled(!canToggleVoiceSharing && !isVoiceSharingOn || toggling)
                .accessibilityLabel(t(
                    "Share my voice in the WaiComputer directory",
                    "Поделиться голосом в справочнике WaiComputer"
                ))
                .accessibilityValue(toggleSubtitle(sharing))
                .accessibilityIdentifier("settings-voice-sharing-toggle")
        }
    }

    private var canToggleVoiceSharing: Bool {
        sharing?.canEnable == true
    }

    private var isVoiceSharingOn: Bool {
        sharing?.enabled == true
    }

    private var voiceSharingBinding: Binding<Bool> {
        Binding(
            get: { isVoiceSharingOn },
            set: { newValue in
                if newValue {
                    showShareConfirmation = true
                } else {
                    Task { await flipSharing(to: false) }
                }
            }
        )
    }

    private var savingRow: some View {
        HStack(spacing: Spacing.xs) {
            ProgressView().controlSize(.mini)
            Text(t("Saving…", "Сохранение…"))
                .font(Typography.caption)
                .foregroundStyle(Palette.textTertiary)
        }
    }

    private func regularPanel<Content: View>(
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

    private func toggleSubtitle(_ state: VoiceSharingState?) -> String {
        guard let state else { return "" }
        if state.enabled {
            return state.sharedName.map {
                String(format: t("Visible to others as %@.", "Видно другим как %@."), $0)
            } ?? t("On.", "Включено.")
        }
        if state.canEnable {
            return t(
                "Off. Other users will not see your name in their recordings.",
                "Выключено. Другие пользователи не увидят твоё имя в своих записях."
            )
        }
        var missing: [String] = []
        if !state.hasFirstName || !state.hasLastName {
            missing.append(t("a first and last name", "имя и фамилию"))
        }
        if !state.hasVoiceprint {
            missing.append(t("an enrolled voice sample", "образец голоса"))
        }
        return String(
            format: t("Add %@ to enable sharing.", "Добавь %@, чтобы включить шаринг."),
            missing.joined(separator: t(" and ", " и "))
        )
    }

    private var sharedNamePreview: String {
        let composed = [firstName, lastName]
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }
            .joined(separator: " ")
        return composed.isEmpty ? t("your name", "твоё имя") : composed
    }

    private func refresh() async {
        loading = true
        defer { loading = false }

        #if DEBUG
        if IOSTestingMode.current.isScreenshot {
            firstName = IOSScreenshotFixtures.identity.firstName ?? ""
            lastName = IOSScreenshotFixtures.identity.lastName ?? ""
            sharing = IOSScreenshotFixtures.voiceSharing
            error = nil
            return
        }
        #endif

        let api = appState.getAPIClient()
        do {
            async let identity = api.getIdentity()
            async let state = api.getVoiceSharing()
            let (ident, share) = try await (identity, state)
            firstName = ident.firstName ?? ""
            lastName = ident.lastName ?? ""
            sharing = share
            error = nil
        } catch {
            self.error = t("Could not load identity settings.", "Не удалось загрузить настройки профиля.")
        }
    }

    private func saveNames() async {
        guard !savingNames else { return }
        savingNames = true
        defer { savingNames = false }
        let api = appState.getAPIClient()
        do {
            let updated = try await api.updateIdentity(
                UpdateIdentityRequest(firstName: firstName, lastName: lastName)
            )
            firstName = updated.firstName ?? ""
            lastName = updated.lastName ?? ""
            sharing = try await api.getVoiceSharing()
            error = nil
        } catch {
            self.error = t("Could not save your name.", "Не удалось сохранить имя.")
        }
    }

    private func flipSharing(to enabled: Bool) async {
        guard !toggling else { return }
        toggling = true
        defer { toggling = false }
        let api = appState.getAPIClient()
        do {
            sharing = enabled
                ? try await api.enableVoiceSharing()
                : try await api.disableVoiceSharing()
            error = nil
        } catch {
            self.error = enabled
                ? t("Could not turn on voice sharing.", "Не удалось включить шаринг голоса.")
                : t("Could not turn off voice sharing.", "Не удалось выключить шаринг голоса.")
        }
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}
