import Foundation
import XCTest
@testable import WaiComputerKit

final class TranscriptRenderingTests: XCTestCase {
    private func seg(
        _ content: String,
        speaker: String? = nil,
        rawLabel: String? = nil,
        personId: String? = nil,
        displayName: String? = nil,
        startMs: Int? = nil
    ) -> Segment {
        Segment(
            id: UUID().uuidString,
            speaker: speaker,
            rawLabel: rawLabel,
            personId: personId,
            displayName: displayName,
            content: content,
            startMs: startMs
        )
    }

    // Canonical monologue (the user's complaint): plain output drops labels, so this
    // prose is byte-identical to the backend and web vectors.
    private var monologue: [Segment] {
        [
            seg("Замечания относительно сегодняшней", speaker: "speaker_0", startMs: 0),
            seg("сводки.", speaker: "speaker_0", startMs: 2000),
            seg("Я постараюсь подробно объяснить", speaker: "speaker_0", startMs: 4000),
            seg("причину своих", speaker: "speaker_0", startMs: 7000),
            seg("замечаний,", speaker: "speaker_0", startMs: 9000),
        ]
    }
    private let monologueText =
        "Замечания относительно сегодняшней сводки. " +
        "Я постараюсь подробно объяснить причину своих замечаний,"

    // Dialogue uses assigned display names so the labels match across platforms
    // (raw `speaker_N` numbering renders 0-based on Apple, 1-based on web — pre-existing).
    private var dialogue: [Segment] {
        [
            seg("Hello everyone,", speaker: "speaker_0", displayName: "Alice", startMs: 0),
            seg("welcome to the standup.", speaker: "speaker_0", displayName: "Alice", startMs: 3000),
            seg("Thanks for joining.", speaker: "speaker_1", displayName: "Bob", startMs: 15000),
            seg("Let's review the sprint.", speaker: "speaker_1", displayName: "Bob", startMs: 18000),
            seg("I finished the export feature yesterday.", speaker: "speaker_0", displayName: "Alice", startMs: 30000),
        ]
    }

    func testMonologueCollapsesToSingleTurn() {
        let turns = TranscriptRendering.mergeTurns(monologue, languageCode: "en")
        XCTAssertEqual(turns.count, 1)
        XCTAssertEqual(turns[0].text, monologueText)
        XCTAssertEqual(turns[0].startMs, 0)
        XCTAssertEqual(turns[0].segments.count, 5)
    }

    func testDialogueGroupsConsecutiveSameSpeaker() {
        let turns = TranscriptRendering.mergeTurns(dialogue, languageCode: "en")
        XCTAssertEqual(turns.map(\.speaker), ["Alice", "Bob", "Alice"])
        XCTAssertEqual(turns[0].text, "Hello everyone, welcome to the standup.")
        XCTAssertEqual(turns[1].text, "Thanks for joining. Let's review the sprint.")
    }

    func testOrdersByStartMs() {
        let turns = TranscriptRendering.mergeTurns(
            [seg("second", speaker: "speaker_0", startMs: 1000),
             seg("first", speaker: "speaker_0", startMs: 0)],
            languageCode: "en"
        )
        XCTAssertEqual(turns[0].text, "first second")
    }

    func testSkipsEmptySegments() {
        let turns = TranscriptRendering.mergeTurns(
            [seg("  ", speaker: "speaker_0", startMs: 0),
             seg("real", speaker: "speaker_0", startMs: 1000)],
            languageCode: "en"
        )
        XCTAssertEqual(turns.count, 1)
        XCTAssertEqual(turns[0].text, "real")
    }

    func testUnknownBucketDoesNotMergeWithLabelledSpeaker() {
        let turns = TranscriptRendering.mergeTurns(
            [seg("anon", startMs: 0),
             seg("named", speaker: "speaker_0", startMs: 1000)],
            languageCode: "en"
        )
        XCTAssertEqual(turns.map(\.key), ["", "speaker:0"])
    }

    func testMergesAssignedPersonAcrossDifferingRawLabels() {
        let turns = TranscriptRendering.mergeTurns(
            [seg("Hi", speaker: "speaker_0", personId: "p1", displayName: "Anna", startMs: 0),
             seg("there", speaker: "speaker_5", personId: "p1", displayName: "Anna", startMs: 1000)],
            languageCode: "en"
        )
        XCTAssertEqual(turns.count, 1)
        XCTAssertEqual(turns[0].speaker, "Anna")
        XCTAssertEqual(turns[0].text, "Hi there")
    }

