import Foundation

/// Caches a single short-lived realtime transcription session config.
///
/// The cached value contains provider endpoint metadata and a temporary
/// credential, but it does not open the microphone or establish a provider
/// WebSocket. Values are consumed on use because some upstream providers treat
/// realtime credentials as single-session credentials.
public actor RealtimeTranscriptionSessionConfigVault {
    public struct Key: Hashable, Sendable {
        public let language: String
        public let channels: Int
        public let purpose: RealtimeTranscriptionPurpose

        public init(language: String, channels: Int, purpose: RealtimeTranscriptionPurpose) {
            self.language = language
            self.channels = channels
            self.purpose = purpose
        }
    }

    public struct TakeResult: Sendable {
        public let config: RealtimeTranscriptionSessionConfig
        public let prefetched: Bool
        public let tokenAgeMilliseconds: Int

        public init(
            config: RealtimeTranscriptionSessionConfig,
            prefetched: Bool,
            tokenAgeMilliseconds: Int
        ) {
            self.config = config
            self.prefetched = prefetched
            self.tokenAgeMilliseconds = tokenAgeMilliseconds
        }
    }

    public typealias Minter = @Sendable (Key) async throws -> RealtimeTranscriptionSessionConfig

    private struct Entry: Sendable {
        let key: Key
        let config: RealtimeTranscriptionSessionConfig
        let mintedAt: ContinuousClock.Instant
    }

    private let minter: Minter
    private var cached: Entry?
    private var inFlightKey: Key?
    private var inFlight: Task<Entry, Error>?

    public init(minter: @escaping Minter) {
        self.minter = minter
    }

    public func prefetch(for key: Key) {
        let now = ContinuousClock().now
        if let cached, cached.key == key, isAlive(cached, now: now) {
            return
        }
        if inFlightKey == key, inFlight != nil {
            return
        }
        Task { [weak self] in
            guard let self else { return }
            _ = try? await self.mintAndCache(for: key)
        }
    }

    public func take(
        for key: Key,
        expectedProvider: String? = nil,
        expectedModel: String? = nil
    ) async throws -> TakeResult {
        let now = ContinuousClock().now
        if let cached,
           cached.key == key,
           isAlive(cached, now: now),
           matches(cached.config, expectedProvider: expectedProvider, expectedModel: expectedModel) {
            self.cached = nil
            return TakeResult(
                config: cached.config,
                prefetched: true,
                tokenAgeMilliseconds: milliseconds(from: cached.mintedAt.duration(to: now))
            )
        }

        if cached != nil {
            cached = nil
        }

        let entry = try await mintFresh(for: key)
        if matches(entry.config, expectedProvider: expectedProvider, expectedModel: expectedModel) {
            return TakeResult(config: entry.config, prefetched: false, tokenAgeMilliseconds: 0)
        }

        throw RealtimeTranscriptionSessionConfigVaultError.unexpectedProvider(
            expectedProvider: expectedProvider,
            expectedModel: expectedModel,
            actualProvider: entry.config.provider,
            actualModel: entry.config.model
        )
    }

    public func clear() {
        cached = nil
        inFlight?.cancel()
        inFlight = nil
        inFlightKey = nil
    }

    private func mintAndCache(for key: Key) async throws -> Entry {
        let entry = try await mintFresh(for: key)
        cached = entry
        return entry
    }

    private func mintFresh(for key: Key) async throws -> Entry {
        if let inFlight, inFlightKey == key {
            return try await inFlight.value
        }

        let task = Task<Entry, Error> {
            let config = try await self.minter(key)
            return Entry(key: key, config: config, mintedAt: ContinuousClock().now)
        }
        inFlight = task
        inFlightKey = key
        defer {
            inFlight = nil
            inFlightKey = nil
        }
        return try await task.value
    }

    private func isAlive(_ entry: Entry, now: ContinuousClock.Instant) -> Bool {
        let lifetime = max(entry.config.expiresInSeconds, 0)
        guard lifetime > 0 else { return false }
        let safety = min(30, max(3, lifetime / 4))
        return entry.mintedAt.advanced(by: .seconds(lifetime - safety)) > now
    }

    private func matches(
        _ config: RealtimeTranscriptionSessionConfig,
        expectedProvider: String?,
        expectedModel: String?
    ) -> Bool {
        if let expectedProvider, config.provider != expectedProvider {
            return false
        }
        if let expectedModel, config.model != expectedModel {
            return false
        }
        return true
    }

    private func milliseconds(from duration: Duration) -> Int {
        let components = duration.components
        let secondsMs = components.seconds * 1_000
        let attosecondsMs = components.attoseconds / 1_000_000_000_000_000
        return Int(secondsMs + attosecondsMs)
    }
}

public enum RealtimeTranscriptionSessionConfigVaultError: Error, Equatable, Sendable {
    case unexpectedProvider(
        expectedProvider: String?,
        expectedModel: String?,
        actualProvider: String,
        actualModel: String
    )
}
