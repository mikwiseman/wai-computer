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

    func testCleanupDisabledUsesRawTranscript() throws {
        let text = try DictationCleanupPolicy.textToInsert(
            rawText: "raw transcript",
            cleanupEnabled: false,
            cleanedText: nil,
            cleanupError: nil
        )

        XCTAssertEqual(text, "raw transcript")
    }

    func testCleanupEnabledUsesCleanedTranscript() throws {
        let text = try DictationCleanupPolicy.textToInsert(
            rawText: "raw transcript",
            cleanupEnabled: true,
            cleanedText: "Cleaned transcript.",
            cleanupError: nil
        )

        XCTAssertEqual(text, "Cleaned transcript.")
    }

    func testCleanupEnabledFailureAbortsInsteadOfUsingRawTranscript() {
        XCTAssertThrowsError(
            try DictationCleanupPolicy.textToInsert(
                rawText: "raw transcript",
                cleanupEnabled: true,
                cleanedText: nil,
                cleanupError: URLError(.cannotConnectToHost)
            )
        ) { error in
            XCTAssertEqual((error as? URLError)?.code, .cannotConnectToHost)
        }
    }

    func testCleanupEnabledBlankResultAbortsInsteadOfInsertingEmptyText() {
        XCTAssertThrowsError(
            try DictationCleanupPolicy.textToInsert(
                rawText: "raw transcript",
                cleanupEnabled: true,
                cleanedText: "   ",
                cleanupError: nil
            )
        )
    }
}
