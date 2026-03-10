import SwiftUI
import WaiComputerKit

struct RecordingListView: View {
    let recordings: [Recording]
    let folders: [Folder]
    let isTrash: Bool
    @Binding var selectedRecordingIds: Set<String>
    let onTrash: ([String]) -> Void
    let onRestore: ([String]) -> Void
    let onPermanentDelete: ([String]) -> Void
    let onMoveToFolder: ([String], String?) -> Void

    var body: some View {
        List(recordings, selection: $selectedRecordingIds) { recording in
            RecordingRowView(recording: recording)
                .tag(recording.id)
                .contextMenu {
                    let contextSelection = selection(for: recording.id)

                    if isTrash {
                        Button("Restore") {
                            onRestore(contextSelection)
                        }

                        Button("Delete Permanently", role: .destructive) {
                            onPermanentDelete(contextSelection)
                        }
                    } else {
                        Menu("Move to Folder") {
                            Button("Unfiled") {
                                onMoveToFolder(contextSelection, nil)
                            }

                            ForEach(folders) { folder in
                                Button(folder.name) {
                                    onMoveToFolder(contextSelection, folder.id)
                                }
                            }
                        }

                        Button("Move to Trash", role: .destructive) {
                            onTrash(contextSelection)
                        }
                    }
                }
        }
        .listStyle(.inset)
        .onDeleteCommand {
            let ids = Array(selectedRecordingIds)
            guard !ids.isEmpty else { return }
            if isTrash {
                onPermanentDelete(ids)
            } else {
                onTrash(ids)
            }
        }
    }

    private func selection(for recordingId: String) -> [String] {
        if selectedRecordingIds.contains(recordingId) {
            return Array(selectedRecordingIds)
        }
        return [recordingId]
    }
}

struct RecordingRowView: View {
    let recording: Recording

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            HStack(spacing: Spacing.sm) {
                Text(recording.title ?? "Untitled")
                    .font(Typography.headingMedium)
                    .lineLimit(1)

                Spacer(minLength: Spacing.sm)

                if let statusText = recording.statusDisplayText {
                    Text(statusText)
                        .font(Typography.label)
                        .foregroundStyle(statusColor)
                        .lineLimit(1)
                        .fixedSize(horizontal: true, vertical: false)
                }
            }

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

    private var statusColor: Color {
        recording.isFailedUpload ? Palette.recording : Palette.textSecondary
    }
}
