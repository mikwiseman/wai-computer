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
                Image("BrandIcon")
                    .resizable()
                    .interpolation(.high)
                    .scaledToFit()
                    .frame(width: 64, height: 64)

                Text(t("New Recording", "Новая запись"))
                    .font(Typography.displaySmall)
            }

            // Recording options card
            VStack(spacing: 0) {
                RecordingOptionRow(
                    title: t("Record", "Записать"),
                    icon: "waveform",
                    subtitle: t("Records your mic and computer audio", "Записывает микрофон и звук компьютера"),
                    shortcut: "⌘N",
                    isPrimary: true,
                    action: onStartRecording
                )
                .accessibilityIdentifier("start-recording-button")
            }
            .background(Palette.surfaceSubtle)
            .clipShape(RoundedRectangle(cornerRadius: 8))

            // Import card (separate)
            VStack(spacing: 0) {
                RecordingOptionRow(
                    title: t("Import Audio File", "Импорт аудиофайла"),
                    icon: "square.and.arrow.down",
                    subtitle: t("Transcribe an existing audio file", "Расшифровать готовый аудиофайл"),
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
