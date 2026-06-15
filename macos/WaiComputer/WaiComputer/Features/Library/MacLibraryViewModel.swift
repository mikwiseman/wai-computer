import Foundation
import WaiComputerKit

enum LibraryBulkOperationKind: Equatable {
    case moving
    case movingToTrash
    case restoring
    case deletingPermanently
}

struct LibraryBulkOperation: Equatable {
    let kind: LibraryBulkOperationKind
    let totalCount: Int
    var completedCount: Int

    var isDeterminate: Bool {
        completedCount > 0 && totalCount > 0
    }
}

@MainActor
class MacLibraryViewModel: ObservableObject {
    @Published var recordings: [Recording] = [] {
        didSet { recordingsRevision &+= 1 }
    }
    @Published var trashedRecordings: [Recording] = [] {
        didSet { trashedRecordingsRevision &+= 1 }
    }
    @Published var folders: [Folder] = [] {
        didSet { foldersRevision &+= 1 }
    }
    @Published private(set) var localRecoveryRecordingIDs: Set<String> = []
    /// Recordings whose local backup hit a permanent sync failure (e.g. deleted
    /// on the server). Surfaced as "needs attention" rather than "saved locally".
    @Published private(set) var permanentLocalFailureRecordingIDs: Set<String> = []
    @Published private(set) var bulkOperation: LibraryBulkOperation?
    @Published var isLoading = false
    @Published var isRefreshing = false
    @Published var error: String?

    private(set) var recordingsRevision = 0
    private(set) var trashedRecordingsRevision = 0
    private(set) var foldersRevision = 0
    private var loadGeneration = 0
    private var processingRefreshTask: Task<Void, Never>?

    deinit {
        processingRefreshTask?.cancel()
    }

    func filteredRecordings(type: RecordingType? = nil, folderId: String? = nil, trashed: Bool = false) -> [Recording] {
        let source = trashed ? trashedRecordings : recordings

        return source.filter { recording in
            let matchesType = type == nil || recording.type == type
            let matchesFolder = folderId == nil || recording.folderId == folderId
            return matchesType && matchesFolder
        }
    }

    func loadLibrary(apiClient: APIClient) async {
        let hasExistingContent = !recordings.isEmpty || !trashedRecordings.isEmpty || !folders.isEmpty
        loadGeneration += 1
        let generation = loadGeneration
        if hasExistingContent {
            isRefreshing = true
        } else {
            isLoading = true
        }
        error = nil

        defer {
            if generation == loadGeneration {
                isLoading = false
                isRefreshing = false
            }
        }

        do {
            async let active = apiClient.listRecordings(limit: 100)
            async let trashed = apiClient.listRecordings(limit: 100, trashed: true)
            async let folderList = apiClient.listFolders()

            let activeRecordings = try await active
            let trashedItems = try await trashed
            let folderItems = try await folderList
            let backupManifests = (try? RecordingBackupStore.manifestsByRecordingId()) ?? [:]
            guard generation == loadGeneration else { return }

            recordings = activeRecordings
            trashedRecordings = trashedItems
            folders = folderItems
            localRecoveryRecordingIDs = Set(
                backupManifests.compactMap { element in
                    let recordingId = element.key
                    let manifest = element.value
                    return shouldShowLocalRecoveryMarker(for: manifest) ? recordingId : nil
                }
            )
            permanentLocalFailureRecordingIDs = Set(
                backupManifests.compactMap { element in
                    element.value.isPermanentFailure ? element.key : nil
                }
            )

            processingRefreshTask?.cancel()
            if !backupManifests.isEmpty {
                await PendingRecordingSyncCoordinator.shared.scheduleSync(using: apiClient)
            }
            if activeRecordings.contains(where: shouldBackgroundRefresh) {
                processingRefreshTask = Task { [weak self] in
                    try? await Task.sleep(for: .seconds(4))
                    guard !Task.isCancelled else { return }
                    await self?.loadLibrary(apiClient: apiClient)
                }
            }
        } catch {
            guard generation == loadGeneration else { return }
            if hasExistingContent {
                NSLog("[Library] Background refresh failed: %@", error.localizedDescription)
                let stillRefreshing = recordings.contains(where: shouldBackgroundRefresh)
                if stillRefreshing {
                    self.error = error.userFacingMessage(context: .library)
                    processingRefreshTask?.cancel()
                    processingRefreshTask = Task { [weak self] in
                        try? await Task.sleep(for: .seconds(6))
                        guard !Task.isCancelled else { return }
                        await self?.loadLibrary(apiClient: apiClient)
                    }
                }
            } else {
                self.error = error.userFacingMessage(context: .library)
            }
        }
    }

    func setRecordings(_ recordings: [Recording]) {
        self.recordings = recordings
        trashedRecordings = []
        localRecoveryRecordingIDs = []
        permanentLocalFailureRecordingIDs = []
        isLoading = false
        isRefreshing = false
        error = nil
    }

