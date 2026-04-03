import AppKit
import SwiftUI
import WaiComputerKit

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
                    // Copy all transcript button
                    HStack {
                        Spacer()
                        Button {
                            let text = segments.map { seg in
                                let speaker = seg.speaker ?? "Speaker"
                                let ts = seg.formattedTimestamp
                                return "[\(speaker), \(ts)] \(seg.content)"
                            }.joined(separator: "\n")
                            NSPasteboard.general.clearContents()
                            NSPasteboard.general.setString(text, forType: .string)
                            copied = true
                            Task {
                                try? await Task.sleep(for: .seconds(1.5))
                                copied = false
                            }
                        } label: {
                            Image(systemName: copied ? "checkmark" : "doc.on.doc")
                                .font(Typography.caption)
                                .foregroundStyle(copied ? Palette.accent : Palette.textTertiary)
                        }
                        .buttonStyle(.plain)
                        .help(copied ? "Copied!" : "Copy Transcript")
                    }

                    ForEach(segments) { segment in
                        SegmentRowView(segment: segment)
                    }
                }
                .padding(Spacing.lg)
            }
            .accessibilityIdentifier("transcript-content")
        }
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
