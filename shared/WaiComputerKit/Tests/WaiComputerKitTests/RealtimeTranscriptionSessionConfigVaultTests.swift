import XCTest
@testable import WaiComputerKit

final class RealtimeTranscriptionSessionConfigVaultTests: XCTestCase {
    private let key = RealtimeTranscriptionSessionConfigVault.Key(
        language: "multi",
        channels: 1,
        purpose: .dictation
    )

    func testTakeMintsFreshWhenCacheIsEmpty() async throws {
        let mintCount = SessionConfigMintCounter()
        let vault = RealtimeTranscriptionSessionConfigVault { key in
            await mintCount.increment()
            return Self.config(token: "fresh", language: key.language)
        }

        let result = try await vault.take(
            for: key,
            expectedProvider: "deepgram",
            expectedModel: "nova-3"
        )

        XCTAssertEqual(result.config.token, "fresh")
        XCTAssertFalse(result.prefetched)
        let count = await mintCount.count()
        XCTAssertEqual(count, 1)
    }

    func testPrefetchPopulatesCacheAndTakeConsumesItOnce() async throws {
        let mintCount = SessionConfigMintCounter()
        let vault = RealtimeTranscriptionSessionConfigVault { _ in
            await mintCount.increment()
            let count = await mintCount.count()
            return Self.config(token: "token-\(count)")
        }

        await vault.prefetch(for: key)
        try await Task.sleep(for: .milliseconds(100))

        let prefetched = try await vault.take(
            for: key,
            expectedProvider: "deepgram",
            expectedModel: "nova-3"
        )
        let fresh = try await vault.take(
            for: key,
            expectedProvider: "deepgram",
            expectedModel: "nova-3"
        )

        XCTAssertTrue(prefetched.prefetched)
        XCTAssertEqual(prefetched.config.token, "token-1")
        XCTAssertFalse(fresh.prefetched)
        XCTAssertEqual(fresh.config.token, "token-2")
    }

    func testTakeDuringInFlightPrefetchConsumesWithoutLeavingTokenCached() async throws {
        let mintCount = SessionConfigMintCounter()
        let vault = RealtimeTranscriptionSessionConfigVault { _ in
            await mintCount.increment()
            let count = await mintCount.count()
            try await Task.sleep(for: .milliseconds(120))
            return Self.config(token: "token-\(count)")
        }

        await vault.prefetch(for: key)
        try await waitUntil { await mintCount.count() == 1 }

        let first = try await vault.take(
            for: key,
            expectedProvider: "deepgram",
            expectedModel: "nova-3"
        )
        let second = try await vault.take(
            for: key,
            expectedProvider: "deepgram",
            expectedModel: "nova-3"
        )

        XCTAssertTrue(first.prefetched)
        XCTAssertEqual(first.config.token, "token-1")
        XCTAssertFalse(second.prefetched)
        XCTAssertEqual(second.config.token, "token-2")
        let count = await mintCount.count()
        XCTAssertEqual(count, 2)
    }

    func testConcurrentTakesDuringInFlightPrefetchDoNotShareToken() async throws {
        let mintCount = SessionConfigMintCounter()
        let vault = RealtimeTranscriptionSessionConfigVault { _ in
            await mintCount.increment()
            let count = await mintCount.count()
            try await Task.sleep(for: .milliseconds(120))
            return Self.config(token: "token-\(count)")
        }

        await vault.prefetch(for: key)
        try await waitUntil { await mintCount.count() == 1 }

        async let first = vault.take(
            for: key,
            expectedProvider: "deepgram",
            expectedModel: "nova-3"
        )
        async let second = vault.take(
            for: key,
            expectedProvider: "deepgram",
            expectedModel: "nova-3"
        )
        let results = try await [first, second]

        XCTAssertEqual(Set(results.map(\.config.token)), ["token-1", "token-2"])
        XCTAssertEqual(results.filter(\.prefetched).count, 1)
        let count = await mintCount.count()
        XCTAssertEqual(count, 2)
    }

    func testTakeRejectsCachedConfigForDifferentProviderAndMintsFresh() async throws {
        let mintCount = SessionConfigMintCounter()
        let vault = RealtimeTranscriptionSessionConfigVault { _ in
            await mintCount.increment()
            let count = await mintCount.count()
            if count == 1 {
                return Self.config(token: "stale", provider: "legacy", model: "legacy-live")
            }
            return Self.config(token: "fresh")
        }

        await vault.prefetch(for: key)
        try await Task.sleep(for: .milliseconds(100))

        let result = try await vault.take(
            for: key,
            expectedProvider: "deepgram",
            expectedModel: "nova-3"
        )

        XCTAssertEqual(result.config.token, "fresh")
        XCTAssertFalse(result.prefetched)
        let count = await mintCount.count()
        XCTAssertEqual(count, 2)
    }

