import Foundation
import SwiftUI
import WaiComputerKit

struct OnboardingDictationSandboxSlide: View {
    let isActive: Bool
    @ObservedObject var dictationManager: DictationManager
    let onContinue: () -> Void
    @EnvironmentObject private var languageManager: LanguageManager

    @State private var text: String = ""
    @State private var hasDictatedOnce: Bool = false
    @State private var textBeforeCurrentUtterance: String?
    @State private var pendingFinalTranscript: PendingFinalTranscript?
    @State private var pendingAppendTask: Task<Void, Never>?
    @FocusState private var fieldFocused: Bool

    var body: some View {
        VStack(spacing: 24) {
            Spacer(minLength: 0)

            VStack(spacing: 8) {
                Text(hasDictatedOnce
                    ? t("Looks great.", "Отлично.")
                    : t("Try dictation now", "Попробуй диктовку")
                )
                    .font(.system(size: 30, weight: .bold))
                    .foregroundStyle(Palette.textPrimary)

                instructionLine
            }

            sandboxField

            statusPill

            HStack(spacing: 12) {
                Button(t("Continue", "Продолжить"), action: onContinue)
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
        .onChangeCompat(of: isActive) { _, newValue in
            if newValue {
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.45) {
                    fieldFocused = true
                }
            } else {
                fieldFocused = false
                pendingAppendTask?.cancel()
                pendingAppendTask = nil
                pendingFinalTranscript = nil
                textBeforeCurrentUtterance = nil
            }
        }
        .onChangeCompat(of: text) { _, newValue in
            if !hasDictatedOnce, !newValue.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                hasDictatedOnce = true
            }
        }
        .onChangeCompat(of: dictationManager.state) { oldValue, newValue in
            if textBeforeCurrentUtterance == nil,
               (newValue == .connecting || newValue == .listening) {
                textBeforeCurrentUtterance = text
            }
            if oldValue != .idle, newValue == .idle {
                schedulePendingFinalTranscriptAppend()
                textBeforeCurrentUtterance = nil
            }
        }
        // DictationManager publishes the final transcript before TextInserter
        // finishes pasting into the target field. Keep it pending until the
        // manager returns to idle, then append only if TextInserter did not
        // already update this sandbox field.
        .onChangeCompat(of: dictationManager.lastFinalTranscript) { oldValue, newValue in
            guard isActive, let inserted = newValue, inserted != oldValue, !inserted.isEmpty else { return }
            pendingFinalTranscript = PendingFinalTranscript(
                text: inserted,
                textBeforeUtterance: textBeforeCurrentUtterance
            )
            if dictationManager.state == .idle {
                schedulePendingFinalTranscriptAppend()
            }
        }
        .onDisappear {
            pendingAppendTask?.cancel()
            pendingAppendTask = nil
            pendingFinalTranscript = nil
        }
    }

    @ViewBuilder
    private var instructionLine: some View {
        HStack(spacing: 6) {
            if hasDictatedOnce {
                Text(t("You can dictate from any app the same way.", "Так же можно диктовать в любом приложении."))
            } else {
                Text(t("Hold", "Зажми"))
                keyChip(dictationManager.selectedHotkey.onboardingShortLabel(language: languageManager.current))
                Text(t("and speak. Release to insert.", "и говори. Отпусти, чтобы вставить текст."))
            }
        }
        .font(.system(size: 14))
        .foregroundStyle(Palette.textSecondary)
    }

    @ViewBuilder
    private var sandboxField: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(t("Compose", "Текст"))
                .font(.system(size: 11, weight: .medium))
                .tracking(0.6)
                .foregroundStyle(Palette.textTertiary)
                .textCase(.uppercase)

            TextField(t("Compose a message…", "Надиктуй сообщение…"), text: $text, axis: .vertical)
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
                Text(t("Connecting…", "Подключаемся…"))
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(Palette.textSecondary)
            case .listening:
                Image(systemName: "waveform")
                    .variableColorIterativeEffectCompat()
                    .font(.system(size: 13))
                    .foregroundStyle(Palette.accent)
                Text(t("Listening — keep the key held.", "Слушаем — держи клавишу."))
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(Palette.accent)
            case .processing:
                ProgressView().controlSize(.small)
                Text(t("Transcribing…", "Распознаем…"))
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(Palette.textSecondary)
            case .inserting:
                ProgressView().controlSize(.small)
                Text(t("Inserting…", "Вставляем…"))
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

    private func appendDictatedText(_ inserted: String, textBeforeUtterance: String?) {
        let nextText = OnboardingDictationSandboxPolicy.textAfterFinalTranscript(
            currentText: text,
            textBeforeUtterance: textBeforeUtterance,
            finalTranscript: inserted
        )
        guard nextText != text else {
            hasDictatedOnce = true
            textBeforeCurrentUtterance = nil
            return
        }
        text = nextText
        hasDictatedOnce = true
        textBeforeCurrentUtterance = nil
    }

    private func schedulePendingFinalTranscriptAppend() {
        pendingAppendTask?.cancel()
        guard let pending = pendingFinalTranscript else { return }

        pendingAppendTask = Task { @MainActor in
            try? await Task.sleep(for: .milliseconds(250))
            guard !Task.isCancelled, isActive, pendingFinalTranscript == pending else { return }
            appendDictatedText(pending.text, textBeforeUtterance: pending.textBeforeUtterance)
            pendingFinalTranscript = nil
            pendingAppendTask = nil
        }
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

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

private struct PendingFinalTranscript: Equatable {
    let text: String
    let textBeforeUtterance: String?
}