    func setFolders(_ folders: [Folder]) {
        self.folders = folders
    }

    @discardableResult
    func createFolder(name: String, apiClient: APIClient) async -> Folder? {
        do {
            let folder = try await apiClient.createFolder(name: name)
            folders.append(folder)
            folders.sort { lhs, rhs in
                if lhs.name.caseInsensitiveCompare(rhs.name) == .orderedSame {
                    return lhs.createdAt < rhs.createdAt
                }
                return lhs.name.localizedCaseInsensitiveCompare(rhs.name) == .orderedAscending
            }
            return folder
        } catch {
            self.error = error.userFacingMessage(context: .library)
            return nil
        }
    }

    func moveRecordings(ids: [String], to folderId: String?, apiClient: APIClient) async {
        guard !ids.isEmpty else { return }
        await runBulkOperation(
            ids: ids,
            kind: .moving,
            action: .move,
            folderId: folderId,
            apiClient: apiClient
        )
    }

    @discardableResult
    func renameFolder(id: String, name: String, apiClient: APIClient) async -> Folder? {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        error = nil

        do {
            let folder = try await apiClient.updateFolder(id: id, name: trimmed)
            await loadLibrary(apiClient: apiClient)
            return folder
        } catch {
            self.error = error.userFacingMessage(context: .library)
            return nil
        }
    }

    @discardableResult
    func deleteFolder(id: String, apiClient: APIClient) async -> Bool {
        error = nil

        do {
            try await apiClient.deleteFolder(id: id)
            await loadLibrary(apiClient: apiClient)
            return true
        } catch {
            self.error = error.userFacingMessage(context: .library)
            return false
        }
    }

    func renameRecording(id: String, newTitle: String, apiClient: APIClient) async {
        let trimmed = newTitle.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        error = nil

        do {
            _ = try await apiClient.updateRecording(id: id, title: trimmed)
            await loadLibrary(apiClient: apiClient)
        } catch {
            self.error = error.userFacingMessage(context: .library)
        }
    }

    func trashRecordings(ids: [String], apiClient: APIClient) async {
        guard !ids.isEmpty else { return }
        await runBulkOperation(
            ids: ids,
            kind: .movingToTrash,
            action: .delete,
            folderId: nil,
            apiClient: apiClient
        )
    }

    func restoreRecordings(ids: [String], apiClient: APIClient) async {
        guard !ids.isEmpty else { return }
        await runBulkOperation(
            ids: ids,
            kind: .restoring,
            action: .restore,
            folderId: nil,
            apiClient: apiClient
        )
    }

    func permanentlyDeleteRecordings(ids: [String], apiClient: APIClient) async {
        guard !ids.isEmpty else { return }
        error = nil
        bulkOperation = LibraryBulkOperation(
            kind: .deletingPermanently,
            totalCount: ids.count,
            completedCount: 0
        )
        defer { bulkOperation = nil }

        do {
            try await withThrowingTaskGroup(of: Void.self) { group in
                for id in ids {
                    group.addTask {
                        try await apiClient.deleteRecording(id: id, permanent: true)
                    }
                }

                var completedCount = 0
                for try await _ in group {
                    completedCount += 1
                    updateBulkOperationCompletedCount(completedCount)
                }
            }
            await loadLibrary(apiClient: apiClient)
        } catch {
            let message = error.userFacingMessage(context: .library)
            await loadLibrary(apiClient: apiClient)
            self.error = message
        }
    }

    private func runBulkOperation(
        ids: [String],
        kind: LibraryBulkOperationKind,
        action: BulkRecordingAction,
        folderId: String?,
        apiClient: APIClient
    ) async {
        error = nil
        bulkOperation = LibraryBulkOperation(kind: kind, totalCount: ids.count, completedCount: 0)
        defer { bulkOperation = nil }

        do {
            let result = try await apiClient.bulkRecordingOperation(
                recordingIds: ids,
                action: action,
                folderId: folderId
            )
            updateBulkOperationCompletedCount(result.processed)
            let partialFailureMessage: String?
            if result.failed > 0 {
                partialFailureMessage = "Processed \(result.processed) of \(ids.count) recordings. Failed: \(result.failed)."
            } else {
                partialFailureMessage = nil
            }
            await loadLibrary(apiClient: apiClient)
            if let partialFailureMessage {
                error = partialFailureMessage
            }
        } catch {
            self.error = error.userFacingMessage(context: .library)
        }
    }

    private func updateBulkOperationCompletedCount(_ completedCount: Int) {
        guard var operation = bulkOperation else { return }
        operation.completedCount = completedCount
        bulkOperation = operation
    }

    private func shouldBackgroundRefresh(for recording: Recording) -> Bool {
        switch recording.status {
        case .pendingUpload, .uploading, .processing:
            return true
        case .ready, .failed:
            return false
        }
    }

    private func shouldShowLocalRecoveryMarker(for manifest: RecordingBackupManifest) -> Bool {
        manifest.syncState != .remoteReady
    }
}