    func testTakeRejectsCachedConfigForDifferentLanguageAndMintsFresh() async throws {
        let mintCount = SessionConfigMintCounter()
        let russianKey = RealtimeTranscriptionSessionConfigVault.Key(
            language: "ru",
            channels: 1,
            purpose: .dictation
        )
        let vault = RealtimeTranscriptionSessionConfigVault { _ in
            await mintCount.increment()
            let count = await mintCount.count()
            if count == 1 {
                return Self.config(token: "stale", language: "multi")
            }
            return Self.config(token: "fresh", language: "ru")
        }

        await vault.prefetch(for: russianKey)
        try await Task.sleep(for: .milliseconds(100))

        let result = try await vault.take(
            for: russianKey,
            expectedProvider: "deepgram",
            expectedModel: "nova-3"
        )

        XCTAssertEqual(result.config.token, "fresh")
        XCTAssertEqual(result.config.language, "ru")
        XCTAssertFalse(result.prefetched)
        let count = await mintCount.count()
        XCTAssertEqual(count, 2)
    }

    func testTakeAcceptsBackendBaseLanguageNormalization() async throws {
        let regionKey = RealtimeTranscriptionSessionConfigVault.Key(
            language: "ru-RU",
            channels: 1,
            purpose: .dictation
        )
        let vault = RealtimeTranscriptionSessionConfigVault { key in
            Self.config(token: "normalized", language: key.language == "ru-RU" ? "ru" : key.language)
        }

        let result = try await vault.take(
            for: regionKey,
            expectedProvider: "deepgram",
            expectedModel: "nova-3"
        )

        XCTAssertEqual(result.config.token, "normalized")
        XCTAssertEqual(result.config.language, "ru")
    }

    func testTakeDoesNotReusePrefetchForDifferentHintSignature() async throws {
        let baseKey = RealtimeTranscriptionSessionConfigVault.Key(
            language: "multi",
            channels: 1,
            purpose: .dictation
        )
        let hintedKey = RealtimeTranscriptionSessionConfigVault.Key(
            language: "multi",
            channels: 1,
            purpose: .dictation,
            keyterms: ["WaiComputer"],
            replacements: [
                RealtimeTranscriptionReplacement(find: "why computer", replace: "WaiComputer"),
            ]
        )
        let mintCount = SessionConfigMintCounter()
        let vault = RealtimeTranscriptionSessionConfigVault { key in
            await mintCount.increment()
            return Self.config(
                token: key.hintSignature.isEmpty ? "base" : "hinted",
                language: key.language
            )
        }

        await vault.prefetch(for: baseKey)
        try await Task.sleep(for: .milliseconds(100))

        let result = try await vault.take(
            for: hintedKey,
            expectedProvider: "deepgram",
            expectedModel: "nova-3"
        )

        XCTAssertFalse(result.prefetched)
        XCTAssertEqual(result.config.token, "hinted")
        let count = await mintCount.count()
        XCTAssertEqual(count, 2)
    }

    func testExpiredPrefetchIsNotUsed() async throws {
        let mintCount = SessionConfigMintCounter()
        let vault = RealtimeTranscriptionSessionConfigVault { _ in
            await mintCount.increment()
            let count = await mintCount.count()
            if count == 1 {
                return Self.config(token: "expired", expiresInSeconds: 1)
            }
            return Self.config(token: "fresh", expiresInSeconds: 120)
        }

        await vault.prefetch(for: key)
        try await Task.sleep(for: .milliseconds(100))

        let result = try await vault.take(for: key)

        XCTAssertEqual(result.config.token, "fresh")
        XCTAssertFalse(result.prefetched)
        let count = await mintCount.count()
        XCTAssertEqual(count, 2)
    }

    private static func config(
        token: String,
        provider: String = "deepgram",
        model: String = "nova-3",
        language: String = "multi",
        expiresInSeconds: Int = 120
    ) -> RealtimeTranscriptionSessionConfig {
        RealtimeTranscriptionSessionConfig(
            provider: provider,
            token: token,
            expiresInSeconds: expiresInSeconds,
            sampleRate: 16_000,
            audioFormat: "linear16",
            language: language,
            channels: 1,
            model: model,
            commitStrategy: "manual",
            websocketURL: "wss://api.deepgram.com/v1/listen?model=nova-3",
            authScheme: "bearer"
        )
    }

    private func waitUntil(
        timeout: Duration = .seconds(1),
        condition: @escaping () async -> Bool
    ) async throws {
        let clock = ContinuousClock()
        let deadline = clock.now.advanced(by: timeout)
        while clock.now < deadline {
            if await condition() {
                return
            }
            try await Task.sleep(for: .milliseconds(10))
        }
        XCTFail("Timed out waiting for condition")
    }
}

private actor SessionConfigMintCounter {
    private var value: Int = 0
    func increment() { value += 1 }
    func count() -> Int { value }
}
