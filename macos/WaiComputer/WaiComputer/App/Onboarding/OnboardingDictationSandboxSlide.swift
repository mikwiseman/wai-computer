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

                instructionLine
            }

            sandboxField

            statusPill

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
        // The dictation overlay panel can grab window focus while recording,
        // so TextInserter (⌘V into the previously-focused field) doesn't
        // reliably land in our TextField. Bypass it: the moment
        // DictationManager publishes a final transcript while the sandbox is
        // active, append it ourselves. Works whether or not TextInserter also
        // succeeded — duplicate inserts are harmless because TextInserter
        // pastes outside our @State binding.
        .onChange(of: dictationManager.lastFinalTranscript) { oldValue, newValue in
            guard isActive, let inserted = newValue, inserted != oldValue, !inserted.isEmpty else { return }
            appendDictatedText(inserted)
        }
    }

    @ViewBuilder
    private var instructionLine: some View {
        HStack(spacing: 6) {
            if hasDictatedOnce {
                Text("You can dictate from any app the same way.")
            } else {
                Text("Hold")
                keyChip(dictationManager.selectedHotkey.shortLabel)
                Text("and speak. Release to insert.")
            }
        }
        .font(.system(size: 14))
        .foregroundStyle(Palette.textSecondary)
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
                        .strokeBorder(borderColor, lineWidth: borderWidth)
                )
                .focused($fieldFocused)
                .accessibilityIdentifier("onboarding-sandbox-textfield")
        }
        .frame(maxWidth: 640)
    }

    /// Live status pill — gives the user immediate "we hear you" feedback
    /// while DictationManager runs through its connect / listen / insert
    /// states. The empty fallback keeps layout height stable.
    @ViewBuilder
    private var statusPill: some View {
        HStack(spacing: 6) {
            switch dictationManager.state {
            case .connecting:
                ProgressView().controlSize(.small)
                Text("Connecting…")
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(Palette.textSecondary)
            case .listening:
                Image(systemName: "waveform")
                    .symbolEffect(.variableColor.iterative)
                    .font(.system(size: 13))
                    .foregroundStyle(Palette.accent)
                Text("Listening — keep the key held.")
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(Palette.accent)
            case .processing:
                ProgressView().controlSize(.small)
                Text("Transcribing…")
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(Palette.textSecondary)
            case .inserting:
                ProgressView().controlSize(.small)
                Text("Inserting…")
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(Palette.textSecondary)
            case .idle:
                if let errorText = dictationManager.error {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .font(.system(size: 12))
                        .foregroundStyle(.orange)
                    Text(errorText)
                        .font(.system(size: 12))
                        .foregroundStyle(Palette.textSecondary)
                        .lineLimit(2)
                } else {
                    // Reserve vertical space so the layout doesn't jump.
                    Text(" ").font(.system(size: 12))
                }
            }
        }
        .frame(minHeight: 18)
    }

    private var borderColor: Color {
        switch dictationManager.state {
        case .listening: return Palette.accent
        case .connecting, .processing, .inserting: return Palette.accent.opacity(0.6)
        case .idle: return fieldFocused ? Palette.accent : Palette.border
        }
    }

    private var borderWidth: CGFloat {
        switch dictationManager.state {
        case .listening: return 2
        case .connecting, .processing, .inserting: return 2
        case .idle: return fieldFocused ? 2 : 1
        }
    }

    private func appendDictatedText(_ inserted: String) {
        let trimmed = inserted.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        if text.isEmpty {
            text = trimmed
        } else {
            // Add a separator if the existing text doesn't already end with whitespace.
            let needsSpace = !(text.last?.isWhitespace ?? true)
            text += (needsSpace ? " " : "") + trimmed
        }
        hasDictatedOnce = true
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
