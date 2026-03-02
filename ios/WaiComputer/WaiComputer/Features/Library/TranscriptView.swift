import SwiftUI
import WaiComputerKit

struct TranscriptView: View {
    let segments: [Segment]

    var body: some View {
        if segments.isEmpty {
            ContentUnavailableView(
                "No Transcript",
                systemImage: "text.quote",
                description: Text("Transcript will appear here during and after recording")
            )
        } else {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 16) {
                    ForEach(segments) { segment in
                        SegmentView(segment: segment)
                    }
                }
                .padding()
            }
        }
    }
}

struct SegmentView: View {
    let segment: Segment
    @State private var isExpanded = false

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            // Speaker and timestamp
            HStack {
                if let speaker = segment.speaker {
                    Text(speaker)
                        .font(.caption)
                        .fontWeight(.semibold)
                        .foregroundStyle(.blue)
                }

                Spacer()

                Text(segment.formattedTimestamp)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }

            // Content
            Text(segment.content)
                .font(.body)
                .lineLimit(isExpanded ? nil : 3)
                .onTapGesture {
                    withAnimation {
                        isExpanded.toggle()
                    }
                }
        }
        .padding()
        .background(Color.gray.opacity(0.05))
        .cornerRadius(8)
    }
}

#Preview {
    TranscriptView(segments: [
        Segment(id: "1", speaker: "Speaker 1", content: "Hello, this is a test segment with some longer content to see how it wraps.", startMs: 0),
        Segment(id: "2", speaker: "Speaker 2", content: "This is another segment.", startMs: 5000),
    ])
}
