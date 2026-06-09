import XCTest
@testable import WaiComputerKit

final class TokenAlignmentTests: XCTestCase {

    // MARK: - tokenize

    func testTokenizeSimpleEnglish() {
        XCTAssertEqual(
            TokenAlignment.tokenize("hello world"),
            ["hello", "world"]
        )
    }

    func testTokenizeStripsSurroundingPunctuation() {
        XCTAssertEqual(
            TokenAlignment.tokenize("I love Figma, it rocks!"),
            ["I", "love", "Figma", "it", "rocks"]
        )
    }

    func testTokenizeKeepsStraightApostrophe() {
        XCTAssertEqual(
            TokenAlignment.tokenize("don't can't won't"),
            ["don't", "can't", "won't"]
        )
    }

    func testTokenizeKeepsCurlyApostrophe() {
        XCTAssertEqual(
            TokenAlignment.tokenize("don\u{2019}t"),
            ["don\u{2019}t"]
        )
    }

    func testTokenizeKeepsIntraWordHyphen() {
        XCTAssertEqual(
            TokenAlignment.tokenize("IT-директор work-life balance"),
            ["IT-директор", "work-life", "balance"]
        )
    }

    func testTokenizeDropsLeadingAndTrailingConnectors() {
        // Leading/trailing hyphens and apostrophes are separators, not part of
        // the token (only intra-word connectors are kept).
        XCTAssertEqual(
            TokenAlignment.tokenize("-foo- 'bar'"),
            ["foo", "bar"]
        )
    }

    func testTokenizeRussian() {
        XCTAssertEqual(
            TokenAlignment.tokenize("Привет, мир!"),
            ["Привет", "мир"]
        )
    }

    func testTokenizeMixedCyrillicLatinAndNumbers() {
        XCTAssertEqual(
            TokenAlignment.tokenize("Открой Figma 2 раза"),
            ["Открой", "Figma", "2", "раза"]
        )
    }

    func testTokenizeEmptyInput() {
        XCTAssertEqual(TokenAlignment.tokenize(""), [])
    }

    func testTokenizeWhitespaceOnlyInput() {
        XCTAssertEqual(TokenAlignment.tokenize("   \n\t  "), [])
    }

    func testTokenizePunctuationOnlyInput() {
        XCTAssertEqual(TokenAlignment.tokenize("!?.,;:—…"), [])
    }

    func testTokenizeMultipleSpacesAndNewlines() {
        XCTAssertEqual(
            TokenAlignment.tokenize("one   two\nthree\t four"),
            ["one", "two", "three", "four"]
        )
    }

    func testTokenizeEmDashSeparatesTokens() {
        // Em dash is intentionally NOT an intra-word connector.
        XCTAssertEqual(
            TokenAlignment.tokenize("foo—bar"),
            ["foo", "bar"]
        )
    }

    // MARK: - normalize

    func testNormalizeLowercasesAndStripsTrailingComma() {
        XCTAssertEqual(TokenAlignment.normalize("Figma,"), "figma")
    }

    func testNormalizeFigmaCommaEqualsFigma() {
        XCTAssertEqual(
            TokenAlignment.normalize("Figma,"),
            TokenAlignment.normalize("figma")
        )
    }

    func testNormalizeStripsLeadingAndTrailingPunctuation() {
        XCTAssertEqual(TokenAlignment.normalize("\"(hello)!\""), "hello")
    }

    func testNormalizeCyrillicCaseFold() {
        XCTAssertEqual(TokenAlignment.normalize("Привет"), "привет")
        XCTAssertEqual(
            TokenAlignment.normalize("ПРИВЕТ,"),
            TokenAlignment.normalize("привет")
        )
    }

    func testNormalizeKeepsIntraWordApostrophe() {
        // The apostrophe is internal, so it must survive normalization.
        XCTAssertEqual(TokenAlignment.normalize("Don't"), "don't")
    }

    func testNormalizeNFCComposesCombiningMarks() {
        // Decomposed "й" (и + combining breve) must normalize identically to the
        // precomposed form.
        let decomposed = "\u{0438}\u{0306}"          // и + ̆
        let precomposed = "\u{0439}"                 // й
        XCTAssertEqual(
            TokenAlignment.normalize(decomposed),
            TokenAlignment.normalize(precomposed)
        )
    }

