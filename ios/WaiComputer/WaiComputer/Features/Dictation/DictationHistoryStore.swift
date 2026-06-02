import Foundation
import os
import WaiComputerKit

private let log = Logger(subsystem: "is.waiwai.computer.app", category: "dictation-history")

struct DictationHistoryEntry: Identifiable, Codable {
    let id: UUID
    let timestamp: Date
    let rawText: String
    let cleanedText: String?
    let durationSeconds: Double
    let wordCount: Int

    init(rawText: String, cleanedText: String?, durationSeconds: Double) {
        self.id = UUID()
        self.timestamp = Date()
        self.rawText = rawText
        self.cleanedText = cleanedText
        self.durationSeconds = durationSeconds
        self.wordCount = (cleanedText ?? rawText)
            .split(separator: " ")
            .count
    }

    var displayText: String {
        cleanedText ?? rawText
    }
}

/// Server-synced dictation history. Ported verbatim from macOS (pure
/// Foundation + WaiComputerKit + FileManager). The local cache lives in
/// Application Support and mirrors the server via the shared
/// `listDictationEntries` / `createDictationEntry` / `deleteDictationEntry`
/// endpoints. The view layer is iOS-native; this store is identical.
@MainActor
final class DictationHistoryStore: ObservableObject {
    @Published private(set) var entries: [DictationHistoryEntry] = []

    private let fileURL: URL
    private let tombstonesURL: URL
    private var tombstones: Set<UUID> = []
    private var apiClient: APIClient?

