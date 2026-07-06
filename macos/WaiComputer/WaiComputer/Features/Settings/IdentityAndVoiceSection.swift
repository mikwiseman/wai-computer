import SwiftUI
import WaiComputerKit

/// Settings section that owns the user's public identity (first + last name)
/// plus the global voice-sharing directory toggle.
///
/// UX rules
/// - First / last name fields autosave on commit (focus out or Return).
/// - The voice-sharing toggle is disabled until name AND voiceprint exist.
/// - Flipping the toggle ON shows a confirmation sheet listing exactly what
///   is shared and what is not.
/// - Flipping OFF is instant; the row is hard-deleted server-side.
struct IdentityAndVoiceSection: View {
    @EnvironmentObject var appState: MacAppState
    @EnvironmentObject var languageManager: LanguageManager

    @State private var firstName: String = ""
    @State private var lastName: String = ""
    @State private var sharing: VoiceSharingState?
    @State private var loading: Bool = true
    @State private var savingNames: Bool = false
    @State private var toggling: Bool = false
    @State private var error: String?
    @State private var showShareConfirmation: Bool = false

    var body: some View {
        Section {
            if loading {
                ProgressView().controlSize(.small)
            } else {
                identityFields
                Divider()
                voiceSharingRow
                if let error {
                    Text(error)
                        .font(Typography.caption)
                        .foregroundStyle(Palette.danger)
                        .accessibilityIdentifier("settings-identity-error")
                }
            }
        } header: {
            Text(t("Identity & Voice", "Удостоверение и голос"))
                .waiSectionHeader()
                .accessibilityIdentifier("settings-identity-header")
        } footer: {
            Text(t(
                "Your name and voiceprint are private until you turn on sharing. "
                + "We never share audio or transcripts.",
                "Твоё имя и голосовой слепок остаются приватными, пока ты не включишь "
                + "шаринг. Мы никогда не передаём аудио и расшифровки."
            ))
            .font(Typography.caption)
            .foregroundStyle(Palette.textTertiary)
        }
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
                    "Other WaiComputer users will see \"%@\" in their recordings when "
                    + "your voice is detected. We share your name and a voice fingerprint "
                    + "only — never your audio or transcripts. You can turn this off any time.",
                    "Другие пользователи WaiComputer увидят «%@» в своих записях, когда "
                    + "распознают твой голос. Мы передаём только имя и голосовой отпечаток — "
                    + "никогда аудио или расшифровки. Это можно отключить в любой момент."
                ),
                sharedNamePreview
            ))
        }
    }

    @ViewBuilder
    private var identityFields: some View {
        LabeledContent {
            TextField(t("First name", "Имя"), text: $firstName)
                .textFieldStyle(.roundedBorder)
                .frame(maxWidth: 220)
                .onSubmit { Task { await saveNames() } }
                .accessibilityIdentifier("settings-identity-first-name")
        } label: {
            Text(t("First name", "Имя"))
        }
        .font(Typography.body)

        LabeledContent {
            TextField(t("Last name", "Фамилия"), text: $lastName)
                .textFieldStyle(.roundedBorder)
                .frame(maxWidth: 220)
                .onSubmit { Task { await saveNames() } }
                .accessibilityIdentifier("settings-identity-last-name")
        } label: {
            Text(t("Last name", "Фамилия"))
        }
        .font(Typography.body)

        if savingNames {
            HStack(spacing: Spacing.xs) {
                ProgressView().controlSize(.mini)
                Text(t("Saving…", "Сохранение…"))
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textTertiary)
            }
        }
    }

    @ViewBuilder
    private var voiceSharingRow: some View {
        let state = sharing
        let canToggle = state?.canEnable == true
        let isOn = state?.enabled == true

        Toggle(
            isOn: Binding(
                get: { isOn },
                set: { newValue in
                    if newValue {
                        showShareConfirmation = true
                    } else {
                        Task { await flipSharing(to: false) }
                    }
                }
            )
        ) {
            VStack(alignment: .leading, spacing: 2) {
                Text(t(
                    "Share my voice in the WaiComputer directory",
                    "Поделиться голосом в справочнике WaiComputer"
                ))
                    .font(Typography.body)
                Text(toggleSubtitle(state))
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textTertiary)
            }
        }
        .toggleStyle(.switch)
        .disabled(!canToggle && !isOn || toggling)
        .accessibilityIdentifier("settings-voice-sharing-toggle")
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
            // Reload sharing state so the toggle reflects the new prerequisites.
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
