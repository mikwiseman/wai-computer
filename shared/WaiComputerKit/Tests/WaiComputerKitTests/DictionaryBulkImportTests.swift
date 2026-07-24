import XCTest
@testable import WaiComputerKit

final class DictionaryBulkImportTests: XCTestCase {
    func testParsesPlainWordsOnePerLine() {
        let result = DictionaryBulkImport.parse("WaiComputer\nCerebras\nАстерис\n")
        XCTAssertEqual(
            result.words,
            [
                DictionaryBulkImport.ParsedWord(word: "WaiComputer", replacement: nil),
                DictionaryBulkImport.ParsedWord(word: "Cerebras", replacement: nil),
                DictionaryBulkImport.ParsedWord(word: "Астерис", replacement: nil),
            ]
        )
        XCTAssertEqual(result.skippedLineCount, 0)
    }

    func testParsesReplacementsWithCommaSemicolonAndTab() {
        let contents = """
        Мейстудио,Wai Studio
        джипити;GPT
        куберн\tKubernetes
        """
        let result = DictionaryBulkImport.parse(contents)
        XCTAssertEqual(
            result.words,
            [
                DictionaryBulkImport.ParsedWord(word: "Мейстудио", replacement: "Wai Studio"),
                DictionaryBulkImport.ParsedWord(word: "джипити", replacement: "GPT"),
                DictionaryBulkImport.ParsedWord(word: "куберн", replacement: "Kubernetes"),
            ]
        )
    }

    func testSkipsBlankCommentAndHeaderLines() {
        let contents = """
        word,replacement

        # names from the design team
        Anna Karenina
        """
        let result = DictionaryBulkImport.parse(contents)
        XCTAssertEqual(
            result.words,
            [DictionaryBulkImport.ParsedWord(word: "Anna Karenina", replacement: nil)]
        )
        XCTAssertEqual(result.skippedLineCount, 0)
    }

    func testDeduplicatesCaseInsensitivelyFirstWins() {
        let result = DictionaryBulkImport.parse("OpenAI\nopenai\nOPENAI,Open AI")
        XCTAssertEqual(
            result.words,
            [DictionaryBulkImport.ParsedWord(word: "OpenAI", replacement: nil)]
        )
        XCTAssertEqual(result.skippedLineCount, 2)
    }

    func testSkipsOverlongEntriesAndCountsThem() {
        let longWord = String(repeating: "x", count: 201)
        let result = DictionaryBulkImport.parse("\(longWord)\nfine")
        XCTAssertEqual(
            result.words,
            [DictionaryBulkImport.ParsedWord(word: "fine", replacement: nil)]
        )
        XCTAssertEqual(result.skippedLineCount, 1)
    }

    func testCapsTotalImportedWords() {
        let contents = (1...600).map { "word\($0)" }.joined(separator: "\n")
        let result = DictionaryBulkImport.parse(contents)
        XCTAssertEqual(result.words.count, DictionaryBulkImport.maxWords)
        XCTAssertEqual(result.skippedLineCount, 600 - DictionaryBulkImport.maxWords)
    }

    func testHandlesCRLFAndWhitespace() {
        let result = DictionaryBulkImport.parse("  Sparkle \r\n\tтермин ,  замена  \r\n")
        XCTAssertEqual(
            result.words,
            [
                DictionaryBulkImport.ParsedWord(word: "Sparkle", replacement: nil),
                DictionaryBulkImport.ParsedWord(word: "термин", replacement: "замена"),
            ]
        )
    }

    func testEmptyReplacementBecomesNil() {
        let result = DictionaryBulkImport.parse("Anthropic,\nCursor;")
        XCTAssertEqual(
            result.words,
            [
                DictionaryBulkImport.ParsedWord(word: "Anthropic", replacement: nil),
                DictionaryBulkImport.ParsedWord(word: "Cursor", replacement: nil),
            ]
        )
    }
}
