import SwiftUI
import WaiComputerKit

struct MacTranscriptView: View {
    let segments: [Segment]

    var body: some View {
        if segments.isEmpty {
            ContentUnavailableView(
                "No Transcript",
                systemImage: "text.alignleft",
                description: Text("This recording doesn't have a transcript yet.")
            )
        } else {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: Spacing.xl) {
                    ForEach(segments) { segment in
                        SegmentRowView(segment: segment)
                    }
                }
                .padding(Spacing.lg)
            }
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
