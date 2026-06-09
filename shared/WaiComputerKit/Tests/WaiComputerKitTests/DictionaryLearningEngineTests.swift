import XCTest
@testable import WaiComputerKit

private struct FakeLexicon: LexiconChecking {
    let known: Set<String>
    init(_ words: [String]) { self.known = Set(words.map { $0.lowercased() }) }
    func isKnownWord(_ token: String, language: String?) -> Bool { known.contains(token.lowercased()) }
}

/// Mutable clock so window/recurrence behaviour is deterministic.
private final class TestClock: @unchecked Sendable {
    var now: Date
    init(_ start: Date) { self.now = start }
}

@MainActor
final class DictionaryLearningEngineTests: XCTestCase {

    private var storeURL: URL!

    override func setUp() {
        super.setUp()
        storeURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("wai-learn-\(UUID().uuidString).json")
    }

    override func tearDown() {
        try? FileManager.default.removeItem(at: storeURL)
        super.tearDown()
    }

    private func makeEngine(
        clock: TestClock,
        promoteAfter: Int = 2,
        window: TimeInterval = 30 * 24 * 60 * 60
    ) -> DictionaryLearningEngine {
        DictionaryLearningEngine(
            lexicon: FakeLexicon(["let's", "use", "here", "open"]),
            config: .init(promoteAfter: promoteAfter, window: window),
            storeURL: storeURL,
            dateProvider: { clock.now }
        )
    }

    private func observeFigmaFix(_ engine: DictionaryLearningEngine) {
        engine.observeEdit(produced: "let's use sigma here", edited: "let's use Figma here", language: "en")
    }

    func testNoSuggestionBelowThreshold() {
        let engine = makeEngine(clock: TestClock(Date()))
        observeFigmaFix(engine)
        XCTAssertTrue(engine.suggestions.isEmpty)
    }

    func testSuggestionAppearsAfterRecurrence() {
        let engine = makeEngine(clock: TestClock(Date()))
        observeFigmaFix(engine)
        observeFigmaFix(engine)
        XCTAssertEqual(engine.suggestions.count, 1)
        XCTAssertEqual(engine.suggestions.first?.corrected, "Figma")
        XCTAssertEqual(engine.suggestions.first?.original, "sigma")
        XCTAssertEqual(engine.suggestions.first?.hitCount, 2)
    }

    func testDismissSuppressesEvenOnFurtherEdits() {
        let engine = makeEngine(clock: TestClock(Date()))
        observeFigmaFix(engine)
        observeFigmaFix(engine)
        let suggestion = try! XCTUnwrap(engine.suggestions.first)
        engine.dismiss(suggestion)
        XCTAssertTrue(engine.suggestions.isEmpty)
        observeFigmaFix(engine) // would be hit #3
        XCTAssertTrue(engine.suggestions.isEmpty, "dismissed pair must not re-surface")
    }

    func testAcceptRemovesSuggestion() {
        let engine = makeEngine(clock: TestClock(Date()))
        observeFigmaFix(engine)
        observeFigmaFix(engine)
        let suggestion = try! XCTUnwrap(engine.suggestions.first)
        engine.accept(suggestion)
        XCTAssertTrue(engine.suggestions.isEmpty)
    }

    func testStaleCorrectionDecaysOutOfWindow() {
        let clock = TestClock(Date(timeIntervalSince1970: 1_000_000))
        let engine = makeEngine(clock: clock, window: 60 * 60) // 1h window
        observeFigmaFix(engine)                 // hit #1 at t0
        clock.now = clock.now.addingTimeInterval(2 * 60 * 60) // +2h, past window
        observeFigmaFix(engine)                 // hit #1 again (old one pruned)
        XCTAssertTrue(engine.suggestions.isEmpty, "expired hit should not count toward the threshold")
    }

    func testPersistenceRoundTrip() {
        let clock = TestClock(Date())
        let engineA = makeEngine(clock: clock)
        observeFigmaFix(engineA)
        observeFigmaFix(engineA)
        XCTAssertEqual(engineA.suggestions.count, 1)

        // A fresh engine over the same store reloads the promoted suggestion.
        let engineB = makeEngine(clock: clock)
        XCTAssertEqual(engineB.suggestions.count, 1)
        XCTAssertEqual(engineB.suggestions.first?.corrected, "Figma")
    }

    func testClearAllForgetsEverything() {
        let engine = makeEngine(clock: TestClock(Date()))
        observeFigmaFix(engine)
        observeFigmaFix(engine)
        XCTAssertEqual(engine.suggestions.count, 1)
        engine.clearAll()
        XCTAssertTrue(engine.suggestions.isEmpty)
    }
}
