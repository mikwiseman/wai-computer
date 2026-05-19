import SwiftUI

struct NewRecordingView: View {
    let onStartDual: () -> Void
    let onStartMicOnly: () -> Void
    let onImportFile: () -> Void
    let isImporting: Bool

    var body: some View {
        VStack(spacing: Spacing.xl) {
            Spacer()

            VStack(spacing: Spacing.md) {
                Image(nsImage: NSApp.applicationIconImage)
                    .resizable()
                    .frame(width: 64, height: 64)

                Text("New Recording")
                    .font(Typography.displaySmall)
            }

            // Recording options card
            VStack(spacing: 0) {
                RecordingOptionRow(
                    title: "Mic + System Audio",
                    icon: "waveform",
                    subtitle: "Records your mic and computer audio",
                    shortcut: "⌘R",
                    isPrimary: true,
                    action: onStartDual
                )
                .accessibilityIdentifier("start-recording-button")

                WaiDivider()
                    .padding(.horizontal, Spacing.md)

                RecordingOptionRow(
                    title: "Mic Only",
                    icon: "mic",
                    subtitle: "Records from your microphone only",
                    shortcut: "⇧⌘R",
                    isPrimary: false,
                    action: onStartMicOnly
                )
            }
            .background(Palette.surfaceSubtle)
            .clipShape(RoundedRectangle(cornerRadius: 8))

            // Import card (separate)
            VStack(spacing: 0) {
                RecordingOptionRow(
                    title: "Import Audio File",
                    icon: "square.and.arrow.down",
                    subtitle: "Transcribe an existing audio file",
                    shortcut: "⌘I",
                    isPrimary: false,
                    action: onImportFile
                )
                .accessibilityIdentifier("import-audio-button")
            }
            .background(Palette.surfaceSubtle)
            .clipShape(RoundedRectangle(cornerRadius: 8))
            .disabled(isImporting)
            .opacity(isImporting ? 0.5 : 1.0)

            Text("recording.hint.minDuration", bundle: .main)
                .font(Typography.caption)
                .foregroundStyle(Palette.textTertiary)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.horizontal, Spacing.md)
                .accessibilityIdentifier("recording-min-duration-hint")

            Spacer()
        }
        .frame(maxWidth: 380)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

// MARK: - Option Row

private struct RecordingOptionRow: View {
    let title: String
    let icon: String
    let subtitle: String
    let shortcut: String
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
        .onHover { isHovered = $0 }
    }
}
