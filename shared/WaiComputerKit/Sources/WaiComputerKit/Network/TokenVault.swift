import Foundation

/// Pre-fetches and caches short-lived realtime transcription session tokens
/// so push-to-talk does not pay the HTTP round-trip cost on the cold path.
///
/// Strategy:
/// - On app foreground (or after dictation feature enable), backend mints a
///   fresh token via the existing `/transcription/session` endpoint.
/// - Vault stores the token + wall-clock expiry minus a 30 s safety margin.
/// - On hotkey-down, the vault hands out the cached token (if alive) and
///   immediately fires a background re-fetch — so the next press also
///   benefits from a warm cache.
/// - If the cache is stale or empty, the call mints synchronously
///   (~150 ms slow path; should be rare with a working prefetch loop).
///
/// The vault never logs the token itself. Sentry breadcrumbs include only
/// `tokenAgeMs`, `prefetchHit: bool`, and `mintLatencyMs`.
public actor TokenVault {
    public struct Token: Sendable {
        public let value: String
        public let expiresAt: ContinuousClock.Instant
        public let mintedAt: ContinuousClock.Instant
        public let provider: String
        public let model: String
        public let endpoint: URL?
        public let sampleRate: Int

        public func isAlive(forNow now: ContinuousClock.Instant, safety: Duration = .seconds(30)) -> Bool {
            return expiresAt > now + safety
        }

        public init(
            value: String,
            expiresAt: ContinuousClock.Instant,
            mintedAt: ContinuousClock.Instant = ContinuousClock().now,
            provider: String,
            model: String,
            endpoint: URL? = nil,
            sampleRate: Int = 24_000
        ) {
            self.value = value
            self.expiresAt = expiresAt
            self.mintedAt = mintedAt
            self.provider = provider
            self.model = model
            self.endpoint = endpoint
            self.sampleRate = sampleRate
        }
    }

    public typealias Minter = @Sendable () async throws -> Token

    private let minter: Minter
    private var cached: Token?
    private var inFlight: Task<Token, Error>?

    public init(minter: @escaping Minter) {
        self.minter = minter
    }

    /// Returns a token suitable for an immediate WebSocket connect. Triggers a
    /// background re-fetch so the next caller can also hit a warm cache.
    public func token() async throws -> Token {
        let now = ContinuousClock().now
        if let cached, cached.isAlive(forNow: now) {
            // Hand out the cached token and refresh in the background.
            scheduleBackgroundRefresh()
            return cached
        }
        return try await mintFresh()
    }

    /// Fire-and-forget prefetch — call on app foreground / after enabling
    /// the dictation feature so the first PTT press sees a warm cache.
    public func prefetch() {
        scheduleBackgroundRefresh(force: true)
    }

    public func clear() {
        cached = nil
        inFlight?.cancel()
        inFlight = nil
    }

    // MARK: - Private

    private func mintFresh() async throws -> Token {
        if let inFlight {
            return try await inFlight.value
        }
        let task = Task<Token, Error> {
            let token = try await self.minter()
            return token
        }
        inFlight = task
        defer { inFlight = nil }
        let token = try await task.value
        cached = token
        return token
    }

    private func scheduleBackgroundRefresh(force: Bool = false) {
        if !force, let cached, cached.expiresAt - .seconds(60) > ContinuousClock().now {
            // Plenty of headroom — no need to spend a network call yet.
            return
        }
        Task { [weak self] in
            guard let self else { return }
            _ = try? await self.mintFresh()
        }
    }
}
