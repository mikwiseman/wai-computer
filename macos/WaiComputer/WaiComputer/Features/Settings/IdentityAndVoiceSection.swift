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
                        .foregroundStyle(.red)
                        .accessibilityIdentifier("settings-identity-error")
                }
            }
        } header: {
            Text("Identity & Voice")
                .waiSectionHeader()
                .accessibilityIdentifier("settings-identity-header")
        } footer: {
            Text(
                "Your name and voiceprint are private until you turn on sharing. "
                + "We never share audio or transcripts."
            )
            .font(Typography.caption)
            .foregroundStyle(Palette.textTertiary)
        }
        .task { await refresh() }
        .confirmationDialog(
            "Share your voice in WaiComputer?",
            isPresented: $showShareConfirmation,
            titleVisibility: .visible
        ) {
            Button("Share") {
                Task { await flipSharing(to: true) }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text(
                "Other WaiComputer users will see \"\(sharedNamePreview)\" "
                + "in their recordings when your voice is detected. "
                + "We share your name and a voice fingerprint only — never "
                + "your audio or transcripts. You can turn this off any time."
            )
        }
    }

    @ViewBuilder
    private var identityFields: some View {
        LabeledContent {
            TextField("First name", text: $firstName)
                .textFieldStyle(.roundedBorder)
                .frame(maxWidth: 220)
                .onSubmit { Task { await saveNames() } }
                .accessibilityIdentifier("settings-identity-first-name")
        } label: {
            Text("First name")
        }
        .font(Typography.body)

        LabeledContent {
            TextField("Last name", text: $lastName)
                .textFieldStyle(.roundedBorder)
                .frame(maxWidth: 220)
                .onSubmit { Task { await saveNames() } }
                .accessibilityIdentifier("settings-identity-last-name")
        } label: {
            Text("Last name")
        }
        .font(Typography.body)

        if savingNames {
            HStack(spacing: Spacing.xs) {
                ProgressView().controlSize(.mini)
                Text("Saving…")
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
                Text("Share my voice in the WaiComputer directory")
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
            return state.sharedName.map { "Visible to others as \($0)." } ?? "On."
        }
        if state.canEnable {
            return "Off. Other users will not see your name in their recordings."
        }
        var missing: [String] = []
        if !state.hasFirstName || !state.hasLastName { missing.append("a first and last name") }
        if !state.hasVoiceprint { missing.append("an enrolled voice sample") }
        return "Add \(missing.joined(separator: " and ")) to enable sharing."
    }

    private var sharedNamePreview: String {
        let composed = [firstName, lastName]
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }
            .joined(separator: " ")
        return composed.isEmpty ? "your name" : composed
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
            self.error = "Could not load identity settings."
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
            self.error = "Could not save your name."
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
                ? "Could not turn on voice sharing."
                : "Could not turn off voice sharing."
        }
    }
}
