import AppKit
import SwiftUI
import WaiComputerKit

struct MacTranscriptView: View {
    let segments: [Segment]
    var recordingId: String?
    var onAssigned: ((RecordingDetail) -> Void)?
    @State private var copied = false

    var body: some View {
        if segments.isEmpty {
            ContentUnavailableView(
                "No Transcript",
                systemImage: "text.alignleft",
                description: Text("This recording doesn't have a transcript yet.")
            )
            .accessibilityIdentifier("transcript-empty-state")
        } else {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: Spacing.xl) {
                    HStack {
                        Text("Transcript")
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

    private var transcriptText: String {
        segments.map { seg in
            let speaker = seg.displayName ?? seg.rawLabel ?? seg.speaker ?? "Speaker"
            let timestamp = seg.formattedTimestamp
            return "[\(speaker), \(timestamp)] \(seg.content)"
        }
        .joined(separator: "\n")
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
            Label(copied ? "Copied" : "Copy Transcript", systemImage: copied ? "checkmark" : "doc.on.doc")
        }
        .buttonStyle(WaiGhostButtonStyle())
        .help(copied ? "Copied!" : "Copy transcript")
    }
}

struct SegmentRowView: View {
    let segment: Segment
    let recordingId: String?
    let onAssigned: ((RecordingDetail) -> Void)?

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
        segment.displayName ?? segment.rawLabel ?? segment.speaker
    }
}
