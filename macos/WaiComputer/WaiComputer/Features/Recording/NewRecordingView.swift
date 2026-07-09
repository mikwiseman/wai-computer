import SwiftUI
import WaiComputerKit

struct NewRecordingView: View {
    let onStartRecording: () -> Void
    let onImportFile: () -> Void
    let isImporting: Bool
    @EnvironmentObject private var languageManager: LanguageManager

    var body: some View {
        VStack(spacing: Spacing.xl) {
            Spacer()

            VStack(spacing: Spacing.md) {
                ZStack {
                    RoundedRectangle(cornerRadius: Radius.lg, style: .continuous)
                        .fill(Palette.surfaceSubtle)
                        .frame(width: 64, height: 64)
                        .overlay(
                            RoundedRectangle(cornerRadius: Radius.lg, style: .continuous)
                                .strokeBorder(Palette.border, lineWidth: 1)
                        )
                    Image(systemName: "waveform")
                        .font(.system(size: 30, weight: .semibold))
                        .foregroundStyle(Palette.accent)
                }

                Text(t("New Recording", "Новая запись"))
                    .font(Typography.displaySmall)
            }

            // Recording options card
            VStack(spacing: 0) {
                // ⇧⌘R mirrors the File → Record Now menu command, which runs
                // the identical start-recording action. The hint previously
                // claimed ⌘N, which is bound to New Inbox Item.
                RecordingOptionRow(
                    title: t("Record", "Записать"),
                    icon: "waveform",
                    subtitle: t("Records your mic and computer audio", "Записывает микрофон и звук компьютера"),
                    shortcut: "⇧⌘R",
                    keyEquivalent: KeyboardShortcut("r", modifiers: [.command, .shift]),
                    isPrimary: true,
                    action: onStartRecording
                )
                .accessibilityIdentifier("start-recording-button")
            }
            .background(Palette.surfaceSubtle)
            .clipShape(RoundedRectangle(cornerRadius: Radius.md))

            // Import card (separate)
            VStack(spacing: 0) {
                // ⌘I is unbound elsewhere in the app; attach it for real so
                // the printed hint is true on this screen.
                RecordingOptionRow(
                    title: t("Import Audio or Video", "Импорт аудио или видео"),
                    icon: "square.and.arrow.down",
                    subtitle: t("Transcribe an existing audio or video file", "Расшифровать готовый аудио- или видеофайл"),
                    shortcut: "⌘I",
                    keyEquivalent: KeyboardShortcut("i", modifiers: .command),
                    isPrimary: false,
                    action: onImportFile
                )
                .accessibilityIdentifier("import-audio-button")
            }
            .background(Palette.surfaceSubtle)
            .clipShape(RoundedRectangle(cornerRadius: Radius.md))
            .disabled(isImporting)
            .opacity(isImporting ? 0.5 : 1.0)

            Spacer()
        }
        .frame(maxWidth: 380)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

// MARK: - Option Row

private struct RecordingOptionRow: View {
    let title: String
    let icon: String
    let subtitle: String
    /// Display hint — must describe `keyEquivalent`, the binding actually
    /// attached to the button.
    let shortcut: String
    let keyEquivalent: KeyboardShortcut
    let isPrimary: Bool
    let action: () -> Void

    @State private var isHovered = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: Spacing.md) {
                Image(systemName: icon)
                    .font(.system(size: 18))
                    .foregroundStyle(isPrimary ? Palette.accent : Palette.textSecondary)
                    .frame(width: 28)

                VStack(alignment: .leading, spacing: Spacing.xxs) {
                    Text(title)
                        .font(Typography.headingMedium)

                    Text(subtitle)
                        .font(Typography.bodySmall)
                        .foregroundStyle(Palette.textSecondary)
                }

                Spacer()

                Text(shortcut)
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textTertiary)
            }
            .padding(.vertical, Spacing.md)
            .padding(.horizontal, Spacing.lg)
            .background(isHovered ? Palette.surfaceHover : .clear)
        }
        .buttonStyle(.plain)
        .keyboardShortcut(keyEquivalent)
        .onHover { isHovered = $0 }
    }
}
