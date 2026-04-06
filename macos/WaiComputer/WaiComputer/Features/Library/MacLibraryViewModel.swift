import Foundation
import WaiComputerKit

@MainActor
class MacLibraryViewModel: ObservableObject {
    @Published var recordings: [Recording] = []
    @Published var trashedRecordings: [Recording] = []
    @Published var folders: [Folder] = []
    @Published private(set) var localRecoveryRecordingIDs: Set<String> = []
    @Published var isLoading = false
    @Published var isRefreshing = false
    @Published var error: String?

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
                    guard let message = manifest.lastErrorMessage?
                        .trimmingCharacters(in: .whitespacesAndNewlines),
                          !message.isEmpty
                    else {
                        return nil
                    }
                    return recordingId
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
        error = nil

        do {
            for id in ids {
                _ = try await apiClient.moveRecording(id: id, folderId: folderId)
            }
            await loadLibrary(apiClient: apiClient)
        } catch {
            self.error = error.userFacingMessage(context: .library)
        }
    }

    func trashRecordings(ids: [String], apiClient: APIClient) async {
        guard !ids.isEmpty else { return }
        error = nil

        do {
            for id in ids {
                try await apiClient.deleteRecording(id: id)
            }
            await loadLibrary(apiClient: apiClient)
        } catch {
            self.error = error.userFacingMessage(context: .library)
        }
    }

    func restoreRecordings(ids: [String], apiClient: APIClient) async {
        guard !ids.isEmpty else { return }
        error = nil

        do {
            for id in ids {
                _ = try await apiClient.restoreRecording(id: id)
            }
            await loadLibrary(apiClient: apiClient)
        } catch {
            self.error = error.userFacingMessage(context: .library)
        }
    }

    func permanentlyDeleteRecordings(ids: [String], apiClient: APIClient) async {
        guard !ids.isEmpty else { return }
        error = nil

        do {
            for id in ids {
                try await apiClient.deleteRecording(id: id, permanent: true)
            }
            await loadLibrary(apiClient: apiClient)
        } catch {
            self.error = error.userFacingMessage(context: .library)
        }
    }

    private func shouldBackgroundRefresh(for recording: Recording) -> Bool {
        switch recording.status {
        case .pendingUpload, .uploading, .processing:
            return true
        case .ready, .failed:
            return false
        }
    }
}
