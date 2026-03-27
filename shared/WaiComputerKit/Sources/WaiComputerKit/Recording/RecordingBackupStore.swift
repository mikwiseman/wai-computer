import Foundation
import Sentry

public struct RecordingBackup: Sendable, Equatable {
    public let recordingId: String
    public let directoryURL: URL
    public let manifestURL: URL
    public let segmentsFileURL: URL
    public let audioFileURL: URL
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
    public var hasAudioFile: Bool

    private enum CodingKeys: String, CodingKey {
        case recordingId, title, recordingType, createdAt, durationSeconds
        case segmentCount, transcript, lastErrorMessage, updatedAt, hasAudioFile
    }

    public init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        recordingId = try container.decode(String.self, forKey: .recordingId)
        title = try container.decodeIfPresent(String.self, forKey: .title)
        recordingType = try container.decode(String.self, forKey: .recordingType)
        createdAt = try container.decode(Date.self, forKey: .createdAt)
        durationSeconds = try container.decode(TimeInterval.self, forKey: .durationSeconds)
        segmentCount = try container.decode(Int.self, forKey: .segmentCount)
        transcript = try container.decodeIfPresent(String.self, forKey: .transcript)
        lastErrorMessage = try container.decodeIfPresent(String.self, forKey: .lastErrorMessage)
        updatedAt = try container.decode(Date.self, forKey: .updatedAt)
        hasAudioFile = try container.decodeIfPresent(Bool.self, forKey: .hasAudioFile) ?? false
    }

    public init(
        recordingId: String,
        title: String?,
        recordingType: String,
        createdAt: Date,
        durationSeconds: TimeInterval,
        segmentCount: Int,
        transcript: String?,
        lastErrorMessage: String?,
        updatedAt: Date,
        hasAudioFile: Bool = false
    ) {
        self.recordingId = recordingId
        self.title = title
        self.recordingType = recordingType
        self.createdAt = createdAt
        self.durationSeconds = durationSeconds
        self.segmentCount = segmentCount
        self.transcript = transcript
        self.lastErrorMessage = lastErrorMessage
        self.updatedAt = updatedAt
        self.hasAudioFile = hasAudioFile
    }
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

        SentryHelper.addBreadcrumb(
            category: "backup",
            message: "recording backup saved",
            data: ["recordingId": recordingId, "segments": segments.count]
        )

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

    /// Returns the expected audio file URL for a recording, without checking existence.
    public static func audioFileURL(recordingId: String) throws -> URL {
        let backup = try makeBackup(recordingId: recordingId)
        return backup.audioFileURL
    }

    /// Ensures the backup directory exists for a recording. Call before creating AudioFileWriter.
    public static func ensureDirectoryForRecording(recordingId: String) throws {
        let backup = try makeBackup(recordingId: recordingId)
        try ensureDirectory(backup.directoryURL)
    }

    /// Marks a recording backup as having an audio file.
    public static func markHasAudioFile(recordingId: String) throws {
        let backup = try makeBackup(recordingId: recordingId)
        try ensureDirectory(backup.directoryURL)

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
        manifest.hasAudioFile = true
        manifest.updatedAt = Date()
        try writeManifest(manifest, to: backup.manifestURL)
    }

    private static func makeBackup(recordingId: String) throws -> RecordingBackup {
        let base = try baseDirectory()
        let directoryURL = base.appendingPathComponent(recordingId, isDirectory: true)
        return RecordingBackup(
            recordingId: recordingId,
            directoryURL: directoryURL,
            manifestURL: directoryURL.appendingPathComponent("manifest.json"),
            segmentsFileURL: directoryURL.appendingPathComponent("segments.json"),
            audioFileURL: directoryURL.appendingPathComponent("recording.wav")
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
