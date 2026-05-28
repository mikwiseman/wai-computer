import SwiftUI
import WaiComputerKit

/// iOS Settings sub-page for public identity + voice-sharing directory.
///
/// Mirrors `IdentityAndVoiceSection` on macOS. The toggle is disabled until
/// first/last name AND a voice sample exist, and flipping it ON requires
/// confirmation that surfaces exactly what is shared.
struct IdentityAndVoiceSettingsView: View {
    @EnvironmentObject var appState: AppState

    @State private var firstName: String = ""
    @State private var lastName: String = ""
    @State private var sharing: VoiceSharingState?
    @State private var loading: Bool = true
    @State private var savingNames: Bool = false
    @State private var toggling: Bool = false
    @State private var error: String?
    @State private var showShareConfirmation: Bool = false

    var body: some View {
        List {
            if loading {
                Section { ProgressView() }
            } else {
                identitySection
                voiceSharingSection
                if let error {
                    Section {
                        Text(error)
                            .font(.footnote)
                            .foregroundStyle(.red)
                    }
                }
            }
        }
        .navigationTitle("Identity & Voice")
        .navigationBarTitleDisplayMode(.inline)
        .task { await refresh() }
        .alert("Share your voice in WaiComputer?", isPresented: $showShareConfirmation) {
            Button("Share") {
                Task { await flipSharing(to: true) }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text(
                "Other WaiComputer users will see \"\(sharedNamePreview)\" in their "
                + "recordings when your voice is detected. We share your name and a "
                + "voice fingerprint only — never your audio or transcripts. You can "
                + "turn this off any time."
            )
        }
    }

    @ViewBuilder
    private var identitySection: some View {
        Section {
            HStack {
                Text("First name").foregroundStyle(.secondary)
                Spacer()
                TextField("Required", text: $firstName)
                    .multilineTextAlignment(.trailing)
                    .textInputAutocapitalization(.words)
                    .autocorrectionDisabled(true)
                    .onSubmit { Task { await saveNames() } }
            }
            HStack {
                Text("Last name").foregroundStyle(.secondary)
                Spacer()
                TextField("Required", text: $lastName)
                    .multilineTextAlignment(.trailing)
                    .textInputAutocapitalization(.words)
                    .autocorrectionDisabled(true)
                    .onSubmit { Task { await saveNames() } }
            }
            if savingNames {
                HStack(spacing: 6) {
                    ProgressView().controlSize(.mini)
                    Text("Saving…").font(.footnote).foregroundStyle(.secondary)
                }
            }
        } header: {
            Text("Identity")
        } footer: {
            Text("Used as your display name in other users' recordings when sharing is on.")
        }
    }

    @ViewBuilder
    private var voiceSharingSection: some View {
        let state = sharing
        let canToggle = state?.canEnable == true
        let isOn = state?.enabled == true

        Section {
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
                Text("Share my voice in the WaiComputer directory")
            }
            .disabled(!canToggle && !isOn || toggling)
        } header: {
            Text("Voice Sharing")
        } footer: {
            Text(toggleSubtitle(state))
        }
    }

    private func toggleSubtitle(_ state: VoiceSharingState?) -> String {
        guard let state else { return "" }
        if state.enabled {
            return state.sharedName.map {
                "Visible to others as \($0). We share your name and a voice fingerprint only."
            } ?? "On."
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
