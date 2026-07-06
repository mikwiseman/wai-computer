import SwiftUI
import WaiComputerKit

/// The SwiftUI content displayed inside the floating dictation overlay panel.
/// Shows a compact bar with recording indicator, status, and transcript preview.
struct DictationOverlayView: View {
    @ObservedObject var manager: DictationManager
    @ObservedObject private var languageManager = LanguageManager.shared

    var body: some View {
        HStack(spacing: Spacing.md) {
            // Recording indicator
            recordingDot

            // Status text
            VStack(alignment: .leading, spacing: 1) {
                Text(statusText)
                    .font(Typography.headingSmall)
                    .foregroundStyle(.white)

                if !manager.interimTranscript.isEmpty {
                    Text(transcriptPreview)
                        .font(Typography.caption)
                        .foregroundStyle(.white.opacity(0.7))
                        .lineLimit(1)
                        // Head truncation: during live dictation the freshest
                        // words are at the END — clip the oldest ones instead.
                        .truncationMode(.head)
                }
            }

            Spacer(minLength: 0)

            // Duration
            if manager.state == .listening {
                Text(formattedDuration)
                    .font(Typography.mono)
                    .foregroundStyle(.white.opacity(0.6))
            }

            // Mode badge
            if manager.isHandsFree {
                Text(DictationCopy.handsFreeBadge(language: languageManager.current))
                    .font(.system(size: 9, weight: .semibold))
                    .foregroundStyle(Palette.onAccent)
                    .padding(.horizontal, 6)
                    .padding(.vertical, 2)
                    .background(Palette.accent)
                    .clipShape(Capsule())
            }

            // Cancel button
            Button {
                Task { await manager.cancelDictation() }
            } label: {
                Image(systemName: "xmark")
                    .font(.system(size: 10, weight: .bold))
                    .foregroundStyle(.white.opacity(0.6))
                    .frame(width: 20, height: 20)
                    .background(.white.opacity(0.15))
                    .clipShape(Circle())
            }
            .buttonStyle(.plain)
        }
        .padding(.horizontal, Spacing.lg)
        .padding(.vertical, Spacing.md)
        .frame(width: 360, height: 52)
        .background {
            // Dark-tinted Liquid Glass HUD on Tahoe; dark ultra-thin material
            // (the original look) on earlier systems.
            if #available(macOS 26.0, *) {
                Color.clear.glassEffect(
                    .regular.tint(Color.black.opacity(0.5)),
                    in: .rect(cornerRadius: Radius.lg)
                )
            } else {
                RoundedRectangle(cornerRadius: Radius.lg)
                    .fill(.ultraThinMaterial)
                    .environment(\.colorScheme, .dark)
            }
        }
        .overlay(
            RoundedRectangle(cornerRadius: Radius.lg)
                .strokeBorder(.white.opacity(0.15), lineWidth: 0.5)
        )
    }

    // MARK: - Subviews

    private var recordingDot: some View {
        Circle()
            .fill(dotColor)
            .frame(width: 10, height: 10)
            .overlay(
                Circle()
                    .fill(dotColor.opacity(0.4))
                    .frame(width: 18, height: 18)
                    .opacity(manager.state == .listening ? 1 : 0)
                    .scaleEffect(manager.state == .listening ? 1.0 : 0.5)
                    .animation(
                        manager.state == .listening
                            ? .easeInOut(duration: 0.8).repeatForever(autoreverses: true)
                            : .default,
                        value: manager.state == .listening
                    )
            )
    }

    // MARK: - Computed

    private var statusText: String {
        let status: DictationCopy.OverlayStatus
        switch manager.state {
        case .idle:
            status = .idle
        case .connecting:
            status = .connecting
        case .listening:
            status = .listening
        case .processing:
            status = .processing
        case .inserting:
            status = .inserting
        }
        return DictationCopy.overlayStatus(status, language: languageManager.current)
    }

    private var dotColor: Color {
        switch manager.state {
        case .listening: return Palette.recording
        case .processing, .inserting: return Palette.accent
        case .connecting: return .yellow
        case .idle: return .gray
        }
    }

    private var transcriptPreview: String {
        // Cheap length cap so per-update layout stays bounded; the Text's
        // .truncationMode(.head) keeps the newest words visible and renders
        // the leading ellipsis itself when the string overflows the slot.
        String(manager.interimTranscript.suffix(57))
    }

    private var formattedDuration: String {
        let seconds = Int(manager.dictationDuration)
        let mins = seconds / 60
        let secs = seconds % 60
        return String(format: "%d:%02d", mins, secs)
    }
}