    func testNormalizeEmptyAndPunctuationOnly() {
        XCTAssertEqual(TokenAlignment.normalize(""), "")
        XCTAssertEqual(TokenAlignment.normalize("!!!"), "")
    }

    // MARK: - align: match

    func testAlignIdenticalIsAllMatches() {
        let ops = TokenAlignment.align(["I", "love", "Figma"], ["I", "love", "Figma"])
        XCTAssertEqual(ops, [.match("I"), .match("love"), .match("Figma")])
    }

    func testAlignCaseAndPunctuationOnlyDifferenceIsMatch() {
        // "Figma," vs "figma" normalize equal ⇒ match, NOT substitute.
        let ops = TokenAlignment.align(["Figma,"], ["figma"])
        XCTAssertEqual(ops, [.match("figma")])
    }

    // MARK: - align: substitute

    func testAlignSingleSubstitute() {
        let ops = TokenAlignment.align(["cat"], ["dog"])
        XCTAssertEqual(ops, [.substitute(from: "cat", to: "dog")])
    }

    func testAlignILoveFigmaCapitalizationIsAllMatches() {
        // FOUNDATIONAL RULE (stated three times in the file/CorrectionTypes
        // docs): tokens whose normalize() are equal align as .match, NOT
        // .substitute — a pure capitalization change is not a learnable edit.
        // normalize("figma") == normalize("Figma"), so "I love figma" →
        // "I love Figma" is three matches; the match carries the edited surface.
        let produced = TokenAlignment.tokenize("I love figma")
        let edited = TokenAlignment.tokenize("I love Figma")
        let ops = TokenAlignment.align(produced, edited)
        XCTAssertEqual(
            ops,
            [.match("I"), .match("love"), .match("Figma")]
        )
    }

    func testAlignRealWordSwapYieldsExactlyOneSubstitute() {
        // The genuine "learnable" case the engine cares about: the recognizer
        // mis-heard a word (not a case difference), the user fixed it. Exactly
        // one substitute, the rest match.
        let produced = TokenAlignment.tokenize("I love figmma")
        let edited = TokenAlignment.tokenize("I love figma")
        let ops = TokenAlignment.align(produced, edited)
        XCTAssertEqual(
            ops,
            [.match("I"), .match("love"), .substitute(from: "figmma", to: "figma")]
        )
        // And exactly one substitute overall.
        let substituteCount = ops.filter {
            if case .substitute = $0 { return true }
            return false
        }.count
        XCTAssertEqual(substituteCount, 1)
    }

    func testAlignSubstituteInMiddle() {
        let ops = TokenAlignment.align(
            ["open", "the", "door"],
            ["open", "a", "door"]
        )
        XCTAssertEqual(
            ops,
            [.match("open"), .substitute(from: "the", to: "a"), .match("door")]
        )
    }

    // MARK: - align: insert

    func testAlignInsert() {
        let ops = TokenAlignment.align(
            ["open", "door"],
            ["open", "the", "door"]
        )
        XCTAssertEqual(
            ops,
            [.match("open"), .insert("the"), .match("door")]
        )
    }

    func testAlignInsertIntoEmptyProduced() {
        let ops = TokenAlignment.align([], ["hello", "world"])
        XCTAssertEqual(ops, [.insert("hello"), .insert("world")])
    }

    // MARK: - align: delete

    func testAlignDelete() {
        let ops = TokenAlignment.align(
            ["open", "the", "door"],
            ["open", "door"]
        )
        XCTAssertEqual(
            ops,
            [.match("open"), .delete("the"), .match("door")]
        )
    }

    func testAlignDeleteToEmptyEdited() {
        let ops = TokenAlignment.align(["hello", "world"], [])
        XCTAssertEqual(ops, [.delete("hello"), .delete("world")])
    }

    func testAlignBothEmpty() {
        XCTAssertEqual(TokenAlignment.align([], []), [])
    }

    // MARK: - align: combined / reconstruction

    func testAlignedEditedSurfaceReconstructsEditedStream() {
        // Concatenating the "edited side" of every op (match=surface,
        // substitute=to, insert=token, delete=nothing) must rebuild `edited`.
        let produced = TokenAlignment.tokenize("please open figma now")
        let edited = TokenAlignment.tokenize("please open Figma right now")
        let ops = TokenAlignment.align(produced, edited)

        var rebuilt: [String] = []
        for op in ops {
            switch op {
            case .match(let s): rebuilt.append(s)
            case .substitute(_, let to): rebuilt.append(to)
            case .insert(let s): rebuilt.append(s)
            case .delete: break
            }
        }
        XCTAssertEqual(rebuilt, edited)
        // "figma" → "Figma" is a case-only change ⇒ a match carrying the edited
        // surface (not a substitute); the new word is an insert.
        XCTAssertTrue(ops.contains(.match("Figma")))
        XCTAssertTrue(ops.contains(.insert("right")))
        // No substitutions at all in this purely cosmetic + insert edit.
        XCTAssertFalse(ops.contains { if case .substitute = $0 { return true }; return false })
    }

