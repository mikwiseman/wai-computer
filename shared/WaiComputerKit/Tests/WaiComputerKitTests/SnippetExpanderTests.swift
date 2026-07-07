import XCTest
@testable import WaiComputerKit

final class SnippetExpanderTests: XCTestCase {
    private let email = DictationSnippetRule(trigger: "my email", expansion: "hi@mikwiseman.com")
    private let address = DictationSnippetRule(
        trigger: "office address",
        expansion: "Innovation Drive 42, Dublin"
    )

    // MARK: - Whole-utterance match

    /// Dictating just the trigger replaces the whole text with the expansion,
    /// ignoring case and trailing punctuation the cleanup may have added.
    func testWholeUtteranceMatchIgnoresCaseAndTrailingPunctuation() {
        XCTAssertEqual(
            SnippetExpander.apply(to: "My email.", snippets: [email]),
            "hi@mikwiseman.com"
        )
        XCTAssertEqual(
            SnippetExpander.apply(to: "my email", snippets: [email]),
            "hi@mikwiseman.com"
        )
    }

    /// Russian trailing punctuation and dictation artifacts strip the same way.
    func testWholeUtteranceMatchHandlesQuestionAndExclamation() {
        XCTAssertEqual(
            SnippetExpander.apply(to: "My email!", snippets: [email]),
            "hi@mikwiseman.com"
        )
    }

    // MARK: - In-sentence match

    /// Inside a sentence the trigger must match as an exact phrase on word
    /// boundaries; each occurrence expands in place.
    func testInSentenceExactPhraseExpands() {
        XCTAssertEqual(
            SnippetExpander.apply(
                to: "Send the contract to my email by Friday.",
                snippets: [email]
            ),
            "Send the contract to hi@mikwiseman.com by Friday."
        )
    }

    func testInSentenceMatchIsCaseInsensitive() {
        XCTAssertEqual(
            SnippetExpander.apply(to: "Send it to My Email today.", snippets: [email]),
            "Send it to hi@mikwiseman.com today."
        )
    }

    /// Partial-word overlaps must NOT expand ("my emails" is not the trigger).
    func testPartialWordDoesNotExpand() {
        let text = "Check my emails for the invite."
        XCTAssertEqual(SnippetExpander.apply(to: text, snippets: [email]), text)
    }

    /// Multiple different snippets expand independently in one pass.
    func testMultipleSnippetsExpand() {
        XCTAssertEqual(
            SnippetExpander.apply(
                to: "Ship to office address and cc my email.",
                snippets: [email, address]
            ),
            "Ship to Innovation Drive 42, Dublin and cc hi@mikwiseman.com."
        )
    }

    /// Longer triggers win when one trigger is a prefix of another, so the
    /// more specific snippet is never shadowed.
    func testLongerTriggerWinsOverPrefix() {
        let short = DictationSnippetRule(trigger: "sign", expansion: "Mik")
        let long = DictationSnippetRule(
            trigger: "sign off",
            expansion: "Best regards,\nMik Wiseman"
        )
        XCTAssertEqual(
            SnippetExpander.apply(to: "sign off", snippets: [short, long]),
            "Best regards,\nMik Wiseman"
        )
    }

    /// Expansions are literal text: expanding never re-triggers other
    /// snippets (no recursive expansion).
    func testNoRecursiveExpansion() {
        let a = DictationSnippetRule(trigger: "alpha", expansion: "beta")
        let b = DictationSnippetRule(trigger: "beta", expansion: "gamma")
        XCTAssertEqual(SnippetExpander.apply(to: "alpha", snippets: [a, b]), "beta")
    }

    /// Cyrillic triggers work with the same word-boundary semantics.
    func testCyrillicTriggerExpands() {
        let ru = DictationSnippetRule(trigger: "мой адрес", expansion: "Тверская 1, Москва")
        XCTAssertEqual(
            SnippetExpander.apply(to: "Отправь на мой адрес завтра.", snippets: [ru]),
            "Отправь на Тверская 1, Москва завтра."
        )
        XCTAssertEqual(
            SnippetExpander.apply(to: "Мой адрес.", snippets: [ru]),
            "Тверская 1, Москва"
        )
    }

    func testEmptySnippetsReturnTextUnchanged() {
        XCTAssertEqual(SnippetExpander.apply(to: "Hello there.", snippets: []), "Hello there.")
    }
}
