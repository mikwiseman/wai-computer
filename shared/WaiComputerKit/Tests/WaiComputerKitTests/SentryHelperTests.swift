import XCTest
import Sentry
@testable import WaiComputerKit

final class SentryHelperTests: XCTestCase {
    override func setUp() {
        super.setUp()
        SentryHelper.resetCapturedFingerprints()
    }

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

    func testSanitizeStringRedactsEmbeddedCredentialPatternsInMessages() {
        let sanitized = SentryHelper.sanitizeString(
            "POST https://api.telegram.org/bot123456:ABC-SECRET/sendMessage "
            + "Authorization Bearer abcdefghijklmnopqrstuvwxyz123456 "
            + "token=secret "
            + "jwt eyJhbGciOiJIUzI1NiJ9.abcdefghijklmnopqr.abcdefghijklmnopqr",
            key: "message"
        )

        XCTAssertFalse(sanitized.contains("123456:ABC-SECRET"))
        XCTAssertFalse(sanitized.contains("Bearer abcdefghijklmnopqrstuvwxyz123456"))
        XCTAssertFalse(sanitized.contains("token=secret"))
        XCTAssertFalse(sanitized.contains("eyJhbGciOiJIUzI1NiJ9"))
        XCTAssertTrue(sanitized.contains("bot[redacted-token]"))
        XCTAssertTrue(sanitized.contains("Bearer [redacted-token]"))
        XCTAssertTrue(sanitized.contains("token=[redacted-secret]"))
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

    func testSanitizeEventForSentryRedactsRequestUserAndBreadcrumbs() {
        let event = Event(level: .warning)
        event.message = SentryMessage(formatted: "login failed for alice@example.com")
        event.extra = [
            "query": "Alice comp details",
            "Authorization": "Bearer abcdefghijklmnopqrstuvwxyz123456",
        ]

        let user = Sentry.User(userId: "user-1")
        user.email = "alice@example.com"
        user.username = "alice"
        user.ipAddress = "203.0.113.10"
        user.data = ["email": "alice@example.com"]
        event.user = user

        let request = SentryRequest()
        request.url = "https://wai.computer/api/search?q=alice@example.com&token=secret"
        request.queryString = "q=alice@example.com&token=secret"
        request.cookies = "session=secret"
        request.headers = [
            "Authorization": "Bearer abcdefghijklmnopqrstuvwxyz123456",
            "Cookie": "session=secret",
            "Accept": "application/json",
        ]
        event.request = request

        let breadcrumb = Breadcrumb(level: .info, category: "search")
        breadcrumb.message = "query alice@example.com"
        breadcrumb.data = ["query": "Alice comp details"]
        event.breadcrumbs = [breadcrumb]

        let sanitized = SentryHelper.sanitizeEventForSentry(event)

        XCTAssertTrue(sanitized.message?.formatted.contains("[redacted-email:") == true)
        XCTAssertTrue((sanitized.extra?["query"] as? String)?.hasPrefix("[redacted-text:") == true)
        XCTAssertEqual(sanitized.extra?["Authorization"] as? String, "[redacted-secret]")
        XCTAssertEqual(sanitized.user?.userId, "user-1")
        XCTAssertNil(sanitized.user?.email)
        XCTAssertNil(sanitized.user?.username)
        XCTAssertNil(sanitized.user?.ipAddress)
        XCTAssertTrue((sanitized.user?.data?["email"] as? String)?.hasPrefix("[redacted-email:") == true)
        XCTAssertEqual(sanitized.request?.url, "https://wai.computer/api/search")
        XCTAssertNil(sanitized.request?.queryString)
        XCTAssertNil(sanitized.request?.cookies)
        XCTAssertEqual(sanitized.request?.headers?["Authorization"], "[redacted-secret]")
        XCTAssertEqual(sanitized.request?.headers?["Cookie"], "[redacted-secret]")
        XCTAssertEqual(sanitized.request?.headers?["Accept"], "application/json")
        XCTAssertTrue(sanitized.breadcrumbs?.first?.message?.contains("[redacted-email:") == true)
        XCTAssertTrue(
            (sanitized.breadcrumbs?.first?.data?["query"] as? String)?
                .hasPrefix("[redacted-text:") == true
        )
    }

    func testNormalizedRequestPathCollapsesDynamicIdentifiers() {
        let normalized = SentryHelper.normalizedRequestPath(
            "/api/recordings/123E4567-E89B-12D3-A456-426614174000/upload"
        )

        XCTAssertEqual(normalized, "/api/recordings/:id/upload")
    }

    func testNormalizedRequestPathKeepsStaticGenerateSummarySegment() {
        let normalized = SentryHelper.normalizedRequestPath(
            "/api/recordings/123E4567-E89B-12D3-A456-426614174000/generate-summary"
        )

        XCTAssertEqual(normalized, "/api/recordings/:id/generate-summary")
    }

    func testShouldCaptureFingerprintOnlyOnce() {
        XCTAssertTrue(SentryHelper.shouldCaptureFingerprint("request:POST:/api/recordings/:id/upload:http_502"))
        XCTAssertFalse(SentryHelper.shouldCaptureFingerprint("request:POST:/api/recordings/:id/upload:http_502"))
    }

    func testShouldCaptureFingerprintAgainAfterDedupWindowExpires() {
        let fingerprint = "request:POST:/api/recordings/:id/upload:http_502"
        let start = Date(timeIntervalSince1970: 1_700_000_000)

        XCTAssertTrue(SentryHelper.shouldCaptureFingerprint(fingerprint, now: start))
        XCTAssertFalse(
            SentryHelper.shouldCaptureFingerprint(
                fingerprint,
                now: start.addingTimeInterval(60)
            )
        )
        XCTAssertTrue(
            SentryHelper.shouldCaptureFingerprint(
                fingerprint,
                now: start.addingTimeInterval(SentryHelper.fingerprintDedupWindow + 1)
            )
        )
    }
}
