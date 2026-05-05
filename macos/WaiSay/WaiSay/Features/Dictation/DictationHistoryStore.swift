import Foundation
import os

private let log = Logger(subsystem: "com.waisay.app", category: "dictation-history")

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

@MainActor
final class DictationHistoryStore: ObservableObject {
    @Published private(set) var entries: [DictationHistoryEntry] = []

    private let fileURL: URL

    init() {
        let appSupport = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
        let dir = appSupport.appendingPathComponent("WaiSay", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        self.fileURL = dir.appendingPathComponent("dictation_history.json")
        load()
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
    }

    func delete(_ entry: DictationHistoryEntry) {
        entries.removeAll { $0.id == entry.id }
        save()
    }

    func clearAll() {
        entries.removeAll()
        save()
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

        // Check if dictated today
        let dictatedToday = entries.contains { calendar.isDate($0.timestamp, inSameDayAs: currentDate) }
        if !dictatedToday {
            // Check yesterday — streak continues from yesterday
            currentDate = calendar.date(byAdding: .day, value: -1, to: currentDate)!
            let dictatedYesterday = entries.contains { calendar.isDate($0.timestamp, inSameDayAs: currentDate) }
            if !dictatedYesterday { return 0 }
        }

        // Count consecutive days backward
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
}
