import Foundation
import WaiComputerKit

/// Drives the macOS Content feed: add-anything capture, kind filtering, list +
/// selected-item detail. Polls briefly after a create so the background summary
/// surfaces without a manual refresh.
@MainActor
final class MacContentFeedViewModel: ObservableObject {
    @Published var entries: [ItemListEntry] = []
    @Published var selectedId: String?
    @Published var selectedItem: Item?
    @Published var draft: String = ""
    @Published var kind: String?
    @Published var isLoading = false
    @Published var isAdding = false
    @Published var errorMessage: String?
    // Non-error notice (e.g. an audio/video upload now transcribing in the background).
    @Published var statusMessage: String?
    @Published private var generatingSummaryAudioItemId: String?
    @Published private var downloadingSummaryAudioItemId: String?
    @Published private var playingSummaryAudioItemId: String?

    let apiClient: APIClient
    private let makeSummaryAudioPlayer: (Data) throws -> any MacSummaryAudioPlaying
    private var summaryAudioPlayer: (any MacSummaryAudioPlaying)?
    private var summaryAudioPlaybackToken = UUID()

    init(
        apiClient: APIClient,
        summaryAudioPlayerFactory: @escaping (Data) throws -> any MacSummaryAudioPlaying = MacSummaryAudioPlayback.makePlayer
    ) {
        self.apiClient = apiClient
        self.makeSummaryAudioPlayer = summaryAudioPlayerFactory
    }

