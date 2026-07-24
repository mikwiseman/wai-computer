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

            // Translation target switcher — pick any preset target mid-dictation.
            if manager.activeMode == .translation {
                TranslationTargetChip(store: manager.translationLanguageStore)
            }

            // Duration
            if manager.state == .listening {
                Text(formattedDuration)
                    .font(Typography.mono)
                    .foregroundStyle(.white.opacity(0.6))
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
            .accessibilityLabel(OnboardingL10n.text(
                "Cancel dictation",
                "Отменить диктовку",
                language: languageManager.current
            ))
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
        MacDateFormatting.duration(seconds: Int(manager.dictationDuration))
    }
}

/// Compact target-language switcher shown in the overlay during Translation
/// mode. Click to pick any preset target (Settings → Translation targets)
/// without leaving the dictation — the choice applies when the hotkey is
/// released, because translation happens at finalize time.
private struct TranslationTargetChip: View {
    @ObservedObject var store: TranslationLanguageStore

    var body: some View {
        Menu {
            ForEach(store.enabledEntries) { entry in
                Button {
                    store.selectLanguage(entry.code)
                } label: {
                    if entry.code == store.selectedLanguageCode {
                        Label(entry.displayName, systemImage: "checkmark")
                    } else {
                        Text(entry.displayName)
                    }
                }
            }
        } label: {
            HStack(spacing: 3) {
                Image(systemName: "globe")
                    .font(.system(size: 9, weight: .semibold))
                Text(store.targetLanguageCode.uppercased())
                    .font(Typography.caption.weight(.semibold))
                if store.enabledLanguageCodes.count > 1 {
                    Image(systemName: "chevron.down")
                        .font(.system(size: 7, weight: .bold))
                }
            }
            .foregroundStyle(.white.opacity(0.85))
            .padding(.horizontal, 7)
            .padding(.vertical, 4)
            .background(.white.opacity(0.15))
            .clipShape(Capsule())
        }
        .menuStyle(.borderlessButton)
        .menuIndicator(.hidden)
        .fixedSize()
        .accessibilityIdentifier("dictation-overlay-translation-target-chip")
    }
}

/// Transient, non-activating notice shown after a dictation that degraded
/// softly (e.g. cleanup fell back to raw words). The text WAS inserted — a
/// modal alert here would interrupt typing flow for something already done.
struct DictationNoticeView: View {
    let text: String

    var body: some View {
        HStack(spacing: Spacing.sm) {
            Image(systemName: "exclamationmark.circle.fill")
                .foregroundStyle(.yellow)
            Text(text)
                .font(Typography.caption)
                .foregroundStyle(.white)
                .lineLimit(2)
                .multilineTextAlignment(.leading)
        }
        .padding(.horizontal, Spacing.md)
        .padding(.vertical, Spacing.sm)
        .background(
            RoundedRectangle(cornerRadius: Radius.lg, style: .continuous)
                .fill(Color.black.opacity(0.85))
        )
        .frame(maxWidth: 360)
    }
}
