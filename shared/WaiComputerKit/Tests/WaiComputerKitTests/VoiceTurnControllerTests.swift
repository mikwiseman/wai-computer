import Foundation
import XCTest

@testable import WaiComputerKit

private final class SpyTTS: TTSProvider, @unchecked Sendable {
    var spoken: [String] = []
    var stopCount = 0
    func speak(_ sentence: String) async { spoken.append(sentence) }
    func stop() { stopCount += 1 }
}

private final class StateLog: @unchecked Sendable {
    var states: [VoiceTurnState] = []
    func record(_ s: VoiceTurnState) { states.append(s) }
}

final class VoiceTurnControllerTests: XCTestCase {
    private func make() -> (SpyTTS, StateLog, VoiceTurnController) {
        let tts = SpyTTS()
        let log = StateLog()
        let controller = VoiceTurnController(
            readAloud: ReadAloudController(provider: tts),
            onState: { [log] state in log.record(state) }
        )
        return (tts, log, controller)
    }

    func testHappyPathSpeaksResponseAndReturnsIdle() async {
        let (tts, log, controller) = make()
        let turn = await controller.beginListening()
        let ready = await controller.transcriptReady(turn: turn)
        XCTAssertTrue(ready)
        await controller.appendResponse("Hello. ", turn: turn)
        await controller.appendResponse("World!", turn: turn)
        await controller.completeResponse(turn: turn)

        let state = await controller.state
        XCTAssertEqual(state, .idle)
        XCTAssertEqual(tts.spoken, ["Hello.", "World!"])
        XCTAssertEqual(log.states, [.listening, .thinking, .speaking, .idle])
    }

    func testStaleDeltaFromSupersededTurnIsDropped() async {
        let (tts, _, controller) = make()
        let first = await controller.beginListening()
        let second = await controller.beginListening()  // user re-pressed
        XCTAssertNotEqual(first, second)
        // A delta tagged with the old turn must not be spoken.
        await controller.appendResponse("ghost.", turn: first)
        XCTAssertTrue(tts.spoken.isEmpty)
    }

    func testBargeInDuringSpeakingCancelsAndStartsFreshTurn() async {
        let (tts, _, controller) = make()
        let turn = await controller.beginListening()
        _ = await controller.transcriptReady(turn: turn)
        // Strong terminator so the sentence is spoken immediately (a trailing
        // period would be held by the segmenter awaiting more input).
        await controller.appendResponse("Reading this aloud!", turn: turn)
        XCTAssertEqual(tts.spoken, ["Reading this aloud!"])

        // User barges in mid-read.
        let newTurn = await controller.beginListening()
        XCTAssertEqual(tts.stopCount, 1)
        let afterBargeIn = await controller.state
        XCTAssertEqual(afterBargeIn, .listening)
        // The superseded turn's completion is ignored.
        await controller.completeResponse(turn: turn)
        let stillListening = await controller.state
        XCTAssertEqual(stillListening, .listening)
        XCTAssertGreaterThan(newTurn, turn)
    }

    func testTranscriptReadyIgnoresStaleTurn() async {
        let (_, _, controller) = make()
        _ = await controller.beginListening()
        let ready = await controller.transcriptReady(turn: 999)
        XCTAssertFalse(ready)
        let state = await controller.state
        XCTAssertEqual(state, .listening)
    }

    func testCompleteWithNoDeltasReturnsIdleSilently() async {
        let (tts, log, controller) = make()
        let turn = await controller.beginListening()
        _ = await controller.transcriptReady(turn: turn)
        await controller.completeResponse(turn: turn)
        let state = await controller.state
        XCTAssertEqual(state, .idle)
        XCTAssertTrue(tts.spoken.isEmpty)
        XCTAssertEqual(log.states, [.listening, .thinking, .idle])
    }

    func testAbortCancelsReadAndReturnsIdle() async {
        let (tts, _, controller) = make()
        let turn = await controller.beginListening()
        _ = await controller.transcriptReady(turn: turn)
        await controller.appendResponse("Partial.", turn: turn)
        await controller.abort(turn: turn)
        XCTAssertEqual(tts.stopCount, 1)
        let state = await controller.state
        XCTAssertEqual(state, .idle)
    }
}
