import XCTest
@testable import WaiComputerKit

final class PhoneticMatcherTests: XCTestCase {

    // MARK: - similarity bounds

    func testSimilarityIdenticalIsOne() {
        XCTAssertEqual(PhoneticMatcher.similarity("figma", "figma"), 1.0, accuracy: 1e-9)
    }

    func testSimilarityIsCaseFolded() {
        XCTAssertEqual(PhoneticMatcher.similarity("Figma", "figma"), 1.0, accuracy: 1e-9)
        XCTAssertEqual(PhoneticMatcher.similarity("КОМПАНИЯ", "компания"), 1.0, accuracy: 1e-9)
    }

    func testSimilarityCompletelyDifferentIsZeroWhenNoSharedChars() {
        // Same length, no overlap → every position substitutes → 0.0.
        XCTAssertEqual(PhoneticMatcher.similarity("abc", "xyz"), 0.0, accuracy: 1e-9)
    }

    func testSimilarityBothEmptyIsOne() {
        XCTAssertEqual(PhoneticMatcher.similarity("", ""), 1.0, accuracy: 1e-9)
    }

    func testSimilarityOneEmptyIsZero() {
        XCTAssertEqual(PhoneticMatcher.similarity("figma", ""), 0.0, accuracy: 1e-9)
        XCTAssertEqual(PhoneticMatcher.similarity("", "figma"), 0.0, accuracy: 1e-9)
    }

    func testSimilarityIsSymmetric() {
        let ab = PhoneticMatcher.similarity("kubernetes", "kubernetis")
        let ba = PhoneticMatcher.similarity("kubernetis", "kubernetes")
        XCTAssertEqual(ab, ba, accuracy: 1e-9)
    }

    func testSimilarityKnownValue() {
        // "kitten" vs "sitting": Levenshtein 3, max len 7 → 1 - 3/7.
        XCTAssertEqual(PhoneticMatcher.similarity("kitten", "sitting"), 1.0 - 3.0 / 7.0, accuracy: 1e-9)
    }

    func testSimilarityStaysInUnitInterval() {
        let pairs = [("budget", "allocate"), ("figma", "kubernetes"), ("a", "zzzzzzzz"), ("работа", "собака")]
        for (a, b) in pairs {
            let s = PhoneticMatcher.similarity(a, b)
            XCTAssertGreaterThanOrEqual(s, 0.0)
            XCTAssertLessThanOrEqual(s, 1.0)
        }
    }

    // MARK: - EN sound-alikes (should learn)

    func testEnglishFigmaMisHearing() {
        XCTAssertTrue(PhoneticMatcher.areSoundAlike("figma", "figmah"))
        XCTAssertTrue(PhoneticMatcher.areSoundAlike("Figma", "figmah")) // case-insensitive
    }

    func testEnglishKubernetesMisHearing() {
        XCTAssertTrue(PhoneticMatcher.areSoundAlike("kubernetes", "kubernetis"))
    }

    func testEnglishMisHearingViaCodeEquality() {
        // The phonetic skeleton, not just edit distance, carries these.
        XCTAssertEqual(PhoneticMatcher.code(for: "figma"), PhoneticMatcher.code(for: "figmah"))
        XCTAssertEqual(PhoneticMatcher.code(for: "kubernetes"), PhoneticMatcher.code(for: "kubernetis"))
    }

    func testEnglishPhFoldsToF() {
        // PH → F so "phil"/"fil" share a skeleton.
        XCTAssertEqual(PhoneticMatcher.code(for: "phil"), PhoneticMatcher.code(for: "fil"))
        XCTAssertTrue(PhoneticMatcher.areSoundAlike("phil", "fil"))
    }

    func testEnglishDoubleLetterCollapses() {
        // CK → K and doubled letters collapse: "docker"/"doker" skeleton-equal.
        XCTAssertEqual(PhoneticMatcher.code(for: "docker"), PhoneticMatcher.code(for: "doker"))
        XCTAssertTrue(PhoneticMatcher.areSoundAlike("docker", "doker"))
    }

