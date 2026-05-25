import Foundation
import os
import Sentry

public struct RecordingBackup: Sendable, Equatable {
    public let recordingId: String
    public let directoryURL: URL
    public let manifestURL: URL
    public let segmentsFileURL: URL
    public let audioFileURL: URL
}

public enum RecordingBackupSyncState: String, Codable, Sendable, Equatable {
    case localRecording
    case localReady
    case uploading
    case serverProcessing
    case remoteReady
    case retryableFailure
    case permanentFailure
    case authenticationRequired

    public var isReadyForSync: Bool {
        switch self {
        case .localRecording, .remoteReady, .permanentFailure, .authenticationRequired:
            return false
        case .localReady, .uploading, .serverProcessing, .retryableFailure:
            return true
        }
    }
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
    public var syncState: RecordingBackupSyncState
    public var serverJobId: String?
    public var lastSyncAttemptAt: Date?
    public var syncAttemptCount: Int
    public var lastFailureCode: String?

    public var isPermanentFailure: Bool { syncState == .permanentFailure }
    public var requiresAuthentication: Bool { syncState == .authenticationRequired }
    public var isReadyForSync: Bool { syncState.isReadyForSync }
    public var isServerProcessing: Bool { syncState == .serverProcessing }

    private enum CodingKeys: String, CodingKey {
        case recordingId, title, recordingType, createdAt, durationSeconds
        case segmentCount, transcript, lastErrorMessage, updatedAt, hasAudioFile
        case syncState, serverJobId, lastSyncAttemptAt, syncAttemptCount, lastFailureCode
        case isPermanentFailure, requiresAuthentication, isReadyForSync, isServerProcessing
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
        serverJobId = try container.decodeIfPresent(String.self, forKey: .serverJobId)
        lastSyncAttemptAt = try container.decodeIfPresent(Date.self, forKey: .lastSyncAttemptAt)
        syncAttemptCount = try container.decodeIfPresent(Int.self, forKey: .syncAttemptCount) ?? 0
        lastFailureCode = try container.decodeIfPresent(String.self, forKey: .lastFailureCode)

        if let storedState = try container.decodeIfPresent(RecordingBackupSyncState.self, forKey: .syncState) {
            syncState = storedState
        } else {
            let isPermanentFailure = try container.decodeIfPresent(Bool.self, forKey: .isPermanentFailure) ?? false
            let requiresAuthentication = try container.decodeIfPresent(Bool.self, forKey: .requiresAuthentication) ?? false
            let isServerProcessing = try container.decodeIfPresent(Bool.self, forKey: .isServerProcessing) ?? false
            let isReadyForSync = try container.decodeIfPresent(Bool.self, forKey: .isReadyForSync) ?? true
            if isPermanentFailure {
                syncState = .permanentFailure
            } else if requiresAuthentication {
                syncState = .authenticationRequired
            } else if isServerProcessing {
                syncState = .serverProcessing
            } else if !isReadyForSync {
                syncState = .localRecording
            } else {
                syncState = .localReady
            }
        }
    }

    public func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(recordingId, forKey: .recordingId)
        try container.encodeIfPresent(title, forKey: .title)
        try container.encode(recordingType, forKey: .recordingType)
        try container.encode(createdAt, forKey: .createdAt)
        try container.encode(durationSeconds, forKey: .durationSeconds)
        try container.encode(segmentCount, forKey: .segmentCount)
        try container.encodeIfPresent(transcript, forKey: .transcript)
        try container.encodeIfPresent(lastErrorMessage, forKey: .lastErrorMessage)
        try container.encode(updatedAt, forKey: .updatedAt)
        try container.encode(hasAudioFile, forKey: .hasAudioFile)
        try container.encode(syncState, forKey: .syncState)
        try container.encodeIfPresent(serverJobId, forKey: .serverJobId)
        try container.encodeIfPresent(lastSyncAttemptAt, forKey: .lastSyncAttemptAt)
        try container.encode(syncAttemptCount, forKey: .syncAttemptCount)
        try container.encodeIfPresent(lastFailureCode, forKey: .lastFailureCode)
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
        hasAudioFile: Bool = false,
        syncState: RecordingBackupSyncState? = nil,
        serverJobId: String? = nil,
        lastSyncAttemptAt: Date? = nil,
        syncAttemptCount: Int = 0,
        lastFailureCode: String? = nil,
        isPermanentFailure: Bool = false,
        requiresAuthentication: Bool = false,
        isReadyForSync: Bool = true,
        isServerProcessing: Bool = false
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
        if let syncState {
            self.syncState = syncState
        } else if isPermanentFailure {
            self.syncState = .permanentFailure
        } else if requiresAuthentication {
            self.syncState = .authenticationRequired
        } else if isServerProcessing {
            self.syncState = .serverProcessing
        } else if !isReadyForSync {
            self.syncState = .localRecording
        } else {
            self.syncState = .localReady
        }
        self.serverJobId = serverJobId
        self.lastSyncAttemptAt = lastSyncAttemptAt
        self.syncAttemptCount = syncAttemptCount
        self.lastFailureCode = lastFailureCode
    }
}

