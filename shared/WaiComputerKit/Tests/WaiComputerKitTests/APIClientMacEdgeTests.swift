import Foundation
import XCTest

@testable import WaiComputerKit

final class APIClientMacEdgeTests: XCTestCase {
    override func setUp() {
        super.setUp()
        MockURLProtocol.requestHandler = nil
    }

    private func makeClient() -> APIClient {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [MockURLProtocol.self]
        let session = URLSession(configuration: config)
        return APIClient(
            baseURL: URL(string: "https://api.example.com")!, session: session
        )
    }

    func testDeviceHeartbeat() async throws {
        let client = makeClient()
        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/api/devices/heartbeat")
            let payload = #"{"device_id":"dev-1","online":true}"#.data(using: .utf8)!
            return (
                HTTPURLResponse(
                    url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil
                )!,
                payload
            )
        }
        let res = try await client.deviceHeartbeat(platform: "macos", name: "My Mac")
        XCTAssertEqual(res.deviceId, "dev-1")
        XCTAssertTrue(res.online)
    }

    func testDrainDesktopActions() async throws {
        let client = makeClient()
        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertEqual(request.url?.path, "/api/devices/dev-1/desktop-actions")
            let payload = #"""
            {"actions":[{"action_id":"a1","tool":"desktop_open","args":{"target":"mailto:a@x.com"},"preview":"Open a new email"}]}
            """#.data(using: .utf8)!
            return (
                HTTPURLResponse(
                    url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil
                )!,
                payload
            )
        }
        let queue = try await client.drainDesktopActions(deviceId: "dev-1")
        XCTAssertEqual(queue.actions.count, 1)
        XCTAssertEqual(queue.actions[0].actionId, "a1")
        XCTAssertEqual(queue.actions[0].tool, "desktop_open")
        XCTAssertEqual(queue.actions[0].args["target"], .string("mailto:a@x.com"))
    }

    func testReportDesktopResult() async throws {
        let client = makeClient()
        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(
                request.url?.path,
                "/api/companion/chats/chat-1/actions/a1/desktop_result"
            )
            let payload = #"{"action_id":"a1","status":"executed"}"#.data(using: .utf8)!
            return (
                HTTPURLResponse(
                    url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil
                )!,
                payload
            )
        }
        let res = try await client.reportDesktopResult(
            chatId: "chat-1",
            actionId: "a1",
            status: .executed,
            payload: ["ok": .bool(true)]
        )
        XCTAssertEqual(res.actionId, "a1")
        XCTAssertEqual(res.status, "executed")
    }
}