    func testAlignedProducedSurfaceReconstructsProducedStream() {
        let produced = TokenAlignment.tokenize("the quick brown fox jumped")
        let edited = TokenAlignment.tokenize("a quick red fox leaps high")
        let ops = TokenAlignment.align(produced, edited)

        var rebuilt: [String] = []
        for op in ops {
            switch op {
            case .match(let s): rebuilt.append(s)        // match carries edited surface
            case .substitute(let from, _): rebuilt.append(from)
            case .insert: break
            case .delete(let s): rebuilt.append(s)
            }
        }
        // match carries the edited surface, but for tokens that match they are
        // normalize-equal; reconstruct via normalized comparison instead.
        XCTAssertEqual(rebuilt.map(TokenAlignment.normalize),
                       produced.map(TokenAlignment.normalize))
    }

    // MARK: - locate: hit

    func testLocateFindsExactRun() {
        let haystack = TokenAlignment.tokenize("Notes: please open Figma now, thanks team")
        let needle = TokenAlignment.tokenize("open Figma now")
        let range = TokenAlignment.locate(needle, in: haystack)
        XCTAssertNotNil(range)
        if let range = range {
            let located = Array(haystack[range]).map(TokenAlignment.normalize)
            XCTAssertEqual(located, ["open", "figma", "now"])
        }
    }

    func testLocateFindsRunWithMinorSubstitution() {
        // One token in the inserted run was lightly edited; still locatable.
        let haystack = TokenAlignment.tokenize("intro open the figma file outro extra words")
        let needle = TokenAlignment.tokenize("open a figma file")
        let range = TokenAlignment.locate(needle, in: haystack)
        XCTAssertNotNil(range)
        if let range = range {
            // Should center on the "...figma file..." region.
            let located = Set(Array(haystack[range]).map(TokenAlignment.normalize))
            XCTAssertTrue(located.contains("figma"))
            XCTAssertTrue(located.contains("file"))
        }
    }

    func testLocateAtStart() {
        let haystack = TokenAlignment.tokenize("Figma is great and so is Sketch")
        let needle = TokenAlignment.tokenize("Figma is great")
        let range = TokenAlignment.locate(needle, in: haystack)
        XCTAssertEqual(range, 0..<3)
    }

    func testLocateRussianRun() {
        let haystack = TokenAlignment.tokenize("Сегодня я открыл Figma в редакторе и работал")
        let needle = TokenAlignment.tokenize("открыл Figma")
        let range = TokenAlignment.locate(needle, in: haystack)
        XCTAssertNotNil(range)
        if let range = range {
            let located = Array(haystack[range]).map(TokenAlignment.normalize)
            XCTAssertEqual(located, ["открыл", "figma"])
        }
    }

    // MARK: - locate: miss

    func testLocateReturnsNilForUnrelatedText() {
        let haystack = TokenAlignment.tokenize("the weather today is sunny and warm")
        let needle = TokenAlignment.tokenize("open Figma now please")
        XCTAssertNil(TokenAlignment.locate(needle, in: haystack))
    }

    func testLocateReturnsNilForEmptyNeedle() {
        let haystack = TokenAlignment.tokenize("some text here")
        XCTAssertNil(TokenAlignment.locate([], in: haystack))
    }

    func testLocateReturnsNilForEmptyHaystack() {
        let needle = TokenAlignment.tokenize("open Figma")
        XCTAssertNil(TokenAlignment.locate(needle, in: []))
    }

    func testLocateReturnsNilWhenOnlyOneOfManyMatches() {
        // Only "Figma" overlaps; 1/4 = 25% < 60% threshold ⇒ nil.
        let haystack = TokenAlignment.tokenize("I exported the Figma board to PDF yesterday")
        let needle = TokenAlignment.tokenize("save document close window")
        XCTAssertNil(TokenAlignment.locate(needle, in: haystack))
    }
}
