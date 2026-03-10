import Foundation

public struct RecordingBackup: Sendable, Equatable {
    public let recordingId: String
    public let directoryURL: URL
    public let manifestURL: URL
    public let segmentsFileURL: URL
}

public struct RecordingBackupManifest: Codable, Sendable, Equatable {
    public let recordingId: String
    public let title: String?
    public let recordingType: String
    public let createdAt: Date
    public let durationSeconds: TimeInterval
    public let segmentCount: Int
    public let transcript: String?
    public var lastErrorMessage: String?
    public var updatedAt: Date
}

public enum RecordingBackupStore {
    private static let encoder: JSONEncoder = {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        encoder.outputFormatting = [.sortedKeys]
        return encoder
    }()

    private static let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return decoder
    }()

    private static let folderName = "PendingTranscripts"

    public static func saveRecording(
        recordingId: String,
        title: String? = nil,
        recordingType: RecordingType,
        durationSeconds: TimeInterval,
        transcript: String? = nil,
        segments: [LiveTranscriptSegment]
    ) throws -> RecordingBackup {
        let backup = try makeBackup(recordingId: recordingId)
        try ensureDirectory(backup.directoryURL)

        let manifest = RecordingBackupManifest(
            recordingId: recordingId,
            title: title,
            recordingType: recordingType.rawValue,
            createdAt: Date(),
            durationSeconds: durationSeconds,
            segmentCount: segments.count,
            transcript: transcript,
            lastErrorMessage: nil,
            updatedAt: Date()
        )
        try writeManifest(manifest, to: backup.manifestURL)

        if segments.isEmpty {
            try? FileManager.default.removeItem(at: backup.segmentsFileURL)
        } else {
            let data = try encoder.encode(segments)
            try data.write(to: backup.segmentsFileURL, options: .atomic)
        }

        return backup
    }

    @discardableResult
    public static func recordSaveFailure(
        recordingId: String,
        message: String
    ) throws -> RecordingBackup? {
        let backup = try existingBackup(recordingId: recordingId)
        guard let backup else { return nil }

        var manifest = try readManifest(from: backup.manifestURL) ?? RecordingBackupManifest(
            recordingId: recordingId,
            title: nil,
            recordingType: RecordingType.note.rawValue,
            createdAt: Date(),
            durationSeconds: 0,
            segmentCount: 0,
            transcript: nil,
            lastErrorMessage: nil,
            updatedAt: Date()
        )
        manifest.lastErrorMessage = message
        manifest.updatedAt = Date()
        try writeManifest(manifest, to: backup.manifestURL)
        return backup
    }

    public static func removeRecording(recordingId: String) throws {
        guard let backup = try existingBackup(recordingId: recordingId) else { return }
        try FileManager.default.removeItem(at: backup.directoryURL)
    }

    public static func existingBackup(recordingId: String) throws -> RecordingBackup? {
        let backup = try makeBackup(recordingId: recordingId)
        guard FileManager.default.fileExists(atPath: backup.directoryURL.path) else {
            return nil
        }
        return backup
    }

    private static func makeBackup(recordingId: String) throws -> RecordingBackup {
        let base = try baseDirectory()
        let directoryURL = base.appendingPathComponent(recordingId, isDirectory: true)
        return RecordingBackup(
            recordingId: recordingId,
            directoryURL: directoryURL,
            manifestURL: directoryURL.appendingPathComponent("manifest.json"),
            segmentsFileURL: directoryURL.appendingPathComponent("segments.json")
        )
    }

    private static func baseDirectory() throws -> URL {
        let base = try FileManager.default.url(
            for: .applicationSupportDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
        )
        return base.appendingPathComponent("WaiComputer", isDirectory: true)
            .appendingPathComponent(folderName, isDirectory: true)
    }

    private static func ensureDirectory(_ url: URL) throws {
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
    }

    private static func writeManifest(_ manifest: RecordingBackupManifest, to url: URL) throws {
        let data = try encoder.encode(manifest)
        try data.write(to: url, options: .atomic)
    }

    private static func readManifest(from url: URL) throws -> RecordingBackupManifest? {
        guard FileManager.default.fileExists(atPath: url.path) else {
            return nil
        }
        let data = try Data(contentsOf: url)
        return try decoder.decode(RecordingBackupManifest.self, from: data)
    }
}
