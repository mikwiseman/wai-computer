import Foundation
import WaiComputerKit

@MainActor
class MacLibraryViewModel: ObservableObject {
    @Published var recordings: [Recording] = []
    @Published var trashedRecordings: [Recording] = []
    @Published var folders: [Folder] = []
    @Published var isLoading = false
    @Published var isRefreshing = false
    @Published var error: String?

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
        if hasExistingContent {
            isRefreshing = true
        } else {
            isLoading = true
        }
        error = nil

        defer {
            isLoading = false
            isRefreshing = false
        }

        do {
            async let active = apiClient.listRecordings(limit: 100)
            async let trashed = apiClient.listRecordings(limit: 100, trashed: true)
            async let folderList = apiClient.listFolders()

            recordings = try await active
            trashedRecordings = try await trashed
            folders = try await folderList
        } catch {
            self.error = error.localizedDescription
        }
    }

    func setRecordings(_ recordings: [Recording]) {
        self.recordings = recordings
        trashedRecordings = []
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
            self.error = error.localizedDescription
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
            self.error = error.localizedDescription
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
            self.error = error.localizedDescription
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
            self.error = error.localizedDescription
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
            self.error = error.localizedDescription
        }
    }
}
