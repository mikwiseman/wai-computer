import Foundation
import XCTest

@testable import WaiComputerKit

/// Records what it was asked to speak, without any audio — so the controller's
/// ordering/cancel logic is fully testable offline.
final class FakeTTSProvider: TTSProvider, @unchecked Sendable {
    private let lock = NSLock()
    private var _spoken: [String] = []
    private var _stopped = false

    var spoken: [String] {
        lock.lock(); defer { lock.unlock() }
        return _spoken
    }

    var stopped: Bool {
        lock.lock(); defer { lock.unlock() }
        return _stopped
    }

    func speak(_ sentence: String) async {
        lock.lock(); _spoken.append(sentence); lock.unlock()
    }

    func stop() {
        lock.lock(); _stopped = true; lock.unlock()
    }
}

final class ReadAloudTests: XCTestCase {
    func testSegmenterEmitsCompleteSentences() {
        var seg = SentenceSegmenter()
        XCTAssertEqual(seg.feed("Hello world. How are"), ["Hello world."])
        XCTAssertEqual(seg.feed(" you?"), ["How are you?"])
        XCTAssertNil(seg.flush())
    }

    func testSegmenterDoesNotSplitDecimals() {
        var seg = SentenceSegmenter()
        XCTAssertEqual(seg.feed("Pi is 3.14 today. "), ["Pi is 3.14 today."])
    }

    func testSegmenterFlushReturnsTrailingFragment() {
        var seg = SentenceSegmenter()
        XCTAssertEqual(seg.feed("No terminator yet"), [])
        XCTAssertEqual(seg.flush(), "No terminator yet")
    }

    func testSegmenterStrongTerminatorAtEnd() {
        var seg = SentenceSegmenter()
        XCTAssertEqual(seg.feed("Wow!"), ["Wow!"])
    }

    func testControllerSpeaksSentencesInOrder() async {
        let fake = FakeTTSProvider()
        let ctrl = ReadAloudController(provider: fake)
        await ctrl.begin()
        await ctrl.feed("Hi there. Second one!")
        await ctrl.feed(" Trailing bit")
        await ctrl.finish()
        XCTAssertEqual(fake.spoken, ["Hi there.", "Second one!", "Trailing bit"])
    }

    func testControllerCancelStopsAndSuppresses() async {
        let fake = FakeTTSProvider()
        let ctrl = ReadAloudController(provider: fake)
        await ctrl.begin()
        await ctrl.feed("First sentence. ")
        await ctrl.cancel()
        await ctrl.feed("Should not speak. ")
        await ctrl.finish()
        XCTAssertEqual(fake.spoken, ["First sentence."])
        XCTAssertTrue(fake.stopped)
    }
}