    func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            let response = try await apiClient.listItems(kind: kind)
            entries = response.items
            if let selectedId, !entries.contains(where: { $0.id == selectedId }) {
                self.selectedId = nil
                selectedItem = nil
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func setKind(_ newKind: String?) async {
        kind = newKind
        selectedId = nil
        selectedItem = nil
        await load()
    }

    private static let urlPredicate: (String) -> Bool = { text in
        let lowered = text.lowercased()
        return lowered.hasPrefix("http://") || lowered.hasPrefix("https://")
    }

    func addDraft() async {
        let trimmed = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, !isAdding else { return }
        isAdding = true
        defer { isAdding = false }
        do {
            let created: Item
            if Self.urlPredicate(trimmed) {
                created = try await apiClient.createItem(source: "url", kind: "article", url: trimmed)
            } else {
                created = try await apiClient.createItem(source: "paste", kind: "note", body: trimmed)
            }
            draft = ""
            await load()
            selectedId = created.id
            await selectItem(created.id)
            // Poll in the background so the Add button frees up immediately
            // while the summary + key-moments land (honors the doc comment).
            let createdId = created.id
            Task { [weak self] in await self?.pollUntilProcessed(createdId) }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    /// After a create, poll the new item until its summary lands (or it needs
    /// input / failed) so the "add → instant summary" payoff surfaces without a
    /// manual refresh. Capped at ~60s; bails if the user selects another item.
    private func pollUntilProcessed(_ id: String) async {
        for _ in 0..<30 {
            try? await Task.sleep(nanoseconds: 2_000_000_000)
            guard selectedId == id else { return }
            guard let item = try? await apiClient.getItem(id: id) else { continue }
            selectedItem = item
            if item.summary?.summary != nil
                || item.state == "needs_input"
                || item.state == "failed" {
                await load()
                return
            }
        }
        await load()
    }

    func uploadFile(_ url: URL) async {
        guard !isAdding else { return }
        isAdding = true
        defer { isAdding = false }
        // App Sandbox is off on macOS, but honor the security scope if present
        // (e.g. a file dropped/imported with a scoped URL).
        let scoped = url.startAccessingSecurityScopedResource()
        defer { if scoped { url.stopAccessingSecurityScopedResource() } }
        do {
            let outcome = try await apiClient.uploadItem(fileURL: url)
            switch outcome {
            case .recording(status: _, recordingId: _):
                // Audio/video creates a processing Recording immediately.
                errorMessage = nil
                statusMessage = OnboardingL10n.text(
                    "Transcribing — the recording is now in your Inbox.",
                    "Расшифровываем — запись уже в Инбоксе.",
                    language: LanguageManager.shared.current
                )
            case .item(let created):
                statusMessage = nil
                await load()
                selectedId = created.id
                await selectItem(created.id)
                let createdId = created.id
                Task { [weak self] in await self?.pollUntilProcessed(createdId) }
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func selectItem(_ id: String) async {
        do {
            selectedItem = try await apiClient.getItem(id: id)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func isGeneratingSummaryAudio(for itemId: String) -> Bool {
        generatingSummaryAudioItemId == itemId
    }

    func isDownloadingSummaryAudio(for itemId: String) -> Bool {
        downloadingSummaryAudioItemId == itemId
    }

    func isPlayingSummaryAudio(for itemId: String) -> Bool {
        playingSummaryAudioItemId == itemId
    }

    func startSummaryAudioGeneration(itemId id: String) async {
        guard generatingSummaryAudioItemId == nil else { return }
        generatingSummaryAudioItemId = id
        defer {
            if generatingSummaryAudioItemId == id {
                generatingSummaryAudioItemId = nil
            }
        }

        do {
            let state = try await apiClient.startItemSummaryAudio(itemId: id)
            if selectedItem?.id == id {
                selectedItem = selectedItem?.withSummaryAudio(state)
            }
            await pollSummaryAudioUntilReady(id)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func playOrStopSummaryAudio(itemId id: String) async {
        if playingSummaryAudioItemId == id {
            stopSummaryAudioPlayback(itemId: id)
            return
        }

        downloadingSummaryAudioItemId = id
        defer {
            if downloadingSummaryAudioItemId == id {
                downloadingSummaryAudioItemId = nil
            }
        }

        do {
            let data = try await apiClient.downloadItemSummaryAudio(itemId: id)
            guard selectedItem?.id == id else { return }
            try playSummaryAudioData(data, sourceId: id)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func deleteSelected() async {
        guard let id = selectedId else { return }
        do {
            try await apiClient.deleteItem(id: id)
            selectedId = nil
            selectedItem = nil
            await load()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func pollSummaryAudioUntilReady(_ id: String) async {
        for _ in 0..<30 {
            try? await Task.sleep(nanoseconds: 2_000_000_000)
            guard selectedId == id else { return }
            do {
                let item = try await apiClient.getItem(id: id)
                selectedItem = item
                if item.summaryAudio?.isActive != true {
                    return
                }
            } catch {
                errorMessage = error.localizedDescription
                return
            }
        }
    }

    private func playSummaryAudioData(_ data: Data, sourceId: String) throws {
        let player = try makeSummaryAudioPlayer(data)
        _ = player.prepareToPlay()
        guard player.play() else {
            throw NSError(
                domain: "MacSummaryAudioPlayback",
                code: 1,
                userInfo: [NSLocalizedDescriptionKey: "Could not play summary audio."]
            )
        }

        summaryAudioPlayer?.stop()
        summaryAudioPlayer = player
        playingSummaryAudioItemId = sourceId

        let token = UUID()
        summaryAudioPlaybackToken = token
        let duration = max(player.duration, 0)
        Task { @MainActor [weak self] in
            if duration > 0 {
                try? await Task.sleep(nanoseconds: UInt64((duration + 0.25) * 1_000_000_000))
            } else {
                try? await Task.sleep(for: .seconds(1))
            }
            guard self?.summaryAudioPlaybackToken == token else { return }
            self?.playingSummaryAudioItemId = nil
            self?.summaryAudioPlayer = nil
        }
    }

    private func stopSummaryAudioPlayback(itemId: String) {
        guard playingSummaryAudioItemId == itemId else { return }
        summaryAudioPlaybackToken = UUID()
        summaryAudioPlayer?.stop()
        summaryAudioPlayer = nil
        playingSummaryAudioItemId = nil
    }
}