    init() {
        let appSupport = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
        let dir = appSupport.appendingPathComponent("WaiComputer", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        self.fileURL = dir.appendingPathComponent("dictation_history.json")
        self.tombstonesURL = dir.appendingPathComponent("dictation_history_tombstones.json")
        load()
        loadTombstones()
    }

    // MARK: - Sync wiring

    /// Attach the authenticated API client. Once attached, mutations
    /// fan out to the server and `hydrate()` can pull/merge.
    func attach(apiClient: APIClient) {
        self.apiClient = apiClient
    }

    func add(rawText: String, cleanedText: String?, durationSeconds: Double) {
        let entry = DictationHistoryEntry(
            rawText: rawText,
            cleanedText: cleanedText,
            durationSeconds: durationSeconds
        )
        entries.insert(entry, at: 0)
        save()
        log.info("Saved dictation: \(entry.wordCount) words, \(String(format: "%.1f", durationSeconds))s")

        if apiClient != nil {
            Task { await self.pushEntry(entry) }
        }
    }

    func delete(_ entry: DictationHistoryEntry) {
        entries.removeAll { $0.id == entry.id }
        save()

        guard apiClient != nil else { return }
        tombstones.insert(entry.id)
        saveTombstones()
        Task { await self.deleteEntryOnServer(entry.id) }
    }

    /// Wipe the LOCAL cache only — server data is untouched. Called from
    /// the logout flow; on next login `hydrate()` repopulates from server.
    func clearLocalCache() {
        entries.removeAll()
        tombstones.removeAll()
        save()
        saveTombstones()
    }

    /// User-initiated "Clear All History" — wipes BOTH local and server.
    /// Each server delete is best-effort; failures land in tombstones so the
    /// next hydrate retries.
    func deleteAll() async {
        let snapshot = entries
        entries.removeAll()
        save()

        for entry in snapshot {
            if apiClient != nil {
                tombstones.insert(entry.id)
            }
        }
        saveTombstones()

        for entry in snapshot {
            await deleteEntryOnServer(entry.id)
        }
    }

    /// Pull the server's view, merge with local, then push any local-only
    /// entries up and retry any tombstoned deletes. Safe to call repeatedly.
    func hydrate() async {
        guard let apiClient else { return }

        let serverEntries: [DictationEntryDTO]
        do {
            serverEntries = try await apiClient.listDictationEntries()
        } catch {
            log.error("Hydrate fetch failed: \(error.localizedDescription)")
            return
        }

        // Step 2 — replay tombstoned deletes against server. Drop the
        // tombstone only after the server confirms.
        for serverEntry in serverEntries where tombstones.contains(serverEntry.clientEntryID) {
            do {
                try await apiClient.deleteDictationEntry(clientEntryID: serverEntry.clientEntryID)
                tombstones.remove(serverEntry.clientEntryID)
            } catch {
                log.error("Hydrate tombstone replay failed: \(error.localizedDescription)")
            }
        }
        saveTombstones()

        // Step 3 — server entries we don't have locally (and are not tombstoned).
        let localIDs = Set(entries.map(\.id))
        let serverByID = Dictionary(uniqueKeysWithValues: serverEntries.map { ($0.clientEntryID, $0) })
        var newLocal: [DictationHistoryEntry] = []
        for (id, dto) in serverByID where !localIDs.contains(id) && !tombstones.contains(id) {
            newLocal.append(Self.makeLocalEntry(from: dto))
        }
        if !newLocal.isEmpty {
            entries.append(contentsOf: newLocal)
            entries.sort { $0.timestamp > $1.timestamp }
            save()
        }

        // Step 4 — push local entries the server doesn't yet have.
        let serverIDs = Set(serverByID.keys)
        for entry in entries where !serverIDs.contains(entry.id) {
            await pushEntry(entry)
        }
    }

    // MARK: - Stats

    var totalWords: Int {
        entries.reduce(0) { $0 + $1.wordCount }
    }

    var averageWPM: Int {
        let totalDuration = entries.reduce(0.0) { $0 + $1.durationSeconds }
        guard totalDuration > 0 else { return 0 }
        return Int(Double(totalWords) / (totalDuration / 60.0))
    }

    var streakDays: Int {
        guard !entries.isEmpty else { return 0 }
        let calendar = Calendar.current
        var streak = 1
        var currentDate = calendar.startOfDay(for: Date())

        let dictatedToday = entries.contains { calendar.isDate($0.timestamp, inSameDayAs: currentDate) }
        if !dictatedToday {
            currentDate = calendar.date(byAdding: .day, value: -1, to: currentDate)!
            let dictatedYesterday = entries.contains { calendar.isDate($0.timestamp, inSameDayAs: currentDate) }
            if !dictatedYesterday { return 0 }
        }

        while true {
            let previousDay = calendar.date(byAdding: .day, value: -1, to: currentDate)!
            let dictatedOnDay = entries.contains { calendar.isDate($0.timestamp, inSameDayAs: previousDay) }
            if dictatedOnDay {
                streak += 1
                currentDate = previousDay
            } else {
                break
            }
        }
        return streak
    }

    // MARK: - Sync helpers

    private static let iso8601: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()

    private func pushEntry(_ entry: DictationHistoryEntry) async {
        guard let apiClient else { return }
        let request = CreateDictationEntryRequest(
            clientEntryID: entry.id,
            rawText: entry.rawText,
            cleanedText: entry.cleanedText,
            durationSeconds: entry.durationSeconds,
            wordCount: entry.wordCount,
            occurredAt: Self.iso8601.string(from: entry.timestamp)
        )
        do {
            _ = try await apiClient.createDictationEntry(request)
        } catch {
            log.error("Push entry failed (will retry on next hydrate): \(error.localizedDescription)")
        }
    }

    private func deleteEntryOnServer(_ id: UUID) async {
        guard let apiClient else { return }
        do {
            try await apiClient.deleteDictationEntry(clientEntryID: id)
            tombstones.remove(id)
            saveTombstones()
        } catch {
            log.error("Delete on server failed (tombstone remains): \(error.localizedDescription)")
        }
    }

    private static func makeLocalEntry(from dto: DictationEntryDTO) -> DictationHistoryEntry {
        DictationHistoryEntry(
            id: dto.clientEntryID,
            timestamp: dto.occurredAt,
            rawText: dto.rawText,
            cleanedText: dto.cleanedText,
            durationSeconds: dto.durationSeconds,
            wordCount: dto.wordCount
        )
    }

    // MARK: - Persistence

    private func load() {
        guard FileManager.default.fileExists(atPath: fileURL.path) else { return }
        do {
            let data = try Data(contentsOf: fileURL)
            entries = try JSONDecoder().decode([DictationHistoryEntry].self, from: data)
            log.info("Loaded \(self.entries.count) history entries")
        } catch {
            log.error("Failed to load history: \(error.localizedDescription)")
        }
    }

    private func save() {
        do {
            try FileManager.default.createDirectory(
                at: fileURL.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            let data = try JSONEncoder().encode(entries)
            try data.write(to: fileURL, options: .atomic)
        } catch {
            log.error("Failed to save history: \(error.localizedDescription)")
        }
    }

    private func loadTombstones() {
        guard FileManager.default.fileExists(atPath: tombstonesURL.path) else { return }
        do {
            let data = try Data(contentsOf: tombstonesURL)
            tombstones = Set(try JSONDecoder().decode([UUID].self, from: data))
        } catch {
            log.error("Failed to load tombstones: \(error.localizedDescription)")
        }
    }

    private func saveTombstones() {
        do {
            try FileManager.default.createDirectory(
                at: tombstonesURL.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            let data = try JSONEncoder().encode(Array(tombstones))
            try data.write(to: tombstonesURL, options: .atomic)
        } catch {
            log.error("Failed to save tombstones: \(error.localizedDescription)")
        }
    }
}

// Internal initializer used by hydrate() to mint a local entry from server DTO.
extension DictationHistoryEntry {
    init(
        id: UUID,
        timestamp: Date,
        rawText: String,
        cleanedText: String?,
        durationSeconds: Double,
        wordCount: Int
    ) {
        self.id = id
        self.timestamp = timestamp
        self.rawText = rawText
        self.cleanedText = cleanedText
        self.durationSeconds = durationSeconds
        self.wordCount = wordCount
    }
}