    func testEnglishWhitespaceInsensitive() {
        XCTAssertTrue(PhoneticMatcher.areSoundAlike("  figma ", "figmah  "))
    }

    // MARK: - EN non-sound-alikes (should NOT learn)

    func testEnglishBudgetVsAllocateRejected() {
        XCTAssertFalse(PhoneticMatcher.areSoundAlike("budget", "allocate"))
    }

    func testEnglishUnrelatedWordsRejected() {
        XCTAssertFalse(PhoneticMatcher.areSoundAlike("kubernetes", "budget"))
        XCTAssertFalse(PhoneticMatcher.areSoundAlike("figma", "sketch"))
        XCTAssertFalse(PhoneticMatcher.areSoundAlike("server", "banana"))
    }

    func testEnglishDistinctCodesForUnrelatedWords() {
        XCTAssertNotEqual(PhoneticMatcher.code(for: "budget"), PhoneticMatcher.code(for: "allocate"))
        XCTAssertNotEqual(PhoneticMatcher.code(for: "figma"), PhoneticMatcher.code(for: "sketch"))
    }

    // MARK: - RU sound-alikes (should learn)

    func testRussianKompaniaMisHearing() {
        // компания / кампания — classic о↔а unstressed confusion.
        XCTAssertTrue(PhoneticMatcher.areSoundAlike("компания", "кампания"))
        XCTAssertEqual(PhoneticMatcher.code(for: "компания"), PhoneticMatcher.code(for: "кампания"))
    }

    func testRussianFinalDevoicingMakesHomophones() {
        // код / кот sound identical (final д devoices to т).
        XCTAssertEqual(PhoneticMatcher.code(for: "код"), PhoneticMatcher.code(for: "кот"))
    }

    func testRussianVowelReductionEquivalence() {
        // молоко / малако reduce to the same skeleton (all о/а → А).
        XCTAssertEqual(PhoneticMatcher.code(for: "молоко"), PhoneticMatcher.code(for: "малако"))
        XCTAssertTrue(PhoneticMatcher.areSoundAlike("молоко", "малако"))
    }

    func testRussianSoftSignDropped() {
        // дверь / двер differ only by ь, which is dropped.
        XCTAssertEqual(PhoneticMatcher.code(for: "дверь"), PhoneticMatcher.code(for: "двер"))
        XCTAssertTrue(PhoneticMatcher.areSoundAlike("дверь", "двер"))
    }

    func testRussianCaseInsensitive() {
        XCTAssertTrue(PhoneticMatcher.areSoundAlike("Компания", "кампания"))
    }

    // MARK: - RU non-sound-alikes (should NOT learn)

    func testRussianClearlyDifferentRejected() {
        XCTAssertFalse(PhoneticMatcher.areSoundAlike("собака", "работа"))
        XCTAssertFalse(PhoneticMatcher.areSoundAlike("компания", "проект"))
        XCTAssertFalse(PhoneticMatcher.areSoundAlike("молоко", "телефон"))
    }

    func testRussianDistinctCodesForUnrelatedWords() {
        XCTAssertNotEqual(PhoneticMatcher.code(for: "собака"), PhoneticMatcher.code(for: "работа"))
        XCTAssertNotEqual(PhoneticMatcher.code(for: "компания"), PhoneticMatcher.code(for: "телефон"))
    }

    // MARK: - Script handling

    func testRussianDoesNotUseLatinSkeleton() {
        // A Cyrillic token must produce Cyrillic-letter codes only (never Latin
        // Metaphone output). Verify the code contains no ASCII letters.
        let code = PhoneticMatcher.code(for: "компания")
        XCTAssertFalse(code.isEmpty)
        for scalar in code.unicodeScalars {
            let isLatinAscii = (scalar.value >= 0x41 && scalar.value <= 0x5A)
            XCTAssertFalse(isLatinAscii, "Cyrillic code leaked a Latin letter: \(code)")
        }
    }

