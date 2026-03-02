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
                LazyVStack(alignment: .leading, spacing: 12) {
                    ForEach(segments) { segment in
                        SegmentRowView(segment: segment)
                    }
                }
                .padding()
            }
        }
    }
}

struct SegmentRowView: View {
    let segment: Segment
    @State private var isExpanded = false

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                if let speaker = segment.speaker {
                    Text(speaker)
                        .font(.caption)
                        .fontWeight(.semibold)
                        .foregroundStyle(.blue)
                }

                Text(segment.formattedTimestamp)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }

            Text(segment.content)
                .font(.body)
                .lineLimit(isExpanded ? nil : 3)
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.gray.opacity(0.06))
        .cornerRadius(8)
        .onTapGesture {
            withAnimation(.easeInOut(duration: 0.2)) {
                isExpanded.toggle()
            }
        }
    }
}