public enum RecordingBackupStore {
    static var overrideBaseDirectory: URL?
    private static let log = Logger(subsystem: "is.waiwai.computer", category: "backup")

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

        let existingManifest = try readManifest(from: backup.manifestURL)
        let manifest = RecordingBackupManifest(
            recordingId: recordingId,
            title: title,
            recordingType: recordingType.rawValue,
            createdAt: existingManifest?.createdAt ?? Date(),
            durationSeconds: durationSeconds,
            segmentCount: segments.count,
            transcript: transcript,
            lastErrorMessage: nil,
            updatedAt: Date(),
            hasAudioFile: existingManifest?.hasAudioFile ?? false,
            syncState: existingManifest?.syncState == .serverProcessing ? .serverProcessing : .localReady,
            serverJobId: existingManifest?.serverJobId,
            lastSyncAttemptAt: existingManifest?.lastSyncAttemptAt,
            syncAttemptCount: existingManifest?.syncAttemptCount ?? 0,
            lastFailureCode: existingManifest?.lastFailureCode
        )
        try writeManifest(manifest, to: backup.manifestURL)

        if segments.isEmpty {
            try? FileManager.default.removeItem(at: backup.segmentsFileURL)
        } else {
            let data = try encoder.encode(segments)
            try data.write(to: backup.segmentsFileURL, options: .atomic)
        }