    func testLatinTokenProducesAsciiCode() {
        let code = PhoneticMatcher.code(for: "kubernetes")
        XCTAssertFalse(code.isEmpty)
        for scalar in code.unicodeScalars {
            // Latin skeleton stays within ASCII (letters + the few digit-symbols
            // used for TH/silent markers).
            XCTAssertLessThanOrEqual(scalar.value, 0x7A)
        }
    }

    func testDigitsAndSymbolsFallBackToSimilarityOnly() {
        // Non-letter tokens get an empty code (no phonetic skeleton).
        XCTAssertEqual(PhoneticMatcher.code(for: "1234"), "")
        XCTAssertEqual(PhoneticMatcher.code(for: "!!!"), "")
        // Two unrelated number strings must NOT be sound-alike despite empty codes
        // (empty codes never match; similarity decides).
        XCTAssertFalse(PhoneticMatcher.areSoundAlike("1234", "5678"))
        // But near-identical numerics still pass on similarity.
        XCTAssertTrue(PhoneticMatcher.areSoundAlike("123456", "123455"))
    }

    func testMixedScriptTieFallsBackToSimilarity() {
        // Equal Latin/Cyrillic letter counts → no dominant script → empty code.
        XCTAssertEqual(PhoneticMatcher.code(for: "ab вг"), "")
    }

    // MARK: - Short-token guard

    func testShortTokensRequireHighSimilarity() {
        // 2-char tokens that merely share a phonetic skeleton are NOT enough;
        // a single-char difference (sim 0.5) must be rejected.
        XCTAssertFalse(PhoneticMatcher.areSoundAlike("go", "no"))
        XCTAssertFalse(PhoneticMatcher.areSoundAlike("aa", "ab"))
        XCTAssertFalse(PhoneticMatcher.areSoundAlike("ат", "от")) // RU, sim 0.5
    }

    func testShortIdenticalTokensStillMatch() {
        // Identical short tokens are trivially sound-alike (sim 1.0 ≥ 0.85).
        XCTAssertTrue(PhoneticMatcher.areSoundAlike("ok", "ok"))
        XCTAssertTrue(PhoneticMatcher.areSoundAlike("OK", "ok"))
        XCTAssertTrue(PhoneticMatcher.areSoundAlike("да", "да"))
    }

    func testEmptyInputsAreNeverSoundAlike() {
        XCTAssertFalse(PhoneticMatcher.areSoundAlike("", ""))
        XCTAssertFalse(PhoneticMatcher.areSoundAlike("figma", ""))
        XCTAssertFalse(PhoneticMatcher.areSoundAlike("   ", "figma"))
    }

    // MARK: - code() determinism

    func testCodeIsDeterministic() {
        let tokens = ["figma", "kubernetes", "компания", "docker", "PHP", "молоко"]
        for token in tokens {
            let first = PhoneticMatcher.code(for: token)
            for _ in 0..<5 {
                XCTAssertEqual(PhoneticMatcher.code(for: token), first)
            }
        }
    }

    func testCodeIsCaseInsensitive() {
        XCTAssertEqual(PhoneticMatcher.code(for: "Kubernetes"), PhoneticMatcher.code(for: "kubernetes"))
        XCTAssertEqual(PhoneticMatcher.code(for: "КОМПАНИЯ"), PhoneticMatcher.code(for: "компания"))
    }

    func testCodeIsWhitespaceTrimmed() {
        XCTAssertEqual(PhoneticMatcher.code(for: "  figma  "), PhoneticMatcher.code(for: "figma"))
    }

    func testCodeEmptyForBlankInput() {
        XCTAssertEqual(PhoneticMatcher.code(for: ""), "")
        XCTAssertEqual(PhoneticMatcher.code(for: "   "), "")
    }

    // MARK: - areSoundAlike via similarity floor (no shared code)

    func testSimilarityFloorAcceptsCloseTypos() {
        // "kubernetes"/"kubernetese" differ by one trailing letter; even if codes
        // diverged, similarity (>= 0.72) catches the mis-hearing.
        XCTAssertTrue(PhoneticMatcher.areSoundAlike("kubernetes", "kubernetese"))
    }
}
