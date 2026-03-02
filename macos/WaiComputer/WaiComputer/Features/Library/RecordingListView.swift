import SwiftUI
import WaiComputerKit

struct RecordingListView: View {
    let recordings: [Recording]
    @Binding var selectedRecordingId: String?
    let onDelete: (String) -> Void

    var body: some View {
        List(recordings, selection: $selectedRecordingId) { recording in
            RecordingRowView(recording: recording)
                .tag(recording.id)
                .contextMenu {
                    Button("Delete", role: .destructive) {
                        onDelete(recording.id)
                    }
                }
        }
        .listStyle(.inset)
    }
}

struct RecordingRowView: View {
    let recording: Recording

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(recording.title ?? "Untitled")
                .font(.headline)
                .lineLimit(1)

            HStack(spacing: 8) {
                Text(recording.createdAt.formatted(date: .abbreviated, time: .shortened))
                    .font(.caption)
                    .foregroundStyle(.secondary)

                TypeBadge(type: recording.type)

                if let duration = recording.durationSeconds, duration > 0 {
                    Text(formatDuration(duration))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .padding(.vertical, 2)
    }

    private func formatDuration(_ seconds: Int) -> String {
        let mins = seconds / 60
        let secs = seconds % 60
        return String(format: "%d:%02d", mins, secs)
    }
}

struct TypeBadge: View {
    let type: RecordingType

    var body: some View {
        Text(type.rawValue.capitalized)
            .font(.caption2)
            .fontWeight(.medium)
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(badgeColor.opacity(0.15))
            .foregroundStyle(badgeColor)
            .clipShape(Capsule())
    }

    private var badgeColor: Color {
        switch type {
        case .meeting: return .blue
        case .note: return .green
        case .reflection: return .purple
        }
    }
}
