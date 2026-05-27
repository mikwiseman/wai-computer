import XCTest
@testable import WaiComputerKit

final class TokenVaultTests: XCTestCase {

    // MARK: - Helpers

    private func makeToken(
        value: String = "tok-abc",
        livesForSeconds: Double = 600,
        provider: String = "openai",
        model: String = "gpt-realtime-whisper",
        sampleRate: Int = 24_000
    ) -> TokenVault.Token {
        let now = ContinuousClock().now
        return TokenVault.Token(
            value: value,
            expiresAt: now.advanced(by: .seconds(livesForSeconds)),
            mintedAt: now,
            provider: provider,
            model: model,
            endpoint: URL(string: "wss://example.test"),
            sampleRate: sampleRate
        )
    }

    // MARK: - Token.isAlive

    func testTokenIsAliveBeforeExpiry() {
        let token = makeToken(livesForSeconds: 600)
        XCTAssertTrue(token.isAlive(forNow: ContinuousClock().now))
    }

    func testTokenIsNotAliveAfterExpiry() {
        let now = ContinuousClock().now
        let token = TokenVault.Token(
            value: "expired",
            expiresAt: now.advanced(by: .seconds(-1)),
            provider: "openai",
            model: "gpt-realtime-whisper"
        )
        XCTAssertFalse(token.isAlive(forNow: now))
    }

    func testTokenIsNotAliveWithinSafetyMargin() {
        let now = ContinuousClock().now
        // expires in 20s; safety margin defaults to 30s => not alive
        let token = TokenVault.Token(
            value: "soon",
            expiresAt: now.advanced(by: .seconds(20)),
            provider: "openai",
            model: "gpt-realtime-whisper"
        )
        XCTAssertFalse(token.isAlive(forNow: now), "token within safety margin treated as dead")
    }

    func testTokenCustomSafetyMargin() {
        let now = ContinuousClock().now
        let token = TokenVault.Token(
            value: "x",
            expiresAt: now.advanced(by: .seconds(20)),
            provider: "openai",
            model: "gpt-realtime-whisper"
        )
        XCTAssertTrue(token.isAlive(forNow: now, safety: .seconds(5)), "5s margin allows 20s-from-expiry to be alive")
        XCTAssertFalse(token.isAlive(forNow: now, safety: .seconds(25)))
    }

    // MARK: - Vault.token mint + cache

    func testTokenMintsFreshOnFirstCall() async throws {
        let mintCount = MintCounter()
        let vault = TokenVault {
            await mintCount.increment()
            return self.makeToken()
        }
        let token = try await vault.token()
        XCTAssertEqual(token.value, "tok-abc")
        let count = await mintCount.value
        XCTAssertEqual(count, 1, "first call mints exactly once")
    }

    func testTokenReturnsCachedWhenAlive() async throws {
        let mintCount = MintCounter()
        let vault = TokenVault {
            await mintCount.increment()
            return self.makeToken(livesForSeconds: 600)
        }
        _ = try await vault.token()
        _ = try await vault.token()
        _ = try await vault.token()

        let count = await mintCount.value
        // First call mints. Subsequent calls hit the cache. Background refresh may
        // OR may not have minted again before we read count — accept either, but
        // the cache must have prevented a per-call mint.
        XCTAssertLessThanOrEqual(count, 2, "calls served from cache, not minted per call")
    }

    func testTokenMintsAgainWhenCacheExpires() async throws {
        let mintCount = MintCounter()
        let vault = TokenVault {
            await mintCount.increment()
            // Very short lifetime → first call returns it, second sees it as not-alive.
            return self.makeToken(livesForSeconds: 10) // < safety margin (30s)
        }

        _ = try await vault.token()
        _ = try await vault.token()

        let count = await mintCount.value
        XCTAssertGreaterThanOrEqual(count, 2, "expired cache forces re-mint on next call")
    }

    func testMinterErrorPropagates() async throws {
        struct MintFailed: Error {}
        let vault = TokenVault { throw MintFailed() }

        do {
            _ = try await vault.token()
            XCTFail("expected MintFailed to propagate")
        } catch is MintFailed {
            // OK
        }
    }

    // MARK: - Vault.clear

    func testClearForcesNextCallToMint() async throws {
        let mintCount = MintCounter()
        let vault = TokenVault {
            await mintCount.increment()
            return self.makeToken(livesForSeconds: 600)
        }
        _ = try await vault.token()
        await vault.clear()
        _ = try await vault.token()

        let count = await mintCount.value
        XCTAssertGreaterThanOrEqual(count, 2, "clear forces re-mint")
    }

    // MARK: - Vault.prefetch (background, fire-and-forget)

    func testPrefetchEventuallyPopulatesCache() async throws {
        let mintCount = MintCounter()
        let vault = TokenVault {
            await mintCount.increment()
            return self.makeToken(livesForSeconds: 600)
        }
        await vault.prefetch()

        // Wait briefly for the background task to complete
        try await Task.sleep(nanoseconds: 100_000_000) // 100ms

        let countAfterPrefetch = await mintCount.value
        XCTAssertGreaterThanOrEqual(countAfterPrefetch, 1, "prefetch fires the minter")

        _ = try await vault.token()
        let countAfterToken = await mintCount.value
        // token() should use the cached prefetch — so we shouldn't have a lot more mints
        XCTAssertLessThanOrEqual(countAfterToken, countAfterPrefetch + 1)
    }

    // MARK: - Token init defaults

    func testTokenInitDefaults() {
        let token = TokenVault.Token(
            value: "abc",
            expiresAt: ContinuousClock().now.advanced(by: .seconds(60)),
            provider: "openai",
            model: "gpt-realtime-whisper"
        )
        XCTAssertNil(token.endpoint)
        XCTAssertEqual(token.sampleRate, 24_000, "default sampleRate is 24kHz")
    }
}

/// Thread-safe counter that can be incremented from any actor or task.
private actor MintCounter {
    private(set) var value: Int = 0
    func increment() { value += 1 }
}
