import XCTest
@testable import WaiSayKit

final class SentryHelperTests: XCTestCase {
    func testSanitizeDictionaryRedactsSensitiveKeys() {
        let sanitized = SentryHelper.sanitizeDictionary([
            "email": "alice@example.com",
            "password": "secret",
            "query": "Alice comp details",
            "filename": "alice-notes.m4a",
        ])

        XCTAssertEqual(sanitized["password"] as? String, "[redacted-secret]")
        XCTAssertTrue((sanitized["email"] as? String)?.hasPrefix("[redacted-email:") == true)
        XCTAssertTrue((sanitized["query"] as? String)?.hasPrefix("[redacted-text:") == true)
        XCTAssertTrue((sanitized["filename"] as? String)?.hasPrefix("[redacted-filename:") == true)
    }

    func testSanitizeDictionaryRecursesIntoNestedValues() {
        let sanitized = SentryHelper.sanitizeDictionary([
            "nested": [
                "token": "jwt-token",
                "content": "Alice@example.com said hello",
            ],
        ])

        let nested = sanitized["nested"] as? [String: Any]
        XCTAssertEqual(nested?["token"] as? String, "[redacted-secret]")
        XCTAssertTrue((nested?["content"] as? String)?.hasPrefix("[redacted-text:") == true)
    }

    func testSanitizeStringRedactsEmbeddedEmailsInMessages() {
        let sanitized = SentryHelper.sanitizeString(
            "login failed for alice@example.com",
            key: "message"
        )

        XCTAssertFalse(sanitized.contains("alice@example.com"))
        XCTAssertTrue(sanitized.contains("[redacted-email:"))
    }

    func testSanitizeStringRedactsErrorLikeFields() {
        let sanitizedReason = SentryHelper.sanitizeString(
            "Failed to save transcript for alice@example.com: hello world",
            key: "reason"
        )
        let sanitizedError = SentryHelper.sanitizeString(
            "Bearer secret-token for alice@example.com",
            key: "error"
        )

        XCTAssertTrue(sanitizedReason.hasPrefix("[redacted-text:"))
        XCTAssertTrue(sanitizedError.hasPrefix("[redacted-text:"))
    }
}
