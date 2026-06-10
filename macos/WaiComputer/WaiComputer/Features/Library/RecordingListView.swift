import SwiftUI
import WaiComputerKit

struct RecordingListView: View {
    let recordings: [Recording]
    let folders: [Folder]
    let localRecoveryRecordingIDs: Set<String>
    let permanentLocalFailureRecordingIDs: Set<String>
    let isTrash: Bool
    let isOperationInProgress: Bool
    @Binding var selectedRecordingIds: Set<String>
    let onTrash: ([String]) -> Void
    let onRestore: ([String]) -> Void
    let onPermanentDelete: ([String]) -> Void
    let onMoveToFolder: ([String], String?) -> Void
    let onRequestRename: (String) -> Void
    @EnvironmentObject private var languageManager: LanguageManager

    var body: some View {
        List(recordings, selection: $selectedRecordingIds) { recording in
            RecordingRowView(
                recording: recording,
                hasLocalRecoveryBackup: localRecoveryRecordingIDs.contains(recording.id),
                hasPermanentLocalFailure: permanentLocalFailureRecordingIDs.contains(recording.id)
            )
                .tag(recording.id)
                .draggable(InboxDragItem(kind: .recording, id: recording.id))
                .contextMenu {
                    let contextSelection = selection(for: recording.id)
                    let contextRecordings = recordings.filter { contextSelection.contains($0.id) }
                    let canRemoveFromFolder = contextRecordings.contains { $0.folderId != nil }

                    if isTrash {
                        Button(t("Restore", "Восстановить")) {
                            onRestore(contextSelection)
                        }
                        .disabled(isOperationInProgress)

                        Button(t("Delete Permanently", "Удалить навсегда"), role: .destructive) {
                            onPermanentDelete(contextSelection)
                        }
                        .disabled(isOperationInProgress)
                    } else {
                        Button(t("Rename…", "Переименовать…")) {
                            onRequestRename(recording.id)
                        }
                        .disabled(contextSelection.count > 1 || isOperationInProgress)

                        if canRemoveFromFolder || !folders.isEmpty {
                            Menu(t("Move to Folder", "Переместить в папку")) {
                                if canRemoveFromFolder {
                                    Button(t("Remove from Folder", "Убрать из папки")) {
                                        onMoveToFolder(contextSelection, nil)
                                    }
                                    .disabled(isOperationInProgress)
                                }

                                ForEach(folders) { folder in
                                    Button(folder.name) {
                                        onMoveToFolder(contextSelection, folder.id)
                                    }
                                    .disabled(isOperationInProgress)
                                }
                            }
                            .disabled(isOperationInProgress)
                        }

                        Button(t("Move to Trash", "Переместить в корзину"), role: .destructive) {
                            onTrash(contextSelection)
                        }
                        .disabled(isOperationInProgress)
                    }
                }
        }
        .listStyle(.inset)
        .disabled(isOperationInProgress)
        .onDeleteCommand {
            let ids = Array(selectedRecordingIds)
            guard !ids.isEmpty, !isOperationInProgress else { return }
            if isTrash {
                onPermanentDelete(ids)
            } else {
                onTrash(ids)
            }
        }
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
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
    let hasLocalRecoveryBackup: Bool
    var hasPermanentLocalFailure: Bool = false
    @EnvironmentObject private var languageManager: LanguageManager

    var body: some View {
        VStack(alignment: .leading, spacing: Spacing.xs) {
            HStack(spacing: Spacing.sm) {
                Text(recording.title ?? t("Untitled", "Без названия"))
                    .font(Typography.headingMedium)
                    .lineLimit(1)
                    .truncationMode(.tail)
                    .layoutPriority(1)

                Spacer(minLength: Spacing.sm)

                if let statusText = recording.statusDisplayText(
                    hasLocalRecoveryBackup: hasLocalRecoveryBackup,
                    hasPermanentLocalFailure: hasPermanentLocalFailure,
                    languageCode: fallbackStatusLanguageCode
                ) {
                    Text(statusText)
                        .font(Typography.label)
                        .foregroundStyle(statusColor)
                        .lineLimit(1)
                        .minimumScaleFactor(0.85)
                        .truncationMode(.tail)
                        .fixedSize(horizontal: true, vertical: false)
                        .layoutPriority(2)
                }
            }

            HStack(spacing: Spacing.sm) {
                Circle()
                    .fill(Palette.typeColor(recording.type))
                    .frame(width: 6, height: 6)

                Text(MacDateFormatting.string(
                    from: recording.createdAt,
                    dateStyle: .medium,
                    timeStyle: .short,
                    language: languageManager.current
                ))
                    .font(Typography.label)
                    .foregroundStyle(Palette.textSecondary)

                if let duration = recording.durationSeconds, duration > 0 {
                    Text(formatDuration(duration))
                        .font(Typography.mono)
                        .foregroundStyle(Palette.textSecondary)
                }
            }

            if let failurePreviewText = recording.failurePreviewText,
               recording.isFailedUpload {
                Text(failurePreviewText)
                    .font(Typography.caption)
                    .foregroundStyle(Palette.textSecondary)
                    .lineLimit(1)
            }
        }
        .padding(.vertical, Spacing.xs)
        .frame(
            maxWidth: .infinity,
            minHeight: rowMinHeight,
            alignment: .leading
        )
    }

    private var rowMinHeight: CGFloat {
        if recording.failurePreviewText != nil, recording.isFailedUpload {
            return MacMainLayoutMetrics.recordingRowFailureMinHeight
        }
        return MacMainLayoutMetrics.recordingRowMinHeight
    }

    private func formatDuration(_ seconds: Int) -> String {
        let mins = seconds / 60
        let secs = seconds % 60
        return String(format: "%d:%02d", mins, secs)
    }

    private var statusColor: Color {
        (recording.isFailedUpload || hasPermanentLocalFailure) ? Palette.recording : Palette.textSecondary
    }

    private var fallbackStatusLanguageCode: String {
        switch languageManager.current {
        case .followSystem:
            return languageManager.preferredLocale.identifier
        case .english, .russian:
            return languageManager.current.rawValue
        }
    }

    private func t(_ english: String, _ russian: String) -> String {
        OnboardingL10n.text(english, russian, language: languageManager.current)
    }
}
