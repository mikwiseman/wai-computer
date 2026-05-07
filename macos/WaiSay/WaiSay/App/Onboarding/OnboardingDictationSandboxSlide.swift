import SwiftUI

struct OnboardingDictationSandboxSlide: View {
    let isActive: Bool
    @ObservedObject var dictationManager: DictationManager
    let onContinue: () -> Void

    @State private var text: String = ""
    @State private var hasDictatedOnce: Bool = false
    @FocusState private var fieldFocused: Bool

    var body: some View {
        VStack(spacing: 24) {
            Spacer(minLength: 0)

            VStack(spacing: 8) {
                Text(hasDictatedOnce ? "Looks great." : "Try it now")
                    .font(.system(size: 30, weight: .bold))
                    .foregroundStyle(Palette.textPrimary)

                HStack(spacing: 6) {
                    Text(hasDictatedOnce ? "You can dictate from any app the same way." : "Hold")
                    if !hasDictatedOnce {
                        keyChip(dictationManager.selectedHotkey.shortLabel)
                        Text("and speak. Release to insert.")
                    }
                }
                .font(.system(size: 14))
                .foregroundStyle(Palette.textSecondary)
            }

            sandboxField

            HStack(spacing: 12) {
                Button("Continue", action: onContinue)
                    .buttonStyle(WaiPrimaryButtonStyle(isDisabled: !hasDictatedOnce))
                    .disabled(!hasDictatedOnce)
                    .accessibilityIdentifier("onboarding-sandbox-continue")
                    .keyboardShortcut(.defaultAction)
            }

            Spacer(minLength: 0)
        }
        .padding(.horizontal, Spacing.xl)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .opacity(isActive ? 1 : 0)
        .offset(y: isActive ? 0 : 16)
        .animation(.easeOut(duration: 0.45).delay(0.1), value: isActive)
        .onChange(of: isActive) { _, newValue in
            if newValue {
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.45) {
                    fieldFocused = true
                }
            } else {
                fieldFocused = false
            }
        }
        .onChange(of: text) { _, newValue in
            if !hasDictatedOnce, !newValue.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                hasDictatedOnce = true
            }
        }
    }

    @ViewBuilder
    private var sandboxField: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Compose")
                .font(.system(size: 11, weight: .medium))
                .tracking(0.6)
                .foregroundStyle(Palette.textTertiary)
                .textCase(.uppercase)

            TextField("Compose a message…", text: $text, axis: .vertical)
                .textFieldStyle(.plain)
                .font(.system(size: 16))
                .padding(16)
                .lineLimit(3...6)
                .frame(maxWidth: .infinity, alignment: .topLeading)
                .background(
                    RoundedRectangle(cornerRadius: 14, style: .continuous)
                        .fill(Color(NSColor.windowBackgroundColor))
                )
                .overlay(
                    RoundedRectangle(cornerRadius: 14, style: .continuous)
                        .strokeBorder(fieldFocused ? Palette.accent : Palette.border, lineWidth: fieldFocused ? 2 : 1)
                )
                .focused($fieldFocused)
                .accessibilityIdentifier("onboarding-sandbox-textfield")
        }
        .frame(maxWidth: 640)
    }

    @ViewBuilder
    private func keyChip(_ label: String) -> some View {
        Text(label)
            .font(.system(size: 12, weight: .medium, design: .monospaced))
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(
                RoundedRectangle(cornerRadius: 4, style: .continuous)
                    .fill(Palette.accent.opacity(0.15))
            )
    }
}