    func testJoinDoesNotSpaceBeforeClosingPunctuation() {
        let turns = TranscriptRendering.mergeTurns(
            [seg("Hello", speaker: "speaker_0", startMs: 0),
             seg(", world", speaker: "speaker_0", startMs: 1000)],
            languageCode: "en"
        )
        XCTAssertEqual(turns[0].text, "Hello, world")
    }

    func testPlainMonologueDropsLabels() {
        let rendered = TranscriptRendering.transcriptText(monologue, style: .plain, languageCode: "en")
        XCTAssertEqual(rendered, monologueText)
    }

    func testPlainDialogueLeadsWithLabel() {
        let rendered = TranscriptRendering.transcriptText(dialogue, style: .plain, languageCode: "en")
        XCTAssertEqual(rendered, """
        Alice: Hello everyone, welcome to the standup.

        Bob: Thanks for joining. Let's review the sprint.

        Alice: I finished the export feature yesterday.
        """)
    }

    func testSpeakersStyleLabelsMonologue() {
        let rendered = TranscriptRendering.transcriptText(monologue, style: .speakers, languageCode: "en")
        XCTAssertEqual(rendered, "Speaker 0: \(monologueText)")
    }

    func testTimestampedMergesOneLinePerTurn() {
        let rendered = TranscriptRendering.transcriptText(dialogue, style: .timestamped, languageCode: "en")
        XCTAssertEqual(rendered, """
        [Alice, 0:00] Hello everyone, welcome to the standup.
        [Bob, 0:15] Thanks for joining. Let's review the sprint.
        [Alice, 0:30] I finished the export feature yesterday.
        """)
    }

    func testTimestampedOmitsMissingTimestamp() {
        let turns = TranscriptRendering.mergeTurns([seg("hi", speaker: "speaker_0")], languageCode: "en")
        XCTAssertEqual(TranscriptRendering.renderTranscript(turns, style: .timestamped), "[Speaker 0] hi")
    }

    func testEmptyTurnsRenderEmptyString() {
        XCTAssertEqual(TranscriptRendering.renderTranscript([], style: .plain), "")
    }

    func testDisplaySegmentCarriesMergedTextAndHeadMetadata() {
        let turns = TranscriptRendering.mergeTurns(
            [seg("Hello", speaker: "speaker_0", rawLabel: "speaker_0", startMs: 0),
             seg("world.", speaker: "speaker_0", rawLabel: "speaker_0", startMs: 1000)],
            languageCode: "en"
        )
        let display = turns[0].displaySegment
        XCTAssertEqual(display.content, "Hello world.")
        XCTAssertEqual(display.startMs, 0)
        XCTAssertEqual(display.rawLabel, "speaker_0")
    }
}

extension TranscriptRenderingTests {
    private func longRun(count: Int) -> [Segment] {
        (0..<count).map { index in
            Segment(
                id: "seg-\(index)",
                speaker: "speaker_0",
                rawLabel: "speaker_0",
                personId: nil,
                displayName: nil,
                content: "Это довольно длинное предложение из живой диктовки.",
                startMs: index * 1_000
            )
        }
    }

    /// Every dictation is one speaker across many segments. That used to merge
    /// into a single turn holding the whole transcript — one `Text` to line-break
    /// before anything paints, and nothing for `List` to recycle.
    func testLongSingleSpeakerRunSplitsIntoBoundedTurns() {
        let turns = TranscriptRendering.mergeTurns(longRun(count: 4_000), languageCode: "ru")

        XCTAssertGreaterThan(turns.count, 120)
        for turn in turns {
            XCTAssertLessThan(turn.text.count, 2_000)
        }
        XCTAssertEqual(turns.reduce(0) { $0 + $1.segments.count }, 4_000)
    }

    /// Splitting must not change how ordinary short runs read.
    func testShortSingleSpeakerRunStillMergesIntoOneTurn() {
        let turns = TranscriptRendering.mergeTurns(longRun(count: 3), languageCode: "ru")

        XCTAssertEqual(turns.count, 1)
        XCTAssertEqual(
            turns.first?.text,
            "Это довольно длинное предложение из живой диктовки. "
                + "Это довольно длинное предложение из живой диктовки. "
                + "Это довольно длинное предложение из живой диктовки."
        )
    }
}