        log.info("Backup saved: \(recordingId) (\(segments.count) segments)")
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
        if manifest.syncState != .serverProcessing {
            manifest.syncState = .retryableFailure
        }
        manifest.updatedAt = Date()
        try writeManifest(manifest, to: backup.manifestURL)
        log.warning("Recorded save failure for \(recordingId)")
        return backup
    }

    public static func markPermanentFailure(recordingId: String) throws {
        guard let backup = try existingBackup(recordingId: recordingId) else { return }
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
        manifest.syncState = .permanentFailure
        manifest.serverJobId = nil
        manifest.lastFailureCode = "permanent_failure"
        manifest.updatedAt = Date()
        try writeManifest(manifest, to: backup.manifestURL)
        log.error("Marked permanent failure for \(recordingId)")
    }

    public static func markAuthenticationRequired(recordingId: String) throws {
        guard let backup = try existingBackup(recordingId: recordingId) else { return }
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
        manifest.syncState = .authenticationRequired
        manifest.serverJobId = nil
        manifest.lastFailureCode = "authentication_required"
        manifest.updatedAt = Date()
        try writeManifest(manifest, to: backup.manifestURL)
        log.error("Marked authentication required for \(recordingId)")
    }

    public static func markServerProcessing(recordingId: String, serverJobId: String? = nil) throws {
        guard let backup = try existingBackup(recordingId: recordingId) else { return }
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
        manifest.syncState = .serverProcessing
        manifest.serverJobId = serverJobId ?? manifest.serverJobId
        manifest.lastFailureCode = nil
        manifest.updatedAt = Date()
        try writeManifest(manifest, to: backup.manifestURL)
        log.info("Marked server processing for \(recordingId)")
    }

    public static func clearServerProcessing(recordingId: String) throws {
        guard let backup = try existingBackup(recordingId: recordingId) else { return }
        guard var manifest = try readManifest(from: backup.manifestURL) else { return }
        guard manifest.isServerProcessing else { return }

        manifest.syncState = .localReady
        manifest.serverJobId = nil
        manifest.updatedAt = Date()
        try writeManifest(manifest, to: backup.manifestURL)
        log.info("Cleared server processing for \(recordingId)")
    }

    public static func clearAuthenticationRequired(recordingId: String) throws {
        guard let backup = try existingBackup(recordingId: recordingId) else { return }
        guard var manifest = try readManifest(from: backup.manifestURL) else { return }
        guard manifest.requiresAuthentication else { return }

        manifest.syncState = .localReady
        manifest.lastFailureCode = nil
        manifest.updatedAt = Date()
        try writeManifest(manifest, to: backup.manifestURL)
        log.info("Cleared authentication required for \(recordingId)")
    }

    public static func removeRecording(recordingId: String) throws {
        guard let backup = try existingBackup(recordingId: recordingId) else { return }
        try FileManager.default.removeItem(at: backup.directoryURL)
        log.info("Removed backup for \(recordingId)")
    }

    public static func removeAllRecordings() throws {
        let base = try baseDirectory()
        guard FileManager.default.fileExists(atPath: base.path) else {
            return
        }
        try FileManager.default.removeItem(at: base)
        log.info("Removed all pending recording backups")
    }

    public static func existingBackup(recordingId: String) throws -> RecordingBackup? {
        let backup = try makeBackup(recordingId: recordingId)
        guard FileManager.default.fileExists(atPath: backup.directoryURL.path) else {
            return nil
        }
        return backup
    }

    public static func listBackups() throws -> [RecordingBackup] {
        let base = try baseDirectory()
        guard FileManager.default.fileExists(atPath: base.path) else {
            return []
        }

        return try FileManager.default.contentsOfDirectory(
            at: base,
            includingPropertiesForKeys: [.isDirectoryKey, .contentModificationDateKey],
            options: [.skipsHiddenFiles]
        )
        .filter { url in
            (try? url.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true
        }
        .compactMap { url in
            let recordingId = url.lastPathComponent
            return try? existingBackup(recordingId: recordingId)
        }
        .sorted { lhs, rhs in
            let lhsDate = (try? readManifest(from: lhs.manifestURL)?.updatedAt) ?? .distantPast
            let rhsDate = (try? readManifest(from: rhs.manifestURL)?.updatedAt) ?? .distantPast
            return lhsDate > rhsDate
        }
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
        manifest.syncState = .localRecording
        manifest.serverJobId = nil
        manifest.lastFailureCode = nil
        manifest.updatedAt = Date()
        try writeManifest(manifest, to: backup.manifestURL)
    }

    public static func recordSyncAttempt(recordingId: String) throws {
        guard let backup = try existingBackup(recordingId: recordingId) else { return }
        guard var manifest = try readManifest(from: backup.manifestURL) else { return }
        manifest.lastSyncAttemptAt = Date()
        manifest.syncAttemptCount += 1
        manifest.updatedAt = Date()
        try writeManifest(manifest, to: backup.manifestURL)
    }

    public static func markRetryableFailure(
        recordingId: String,
        message: String,
        failureCode: String? = nil
    ) throws {
        guard let backup = try recordSaveFailure(recordingId: recordingId, message: message) else { return }
        guard var manifest = try readManifest(from: backup.manifestURL) else { return }
        manifest.syncState = .retryableFailure
        manifest.serverJobId = nil
        manifest.lastFailureCode = failureCode
        manifest.updatedAt = Date()
        try writeManifest(manifest, to: backup.manifestURL)
    }

    public static func manifest(recordingId: String) throws -> RecordingBackupManifest? {
        let backup = try makeBackup(recordingId: recordingId)
        return try readManifest(from: backup.manifestURL)
    }

    public static func manifestsByRecordingId() throws -> [String: RecordingBackupManifest] {
        var manifests: [String: RecordingBackupManifest] = [:]

        for backup in try listBackups() {
            if let manifest = try readManifest(from: backup.manifestURL) {
                manifests[backup.recordingId] = manifest
            }
        }

        return manifests
    }

    public static func segments(recordingId: String) throws -> [LiveTranscriptSegment] {
        let backup = try makeBackup(recordingId: recordingId)
        guard FileManager.default.fileExists(atPath: backup.segmentsFileURL.path) else {
            return []
        }
        let data = try Data(contentsOf: backup.segmentsFileURL)
        return try decoder.decode([LiveTranscriptSegment].self, from: data)
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
        if let overrideBaseDirectory {
            return overrideBaseDirectory
        }
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
