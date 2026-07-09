import XCTest
import WaiComputerKit

final class DictationCopyTests: XCTestCase {
    func testOverlayCopyUsesRussianLanguage() {
        assertRussian(DictationCopy.overlayStatus(.idle, language: .russian))
        assertRussian(DictationCopy.overlayStatus(.connecting, language: .russian))
        assertRussian(DictationCopy.overlayStatus(.listening, language: .russian))
        assertRussian(DictationCopy.overlayStatus(.processing, language: .russian))
        assertRussian(DictationCopy.overlayStatus(.inserting, language: .russian))
    }

    func testPermissionAndRecoveryErrorsUseRussianLanguage() {
        assertRussian(DictationCopy.microphonePermissionDenied(language: .russian))
        assertRussian(DictationCopy.recoveryCopyKept(
            insertionError: "AX error",
            language: .russian
        ))
        assertRussian(DictationCopy.genericInsertionRecovery(language: .russian))
    }

    func testProviderErrorsUseRussianLanguage() {
        let errors: [ProviderError] = [
            .authError(server: nil),
            .quotaExceeded,
            .rateLimited(retryAfterMs: nil),
            .insufficientAudioActivity,
            .sessionTimeLimitExceeded,
            .chunkSizeExceeded,
            .commitThrottled,
            .malformedFrame(rawType: "bad"),
            .unsupportedModel("test-model"),
            .transcriberInternal(message: ""),
            .transcriberInternal(message: "upstream"),
        ]

        for error in errors {
            assertRussian(DictationCopy.providerError(error, language: .russian))
        }
    }

    private func assertRussian(_ value: String, file: StaticString = #filePath, line: UInt = #line) {
        XCTAssertFalse(value.contains("Hands-free"), file: file, line: line)
        XCTAssertFalse(value.contains("Ready"), file: file, line: line)
        XCTAssertFalse(value.contains("Connecting"), file: file, line: line)
        XCTAssertFalse(value.contains("Listening"), file: file, line: line)
        XCTAssertFalse(value.contains("Processing"), file: file, line: line)
        XCTAssertFalse(value.contains("Inserting"), file: file, line: line)
        XCTAssertFalse(value.contains("Microphone permission denied"), file: file, line: line)
        XCTAssertFalse(value.contains("A recovery copy was kept"), file: file, line: line)
        XCTAssertFalse(value.contains("Please try again"), file: file, line: line)
        XCTAssertFalse(value.contains("Без удержания"), file: file, line: line)
        XCTAssertFalse(value.contains("push-to-talk"), file: file, line: line)
        XCTAssertFalse(value.contains("Пост-фильтр"), file: file, line: line)
    }
}
