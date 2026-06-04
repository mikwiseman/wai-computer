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

    private func jsonBody(from request: URLRequest) throws -> [String: Any] {
        let data: Data
        if let httpBody = request.httpBody {
            data = httpBody
        } else if let stream = request.httpBodyStream {
            stream.open()
            defer { stream.close() }
            let buffer = UnsafeMutablePointer<UInt8>.allocate(capacity: 4096)
            defer { buffer.deallocate() }
            let read = stream.read(buffer, maxLength: 4096)
            XCTAssertGreaterThan(read, 0)
            data = Data(bytes: buffer, count: read)
        } else {
            XCTFail("Expected request body")
            throw APIError.noData
        }
        return try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
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
            {"actions":[{"action_id":"a1","chat_id":"c1","tool":"desktop_open","args":{"target":"mailto:a@x.com"},"preview":"Open a new email"}]}
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
        XCTAssertEqual(queue.actions[0].chatId, "c1")
        XCTAssertNil(queue.actions[0].agentId)
        XCTAssertNil(queue.actions[0].agentRunId)
        XCTAssertEqual(queue.actions[0].tool, "desktop_open")
        XCTAssertEqual(queue.actions[0].args["target"], .string("mailto:a@x.com"))
    }

    func testDrainAgentDesktopAction() async throws {
        let client = makeClient()
        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertEqual(request.url?.path, "/api/devices/dev-1/desktop-actions")
            let payload = #"""
            {"actions":[{"action_id":"a1","agent_id":"agent-1","agent_run_id":"run-1","tool":"desktop_open","args":{"target":"mailto:a@x.com"},"preview":"Open a new email"}]}
            """#.data(using: .utf8)!
            return (
                HTTPURLResponse(
                    url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil
                )!,
                payload
            )
        }
        let queue = try await client.drainDesktopActions(deviceId: "dev-1")
        XCTAssertEqual(queue.actions[0].actionId, "a1")
        XCTAssertNil(queue.actions[0].chatId)
        XCTAssertEqual(queue.actions[0].agentId, "agent-1")
        XCTAssertEqual(queue.actions[0].agentRunId, "run-1")
    }

    func testReportDesktopResult() async throws {
        let client = makeClient()
        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(
                request.url?.path,
                "/api/companion/chats/chat-1/actions/a1/desktop_result"
            )
            let json = try self.jsonBody(from: request)
            XCTAssertEqual(json["device_id"] as? String, "dev-1")
            XCTAssertEqual(json["status"] as? String, "executed")
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
            deviceId: "dev-1",
            status: .executed,
            payload: ["ok": .bool(true)]
        )
        XCTAssertEqual(res.actionId, "a1")
        XCTAssertEqual(res.status, "executed")
        XCTAssertNil(res.runStatus)
    }

    func testReportAgentDesktopResult() async throws {
        let client = makeClient()
        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(
                request.url?.path,
                "/api/agents/agent-1/runs/run-1/actions/a1/desktop_result"
            )
            let json = try self.jsonBody(from: request)
            XCTAssertEqual(json["device_id"] as? String, "dev-1")
            XCTAssertEqual(json["status"] as? String, "executed")
            let payload = #"{"action_id":"a1","status":"executed","run_status":"done"}"#.data(using: .utf8)!
            return (
                HTTPURLResponse(
                    url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil
                )!,
                payload
            )
        }
        let res = try await client.reportAgentDesktopResult(
            agentId: "agent-1",
            runId: "run-1",
            actionId: "a1",
            deviceId: "dev-1",
            status: .executed,
            payload: ["ok": .bool(true)]
        )
        XCTAssertEqual(res.actionId, "a1")
        XCTAssertEqual(res.status, "executed")
        XCTAssertEqual(res.runStatus, "done")
    }
}
