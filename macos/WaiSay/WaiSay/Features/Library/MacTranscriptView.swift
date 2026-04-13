import AppKit
import SwiftUI
import WaiSayKit

struct MacTranscriptView: View {
    let segments: [Segment]
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
                        SegmentRowView(segment: segment)
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
            let speaker = seg.speaker ?? "Speaker"
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

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            HStack(spacing: Spacing.sm) {
                if let speaker = segment.speaker {
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
}
