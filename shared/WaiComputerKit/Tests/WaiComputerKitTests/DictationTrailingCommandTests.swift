import XCTest
@testable import WaiComputerKit

final class DictationTrailingCommandTests: XCTestCase {
    func testPressEnterAtEndIsStrippedAndDetected() {
        let parsed = DictationTrailingCommand.parse("Ship it today press enter")
        XCTAssertEqual(parsed.text, "Ship it today")
        XCTAssertEqual(parsed.command, .pressEnter)
    }

    func testPressEnterWithPunctuationAndCase() {
        let parsed = DictationTrailingCommand.parse("Ship it today. Press Enter.")
        XCTAssertEqual(parsed.text, "Ship it today.")
        XCTAssertEqual(parsed.command, .pressEnter)
    }

    func testRussianVariantsDetected() {
        for phrase in ["нажми энтер", "нажми enter", "Нажми Энтер."] {
            let parsed = DictationTrailingCommand.parse("Отправляю отчёт \(phrase)")
            XCTAssertEqual(parsed.command, .pressEnter, "failed for: \(phrase)")
            XCTAssertEqual(parsed.text, "Отправляю отчёт")
        }
    }

    func testNoCommandLeavesTextUntouched() {
        let parsed = DictationTrailingCommand.parse("Just a normal sentence.")
        XCTAssertEqual(parsed.text, "Just a normal sentence.")
        XCTAssertNil(parsed.command)
    }

    /// Mid-sentence mention is NOT a command — only a trailing phrase is.
    func testMidSentenceMentionIsNotACommand() {
        let text = "The press enter key is on the right."
        let parsed = DictationTrailingCommand.parse(text)
        XCTAssertEqual(parsed.text, text)
        XCTAssertNil(parsed.command)
    }

    /// The whole utterance being just the command sends Enter with no text.
    func testCommandOnlyUtteranceYieldsEmptyText() {
        let parsed = DictationTrailingCommand.parse("Press enter")
        XCTAssertEqual(parsed.text, "")
        XCTAssertEqual(parsed.command, .pressEnter)
    }
}
