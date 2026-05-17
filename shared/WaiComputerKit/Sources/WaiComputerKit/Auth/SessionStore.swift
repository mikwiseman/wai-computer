import Foundation
import os

private let log = Logger(subsystem: "is.waiwai.computer.auth", category: "session-store")

/// File-based persistence for the user's auth session.
///
/// macOS Keychain ACLs invalidate when an app's cdhash drifts (every Sparkle
/// update, every re-sign), forcing the user to re-login on every release. The
/// industry workaround that ships in Wispr Flow, TokenEater, Claude Code, and
/// other 2026 macOS apps is to persist OAuth tokens in a JSON file under
/// Application Support and rely on filesystem permissions + FileVault for
/// at-rest protection.
///
/// `SessionStore` writes to `<Application Support>/WaiComputer/session.json` with
/// 0600 file mode. On first launch from a build that previously used Keychain,
/// it migrates any existing tokens out of Keychain into the file, so users
/// stay signed in across the cutover.
public final class SessionStore: @unchecked Sendable {
    public static let shared = SessionStore()

    public struct Session: Codable, Equatable {
        public var accessToken: String
        public var refreshToken: String?
        public var savedAt: Date

        public init(accessToken: String, refreshToken: String? = nil, savedAt: Date = Date()) {
            self.accessToken = accessToken
            self.refreshToken = refreshToken
            self.savedAt = savedAt
        }
    }

    public enum StorageError: Error {
        case directoryCreationFailed(URL)
        case writeFailed(Error)
    }

    private let queue = DispatchQueue(label: "is.waiwai.computer.auth.sessionstore")
    private let fileManager: FileManager
    private let directoryName: String

    private init() {
        self.fileManager = .default
        self.directoryName = "WaiComputer"
    }

    /// Create a SessionStore with custom paths (used by tests).
    public init(fileManager: FileManager, directoryName: String) {
        self.fileManager = fileManager
        self.directoryName = directoryName
    }

    // MARK: - Public API

    /// Returns the persisted session, migrating from Keychain on first read if
    /// no file exists yet. Returns nil only when no token has ever been saved.
    public func load() -> Session? {
        queue.sync { loadLocked() }
    }

    public func save(accessToken: String, refreshToken: String?) throws {
        try queue.sync {
            try saveLocked(Session(
                accessToken: accessToken,
                refreshToken: refreshToken,
                savedAt: Date()
            ))
        }
    }

    public func clear() {
        queue.sync {
            let url = sessionFileURL
            if fileManager.fileExists(atPath: url.path) {
                try? fileManager.removeItem(at: url)
            }
            // Also clear any leftover Keychain entries from before the migration.
            KeychainHelper.delete(key: KeychainHelper.accessTokenKey)
            KeychainHelper.delete(key: KeychainHelper.refreshTokenKey)
        }
    }

    public var sessionFileURL: URL {
        let supportDir: URL
        if let candidate = try? fileManager.url(
            for: .applicationSupportDirectory,
            in: .userDomainMask,
            appropriateFor: nil,
            create: true
        ) {
            supportDir = candidate
        } else {
            supportDir = URL(fileURLWithPath: NSHomeDirectory())
                .appendingPathComponent("Library", isDirectory: true)
                .appendingPathComponent("Application Support", isDirectory: true)
        }
        let appDir = supportDir.appendingPathComponent(directoryName, isDirectory: true)
        return appDir.appendingPathComponent("session.json")
    }

    // MARK: - Private

    private func loadLocked() -> Session? {
        let url = sessionFileURL
        if let session = readSession(from: url) {
            return session
        }

        // No file — try Keychain migration once.
        guard let migrated = migrateFromKeychain() else { return nil }
        do {
            try saveLocked(migrated)
        } catch {
            log.warning("Keychain → file migration: save failed (\(String(describing: error), privacy: .public))")
        }
        return migrated
    }

    private func saveLocked(_ session: Session) throws {
        let url = sessionFileURL
        let dir = url.deletingLastPathComponent()
        do {
            try fileManager.createDirectory(at: dir, withIntermediateDirectories: true, attributes: nil)
        } catch {
            log.error("Could not create session directory: \(error.localizedDescription, privacy: .public)")
            throw StorageError.directoryCreationFailed(dir)
        }

        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        encoder.dateEncodingStrategy = .iso8601
        let data: Data
        do {
            data = try encoder.encode(session)
        } catch {
            log.error("Session encode failed: \(error.localizedDescription, privacy: .public)")
            throw StorageError.writeFailed(error)
        }

        do {
            try data.write(to: url, options: [.atomic])
            try? fileManager.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
        } catch {
            log.error("Session write failed: \(error.localizedDescription, privacy: .public)")
            throw StorageError.writeFailed(error)
        }
    }

    private func readSession(from url: URL) -> Session? {
        guard fileManager.fileExists(atPath: url.path),
              let data = try? Data(contentsOf: url) else {
            return nil
        }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return try? decoder.decode(Session.self, from: data)
    }

    private func migrateFromKeychain() -> Session? {
        guard let access = KeychainHelper.load(key: KeychainHelper.accessTokenKey), !access.isEmpty else {
            return nil
        }
        let refresh = KeychainHelper.load(key: KeychainHelper.refreshTokenKey)
        log.info("Migrating session from Keychain → file")
        return Session(accessToken: access, refreshToken: refresh, savedAt: Date())
    }
}
