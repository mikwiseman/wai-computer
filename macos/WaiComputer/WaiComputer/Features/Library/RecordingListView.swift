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
        VStack(alignment: .leading, spacing: Spacing.xs) {
            Text(recording.title ?? "Untitled")
                .font(Typography.headingMedium)
                .lineLimit(1)

            HStack(spacing: Spacing.sm) {
                Circle()
                    .fill(Palette.typeColor(recording.type))
                    .frame(width: 6, height: 6)

                Text(recording.createdAt.formatted(date: .abbreviated, time: .shortened))
                    .font(Typography.label)
                    .foregroundStyle(Palette.textSecondary)

                if let duration = recording.durationSeconds, duration > 0 {
                    Text(formatDuration(duration))
                        .font(Typography.mono)
                        .foregroundStyle(Palette.textSecondary)
                }
            }
        }
        .padding(.vertical, Spacing.sm)
    }

    private func formatDuration(_ seconds: Int) -> String {
        let mins = seconds / 60
        let secs = seconds % 60
        return String(format: "%d:%02d", mins, secs)
    }
}
