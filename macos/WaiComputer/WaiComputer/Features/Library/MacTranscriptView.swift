import AppKit
import SwiftUI
import WaiComputerKit

struct MacTranscriptView: View {
    let segments: [Segment]
    var status: RecordingStatus = .ready
    var recordingId: String?
    var onAssigned: ((RecordingDetail) -> Void)?
    @EnvironmentObject private var languageManager: LanguageManager
    @State private var copied = false

    var body: some View {
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

                    ForEach(segments) { segment in
                        SegmentRowView(
                            segment: segment,
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

    @ViewBuilder
    private var emptyState: some View {
        if isProcessing {
            ContentUnavailableView(
                t("Transcript is processing", "Расшифровка готовится"),
                systemImage: "hourglass",
                description: Text(t(
                    "WaiComputer is processing this recording. The transcript will appear here automatically.",
                    "WaiComputer обрабатывает запись. Расшифровка появится здесь автоматически."
                ))
            )
            .accessibilityIdentifier("transcript-processing-state")
        } else {
            ContentUnavailableView(
                t("No Transcript", "Нет расшифровки"),
                systemImage: "text.alignleft",
                description: Text(t("This recording doesn't have a transcript yet.", "У этой записи пока нет расшифровки."))
            )
            .accessibilityIdentifier("transcript-empty-state")
        }
    }

    private var isProcessing: Bool {
        switch status {
        case .pendingUpload, .uploading, .processing:
            return true
        case .ready, .failed:
            return false
        }
    }

    private var transcriptText: String {
        segments.map { seg in
            let speaker = seg.userFacingSpeakerLabel(languageCode: speakerLanguageCode)
                ?? t("Speaker", "Говорящий")
            let timestamp = seg.formattedTimestamp
            return "[\(speaker), \(timestamp)] \(seg.content)"
        }
        .joined(separator: "\n")
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
        Button {
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(transcriptText, forType: .string)
            copied = true
            Task {
                try? await Task.sleep(for: .seconds(1.5))
                copied = false
            }
        } label: {
            Label(copied ? t("Copied", "Скопировано") : t("Copy Transcript", "Скопировать расшифровку"), systemImage: copied ? "checkmark" : "doc.on.doc")
        }
        .buttonStyle(WaiGhostButtonStyle())
        .help(copied ? t("Copied!", "Скопировано") : t("Copy transcript", "Скопировать расшифровку"))
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
                        .foregroundStyle(Palette.accent)
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
