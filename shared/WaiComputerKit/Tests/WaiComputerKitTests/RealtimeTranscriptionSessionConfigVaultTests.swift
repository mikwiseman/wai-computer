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
            expectedProvider: "inworld",
            expectedModel: "inworld/inworld-stt-1"
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
            expectedProvider: "inworld",
            expectedModel: "inworld/inworld-stt-1"
        )
        let fresh = try await vault.take(
            for: key,
            expectedProvider: "inworld",
            expectedModel: "inworld/inworld-stt-1"
        )

        XCTAssertTrue(prefetched.prefetched)
        XCTAssertEqual(prefetched.config.token, "token-1")
        XCTAssertFalse(fresh.prefetched)
        XCTAssertEqual(fresh.config.token, "token-2")
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
            expectedProvider: "inworld",
            expectedModel: "inworld/inworld-stt-1"
        )

        XCTAssertEqual(result.config.token, "fresh")
        XCTAssertFalse(result.prefetched)
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
        provider: String = "inworld",
        model: String = "inworld/inworld-stt-1",
        language: String = "multi",
        expiresInSeconds: Int = 120
    ) -> RealtimeTranscriptionSessionConfig {
        RealtimeTranscriptionSessionConfig(
            provider: provider,
            token: token,
            expiresInSeconds: expiresInSeconds,
            sampleRate: 16_000,
            audioFormat: "linear16_16000",
            language: language,
            channels: 1,
            model: model,
            websocketURL: "wss://api.inworld.ai/stt/v1/transcribe:streamBidirectional",
            authScheme: "bearer"
        )
    }
}

private actor SessionConfigMintCounter {
    private var value: Int = 0
    func increment() { value += 1 }
    func count() -> Int { value }
}
