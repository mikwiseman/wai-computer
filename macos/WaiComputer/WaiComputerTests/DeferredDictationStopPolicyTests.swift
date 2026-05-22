import XCTest

final class DeferredDictationStopPolicyTests: XCTestCase {
    func testPushToTalkReleaseDuringConnectFinishesAfterReady() {
        XCTAssertEqual(
            DeferredDictationStopPolicy.action(deferredStop: true, isHandsFree: false),
            .finishAfterReady
        )
    }

    func testHandsFreeIgnoresDeferredPushToTalkStop() {
        XCTAssertEqual(
            DeferredDictationStopPolicy.action(deferredStop: true, isHandsFree: true),
            .continueListening
        )
    }

    func testNoDeferredStopContinuesListening() {
        XCTAssertEqual(
            DeferredDictationStopPolicy.action(deferredStop: false, isHandsFree: false),
            .continueListening
        )
    }

    func testFinalizationKeepsShortAudioTailBeforeStoppingCapture() {
        XCTAssertEqual(DictationFinalizationPolicy.captureTailDelay, .milliseconds(450))
    }
}
