import AppKit
import SwiftUI
import WaiComputerKit

struct MacTranscriptView: View {
    let segments: [Segment]
    var availability: MacTranscriptAvailability = .content
    var localRecoveryManifest: RecordingBackupManifest?
    var recordingId: String?
    var onAssigned: ((RecordingDetail) -> Void)?
    @EnvironmentObject private var languageManager: LanguageManager
    @State private var copied = false

    var body: some View {
        Group {
            if segments.isEmpty {
                emptyState
            } else {
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: Spacing.xl) {
                        HStack {
                            Text(t("Transcript", "Расшифровка"))
                                .waiSectionHeader()
                            Spacer()
                            copyTranscriptButton
                        }

                        ForEach(TranscriptRendering.mergeTurns(segments, languageCode: speakerLanguageCode)) { turn in
                            SegmentRowView(
                                segment: turn.displaySegment,
                                recordingId: recordingId,
                                onAssigned: onAssigned
                            )
                        }
                    }
                    .padding(.horizontal, Spacing.xxl)
                    .padding(.vertical, Spacing.xl)
                }
                .accessibilityIdentifier("transcript-content")
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    @ViewBuilder
    private var emptyState: some View {
        if availability == .savedLocally {
            ContentUnavailableViewCompat(
                t("Saved locally", "Сохранено локально"),
                systemImage: "externaldrive",
                description: Text(savedLocallyDescription)
            )
            .accessibilityIdentifier("transcript-local-recovery-state")
        } else if availability == .processing {
            ContentUnavailableViewCompat(
                t("Transcript is processing", "Расшифровка готовится"),
                systemImage: "hourglass",
                description: Text(t(
                    "WaiComputer is processing this recording. The transcript will appear here automatically.",
                    "WaiComputer обрабатывает запись. Расшифровка появится здесь автоматически."
                ))
            )
            .accessibilityIdentifier("transcript-processing-state")
        } else {
            ContentUnavailableViewCompat(
                t("No Transcript", "Нет расшифровки"),
                systemImage: "text.alignleft",
                description: Text(t("This recording doesn't have a transcript yet.", "У этой записи пока нет расшифровки."))
            )
            .accessibilityIdentifier("transcript-empty-state")
        }
    }

    private var savedLocallyDescription: String {
        if localRecoveryManifest?.requiresAuthentication == true {
            return t(
                "Sign in again to sync this recording.",
                "Войди снова, чтобы синхронизировать эту запись."
            )
        }
        if localRecoveryManifest?.isPermanentFailure == true {
            return t(
                "This recording needs attention before it can sync.",
                "Эта запись требует внимания перед синхронизацией."
            )
        }
        if localRecoveryManifest?.isServerProcessing == true {
            return t(
                "Audio is stored on this Mac while server processing finishes. WaiComputer will keep checking automatically.",
                "Аудио сохранено на этом Mac, пока сервер завершает обработку. WaiComputer продолжит проверять автоматически."
            )
        }
        return t(
            "This recording is stored on this Mac. WaiComputer will sync it automatically when the connection is available.",
            "Эта запись сохранена на этом Mac. WaiComputer синхронизирует ее автоматически, когда соединение будет доступно."
        )
    }

    private func copyTranscript(style: TranscriptStyle) {
        let text = TranscriptRendering.transcriptText(
            segments,
            style: style,
            languageCode: speakerLanguageCode
        )
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(text, forType: .string)
        copied = true
        Task {
            try? await Task.sleep(for: .seconds(1.5))
            copied = false
        }
    }

    private var speakerLanguageCode: String {
        switch languageManager.current {
        case .followSystem:
            return languageManager.preferredLocale.identifier
        case .english, .russian:
            return languageManager.current.rawValue
        }
    }

    private var copyTranscriptButton: some View {
        // Single click copies clean prose (the common case); the menu exposes the
        // timestamped variant without making it the default.
        Menu {
            Button {
                copyTranscript(style: .plain)
            } label: {
                Label(t("Copy text", "Скопировать текст"), systemImage: "doc.on.doc")
            }
            Button {
                copyTranscript(style: .timestamped)
            } label: {
                Label(t("Copy with timestamps", "Скопировать с тайм-кодами"), systemImage: "clock")
            }
        } label: {
            Label(copied ? t("Copied", "Скопировано") : t("Copy Transcript", "Скопировать расшифровку"), systemImage: copied ? "checkmark" : "doc.on.doc")
        } primaryAction: {
            copyTranscript(style: .plain)
        }
        .menuStyle(.borderlessButton)
        .fixedSize()
        .help(t("Copy transcript", "Скопировать расшифровку"))
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}

struct SegmentRowView: View {
    let segment: Segment
    let recordingId: String?
    let onAssigned: ((RecordingDetail) -> Void)?
    @EnvironmentObject private var languageManager: LanguageManager

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            HStack(spacing: Spacing.sm) {
                if let recordingId, let rawLabel = effectiveRawLabel, !rawLabel.isEmpty {
                    SpeakerChipView(
                        segment: segment,
                        recordingId: recordingId,
                        onAssigned: { detail in onAssigned?(detail) }
                    )
                } else if let speaker = effectiveDisplayLabel {
                    Text(speaker)
                        .font(Typography.label)
                        .foregroundStyle(Palette.textSecondary)
                }

                Text(segment.formattedTimestamp)
                    .font(Typography.mono)
                    .foregroundStyle(Palette.textTertiary)
            }

            Text(segment.content)
                .font(Typography.reading)
                .lineSpacing(6)
                .textSelection(.enabled)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var effectiveRawLabel: String? {
        segment.rawLabel ?? segment.speaker
    }

    private var effectiveDisplayLabel: String? {
        segment.userFacingSpeakerLabel(languageCode: speakerLanguageCode)
    }

    private var speakerLanguageCode: String {
        switch languageManager.current {
        case .followSystem:
            return languageManager.preferredLocale.identifier
        case .english, .russian:
            return languageManager.current.rawValue
        }
    }
}
