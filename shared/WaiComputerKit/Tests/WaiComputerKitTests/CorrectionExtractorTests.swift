import XCTest
@testable import WaiComputerKit

/// Lexicon stub: a fixed set of "known common words" (case-insensitive).
/// Anything not in the set is treated as out-of-vocabulary (learnable).
private struct FakeLexicon: LexiconChecking {
    let known: Set<String>
    init(_ words: [String]) { self.known = Set(words.map { $0.lowercased() }) }
    func isKnownWord(_ token: String, language: String?) -> Bool {
        known.contains(token.lowercased())
    }
}

final class CorrectionExtractorTests: XCTestCase {

    private func makeExtractor(known: [String]) -> CorrectionExtractor {
        CorrectionExtractor(lexicon: FakeLexicon(known))
    }

    func testSpellingMishearingOfProperNounIsLearned() {
        let extractor = makeExtractor(known: ["let's", "use", "here"])
        let result = extractor.extract(
            produced: "let's use sigma here",
            edited: "let's use Figma here",
            language: "en"
        )
        XCTAssertNil(result.skipped)
        XCTAssertEqual(result.pairs.count, 1)
        XCTAssertEqual(result.pairs.first?.original, "sigma")
        XCTAssertEqual(result.pairs.first?.corrected, "Figma")
    }

    func testSemanticRewriteIsRejected() {
        // "budget" → "allocation" is not a mis-hearing; the phonetic gate drops it.
        let extractor = makeExtractor(known: ["increase", "the"])
        let result = extractor.extract(
            produced: "increase the budget",
            edited: "increase the allocation",
            language: "en"
        )
        XCTAssertTrue(result.pairs.isEmpty)
    }

    func testCommonWordCorrectionIsNotLearned() {
        // "teh" → "the": "the" is a known common word, never auto-learned.
        let extractor = makeExtractor(known: ["the", "cat", "sat"])
        let result = extractor.extract(
            produced: "teh cat sat",
            edited: "the cat sat",
            language: "en"
        )
        XCTAssertTrue(result.pairs.isEmpty)
    }

    func testCapitalizationOfOOVProperNounIsLearned() {
        let extractor = makeExtractor(known: ["i", "opened", "today"])
        let result = extractor.extract(
            produced: "i opened figma today",
            edited: "i opened Figma today",
            language: "en"
        )
        XCTAssertEqual(result.pairs.count, 1)
        XCTAssertEqual(result.pairs.first?.original, "figma")
        XCTAssertEqual(result.pairs.first?.corrected, "Figma")
    }

    func testDowncasingProperNounIsNotLearned() {
        let extractor = makeExtractor(known: ["i", "opened", "today", "love", "apps"])
        XCTAssertTrue(
            extractor.extract(produced: "i opened Figma today", edited: "i opened figma today", language: "en").pairs.isEmpty,
            "down-casing an OOV proper noun must not be learned"
        )
        XCTAssertTrue(
            extractor.extract(produced: "love iOS apps", edited: "love ios apps", language: "en").pairs.isEmpty
        )
    }

    func testSentenceStartCapitalizationOfCommonWordIsNotLearned() {
        let extractor = makeExtractor(known: ["hello", "world"])
        let result = extractor.extract(
            produced: "hello world",
            edited: "Hello world",
            language: "en"
        )
        XCTAssertTrue(result.pairs.isEmpty)
    }

    func testNumeralCorrectionIsNotLearned() {
        let extractor = makeExtractor(known: ["i", "have", "apples"])
        let result = extractor.extract(
            produced: "i have five apples",
            edited: "i have 5 apples",
            language: "en"
        )
        XCTAssertTrue(result.pairs.isEmpty)
    }

    func testIdenticalTextSkips() {
        let extractor = makeExtractor(known: ["hello"])
        let result = extractor.extract(produced: "hello there", edited: "hello there", language: "en")
        XCTAssertEqual(result.skipped, .identical)
        XCTAssertTrue(result.pairs.isEmpty)
    }

    func testLargeRewriteIsTooDivergent() {
        let extractor = makeExtractor(known: [])
        let result = extractor.extract(
            produced: "alpha beta gamma",
            edited: "x y z w v",
            language: "en"
        )
        XCTAssertEqual(result.skipped, .tooDivergent)
    }

    func testEditWithinLargerDocumentIsScopedToInsertedRegion() {
        let extractor = makeExtractor(known: ["i", "use", "daily", "ship", "it", "meeting", "notes"])
        let result = extractor.extract(
            produced: "i use figmaa daily",
            edited: "Meeting notes: i use Figma daily. ship it.",
            language: "en"
        )
        XCTAssertEqual(result.pairs.count, 1)
        XCTAssertEqual(result.pairs.first?.corrected, "Figma")
    }

    func testRussianOOVMishearingIsLearned() {
        let extractor = makeExtractor(known: ["разверни"])
        let result = extractor.extract(
            produced: "разверни кубернетис",
            edited: "разверни кубернетес",
            language: "ru"
        )
        XCTAssertEqual(result.pairs.count, 1)
        XCTAssertEqual(result.pairs.first?.corrected, "кубернетес")
    }

    func testEmptyInputsSkip() {
        let extractor = makeExtractor(known: [])
        XCTAssertEqual(extractor.extract(produced: "", edited: "x", language: nil).skipped, .emptyInput)
        XCTAssertEqual(extractor.extract(produced: "x", edited: "   ", language: nil).skipped, .emptyInput)
    }
}
