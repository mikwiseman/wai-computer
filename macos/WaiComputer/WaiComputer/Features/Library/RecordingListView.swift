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
    @FocusState private var listFocused: Bool

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
                    let canRemoveFromFolder = canRemoveFromFolder(
                        recording: recording,
                        contextSelection: contextSelection
                    )

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
        .focusable()
        .focused($listFocused)
        .focusedValue(\.macSelectionCommands, listFocused ? selectionCommandContext : nil)
        .disabled(isOperationInProgress)
        .onDeleteCommand {
            deleteSelectedRecordings()
        }
        .simultaneousGesture(TapGesture().onEnded { listFocused = true })
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

    private func canRemoveFromFolder(recording: Recording, contextSelection: [String]) -> Bool {
        if contextSelection.count == 1 {
            return recording.folderId != nil
        }

        let selectedIds = Set(contextSelection)
        return recordings.contains { selectedIds.contains($0.id) && $0.folderId != nil }
    }

    private var visibleRecordingIds: [String] {
        recordings.map(\.id)
    }

    private var selectedIdsInVisibleOrder: [String] {
        visibleRecordingIds.filter { selectedRecordingIds.contains($0) }
    }

    private var canActOnSelection: Bool {
        !selectedRecordingIds.isEmpty && !isOperationInProgress
    }

    private var selectionCommandContext: MacSelectionCommandContext {
        MacSelectionCommandContext(
            canSelectAll: !recordings.isEmpty && selectedRecordingIds.count < recordings.count && !isOperationInProgress,
            canClearSelection: !selectedRecordingIds.isEmpty && !isOperationInProgress,
            canDelete: canActOnSelection,
            canMoveToTrash: canActOnSelection && !isTrash,
            canRestore: canActOnSelection && isTrash,
            canDeletePermanently: canActOnSelection && isTrash,
            selectAll: selectAllRecordings,
            clearSelection: clearRecordingSelection,
            delete: deleteSelectedRecordings,
            moveToTrash: moveSelectedRecordingsToTrash,
            restore: restoreSelectedRecordings,
            deletePermanently: deleteSelectedRecordingsPermanently
        )
    }

    private func selectAllRecordings() {
        guard !isOperationInProgress else { return }
        selectedRecordingIds = Set(recordings.map(\.id))
    }

    private func clearRecordingSelection() {
        guard !isOperationInProgress else { return }
        selectedRecordingIds.removeAll()
    }

    private func deleteSelectedRecordings() {
        if isTrash {
            deleteSelectedRecordingsPermanently()
        } else {
            moveSelectedRecordingsToTrash()
        }
    }

    private func moveSelectedRecordingsToTrash() {
        let ids = selectedIdsInVisibleOrder
        guard !ids.isEmpty, !isOperationInProgress, !isTrash else { return }
        onTrash(ids)
    }

    private func restoreSelectedRecordings() {
        let ids = selectedIdsInVisibleOrder
        guard !ids.isEmpty, !isOperationInProgress, isTrash else { return }
        onRestore(ids)
    }

    private func deleteSelectedRecordingsPermanently() {
        let ids = selectedIdsInVisibleOrder
        guard !ids.isEmpty, !isOperationInProgress, isTrash else { return }
        onPermanentDelete(ids)
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

                Text(MacDateFormatting.listTimestamp(
                    from: recording.createdAt,
                    language: languageManager.current
                ))
                    .font(Typography.label)
                    .foregroundStyle(Palette.textSecondary)

                if let duration = recording.durationSeconds, duration > 0 {
                    Text(MacDateFormatting.duration(seconds: duration))
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
