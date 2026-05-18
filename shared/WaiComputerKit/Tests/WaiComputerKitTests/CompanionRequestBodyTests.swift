import Foundation
import XCTest
@testable import WaiComputerKit

/// Verifies that `streamCompanionMessage` includes per-turn working memory
/// (date / timezone / viewing context) in the POST body so the server-side
/// agent can resolve relative time words like "yesterday" / "вчера".
final class CompanionRequestBodyTests: XCTestCase {
    override func setUp() {
        super.setUp()
        MockURLProtocol.requestHandler = nil
    }

    private func makeClient() -> APIClient {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [MockURLProtocol.self]
        let session = URLSession(configuration: config)
        return APIClient(
            baseURL: URL(string: "https://api.example.com")!,
            session: session
        )
    }

    private func bodyData(from request: URLRequest) -> Data? {
        if let data = request.httpBody { return data }
        if let stream = request.httpBodyStream {
            stream.open()
            defer { stream.close() }
            var data = Data()
            let buffer = UnsafeMutablePointer<UInt8>.allocate(capacity: 4096)
            defer { buffer.deallocate() }
            while stream.hasBytesAvailable {
                let read = stream.read(buffer, maxLength: 4096)
                if read <= 0 { break }
                data.append(buffer, count: read)
            }
            return data
        }
        return nil
    }

    /// Construct a Date for the given wall-clock components interpreted in the
    /// given timezone. Avoids epoch-second magic numbers in tests.
    private func date(
        year: Int, month: Int, day: Int,
        hour: Int = 0, minute: Int = 0,
        in tz: TimeZone
    ) -> Date {
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = tz
        let components = DateComponents(
            year: year, month: month, day: day, hour: hour, minute: minute
        )
        return cal.date(from: components)!
    }

    func testStreamCompanionMessageEncodesDateAndTimezone() async throws {
        let client = makeClient()
        let captured = CapturedBody()

        MockURLProtocol.requestHandler = { [self] request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(
                request.url?.path,
                "/api/companion/chats/chat-1/messages"
            )
            XCTAssertEqual(
                request.value(forHTTPHeaderField: "Accept"),
                "text/event-stream"
            )
            captured.data = self.bodyData(from: request)
            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: ["Content-Type": "text/event-stream"]
            )!
            let body = "event: done\ndata: {\"message_id\":\"m1\"}\n\n"
            return (response, body.data(using: .utf8)!)
        }

        // Asia/Tokyo at noon local time — comfortably mid-day, so the
        // date won't roll over and the IANA identifier survives Foundation
        // canonicalization (verified vs Foundation rewriting "UTC" → "GMT").
        let tokyo = TimeZone(identifier: "Asia/Tokyo")!
        let fixedNow = date(
            year: 2026, month: 5, day: 18, hour: 12, minute: 0, in: tokyo
        )

        let stream = try await client.streamCompanionMessage(
            chatId: "chat-1",
            content: "О чем говорили вчера",
            viewingRecordingId: "rec-7",
            viewingFolderId: nil,
            now: fixedNow,
            timeZone: tokyo,
            calendar: Calendar(identifier: .gregorian)
        )
        for await _ in stream { /* drain */ }

        guard let data = captured.data else {
            XCTFail("expected captured request body")
            return
        }
        let json = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        XCTAssertEqual(json?["content"] as? String, "О чем говорили вчера")
        XCTAssertEqual(json?["client_local_date"] as? String, "2026-05-18")
        XCTAssertEqual(json?["client_timezone"] as? String, "Asia/Tokyo")
        XCTAssertEqual(json?["viewing_recording_id"] as? String, "rec-7")
        XCTAssertNil(json?["viewing_folder_id"] as? String)
    }

    func testStreamCompanionMessageDateRespectsLocalTimezoneRollover() async throws {
        // 2026-05-18 23:30 UTC → 2026-05-19 08:30 in Asia/Tokyo (UTC+9).
        // The body must carry Tokyo's local calendar date.
        let client = makeClient()
        let captured = CapturedBody()
        MockURLProtocol.requestHandler = { [self] request in
            captured.data = self.bodyData(from: request)
            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: ["Content-Type": "text/event-stream"]
            )!
            let body = "event: done\ndata: {}\n\n"
            return (response, body.data(using: .utf8)!)
        }

        let utc = TimeZone(identifier: "UTC")!
        let tokyo = TimeZone(identifier: "Asia/Tokyo")!
        let fixedNow = date(
            year: 2026, month: 5, day: 18, hour: 23, minute: 30, in: utc
        )

        let stream = try await client.streamCompanionMessage(
            chatId: "chat-1",
            content: "hi",
            now: fixedNow,
            timeZone: tokyo,
            calendar: Calendar(identifier: .gregorian)
        )
        for await _ in stream { /* drain */ }

        guard let data = captured.data else {
            XCTFail("expected captured request body")
            return
        }
        let json = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        XCTAssertEqual(json?["client_local_date"] as? String, "2026-05-19")
        XCTAssertEqual(json?["client_timezone"] as? String, "Asia/Tokyo")
    }
}

private final class CapturedBody: @unchecked Sendable {
    var data: Data?
}
