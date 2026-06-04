import Foundation
import XCTest
import WaiComputerKit

@MainActor
final class MacAgentsViewModelTests: XCTestCase {
    override func setUp() {
        super.setUp()
        MacAgentsMockURLProtocol.requestHandler = nil
    }

    func testAgentWorkflowLoadsRunsApprovalsAndReminders() async throws {
        let recorder = RequestRecorder()
        let client = makeClient(recorder: recorder)
        let model = MacAgentsViewModel(apiClient: client)

        await model.load()

        XCTAssertEqual(model.agents.first?.name, "Daily")
        XCTAssertEqual(model.actions.first?.tool, "desktop_open")
        XCTAssertEqual(model.reminders.first?.text, "Check launch metrics")

        await model.createAgent(name: "Daily check", note: "Write launch notes")
        await model.startRun(agent: try XCTUnwrap(model.agents.first), objective: "Check launch")
        await model.resolve(action: try XCTUnwrap(model.actions.first), decision: .once)
        await model.createReminder(text: "Review launch", dueAt: Date(timeIntervalSince1970: 1_780_597_800))
        await model.cancel(reminder: try XCTUnwrap(model.reminders.first))

        XCTAssertNil(model.errorMessage)
        XCTAssertEqual(model.statusMessage, "Reminder cancelled.")
        XCTAssertEqual(
            recorder.values(),
            [
                "GET /api/agents",
                "GET /api/agents/runs",
                "GET /api/agents/actions",
                "GET /api/reminders",
                "POST /api/agents",
                "GET /api/agents",
                "GET /api/agents/runs",
                "GET /api/agents/actions",
                "GET /api/reminders",
                "POST /api/agents/agent-1/runs",
                "GET /api/agents",
                "GET /api/agents/runs",
                "GET /api/agents/actions",
                "GET /api/reminders",
                "POST /api/agents/agent-1/runs/run-1/actions/action-1/resolve",
                "GET /api/agents",
                "GET /api/agents/runs",
                "GET /api/agents/actions",
                "GET /api/reminders",
                "POST /api/reminders",
                "GET /api/agents",
                "GET /api/agents/runs",
                "GET /api/agents/actions",
                "GET /api/reminders",
                "POST /api/reminders/reminder-1/cancel",
                "GET /api/agents",
                "GET /api/agents/runs",
                "GET /api/agents/actions",
                "GET /api/reminders"
            ]
        )
    }

    private func makeClient(recorder: RequestRecorder) -> APIClient {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [MacAgentsMockURLProtocol.self]
        let session = URLSession(configuration: config)
        MacAgentsMockURLProtocol.requestHandler = { [self] request in
            recorder.append("\(request.httpMethod ?? "") \(request.url?.path ?? "")")
            return try response(for: request)
        }
        return APIClient(baseURL: URL(string: "https://api.example.com")!, session: session)
    }

    private func response(for request: URLRequest) throws -> (HTTPURLResponse, Data) {
        let path = request.url?.path ?? ""
        let method = request.httpMethod ?? ""
        let response = HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!

        if path == "/api/agents", method == "GET" {
            return (response, Data("""
            {"agents":[{"id":"agent-1","name":"Daily","kind":"mac","trigger_type":"manual","config":{},"autonomy":"propose","enabled":true,"next_run_at":null,"last_run_at":null,"created_at":"2026-06-04T12:00:00Z","updated_at":"2026-06-04T12:00:00Z"}]}
            """.utf8))
        }

        if path == "/api/agents", method == "POST" {
            let body = try jsonBody(from: request)
            let name = try XCTUnwrap(body["name"] as? String)
            XCTAssertEqual(name, "Daily check")
            XCTAssertEqual(body["kind"] as? String, "mac")
            let config = try XCTUnwrap(body["config"] as? [String: Any])
            let steps = try XCTUnwrap(config["steps"] as? [[String: Any]])
            XCTAssertEqual(steps.first?["tool"] as? String, "note")
            let args = try XCTUnwrap(steps.first?["args"] as? [String: Any])
            XCTAssertEqual(args["text"] as? String, "Write launch notes")
            return (response, Data("""
            {"id":"agent-1","name":"\(name)","kind":"mac","trigger_type":"manual","config":{},"autonomy":"propose","enabled":true,"next_run_at":null,"last_run_at":null,"created_at":"2026-06-04T12:00:00Z","updated_at":"2026-06-04T12:00:00Z"}
            """.utf8))
        }

        if path == "/api/agents/runs", method == "GET" {
            return (response, Data("""
            {"runs":[{"id":"run-1","agent_id":"agent-1","trigger_key":"manual:agent-1:mac","trigger_kind":"manual","trigger_payload":{"objective":"Check launch"},"status":"pending","plan":null,"done_spec":null,"result":null,"content_hash":null,"error":null,"next_step_idx":0,"heartbeat_at":null,"started_at":null,"finished_at":null,"cancel_requested_at":null,"created_at":"2026-06-04T12:00:00Z","updated_at":"2026-06-04T12:00:00Z"}]}
            """.utf8))
        }

        if path == "/api/agents/agent-1/runs", method == "POST" {
            let body = try jsonBody(from: request)
            XCTAssertEqual(body["trigger_kind"] as? String, "manual")
            let objective = try XCTUnwrap((body["trigger_payload"] as? [String: Any])?["objective"] as? String)
            XCTAssertEqual(objective, "Check launch")
            XCTAssertTrue((body["idempotency_key"] as? String)?.hasPrefix("mac:") == true)
            return (response, Data("""
            {"id":"run-1","agent_id":"agent-1","trigger_key":"manual:agent-1:mac","trigger_kind":"manual","trigger_payload":{"objective":"\(objective)"},"status":"pending","plan":null,"done_spec":null,"result":null,"content_hash":null,"error":null,"next_step_idx":0,"heartbeat_at":null,"started_at":null,"finished_at":null,"cancel_requested_at":null,"created_at":"2026-06-04T12:00:00Z","updated_at":"2026-06-04T12:00:00Z"}
            """.utf8))
        }

        if path == "/api/agents/actions", method == "GET" {
            return (response, Data("""
            {"actions":[{"id":"action-1","agent_id":"agent-1","run_id":"run-1","step_idx":1,"kind":"approval","tool":"desktop_open","status":"pending","preview":"Open Mail","recipient":null,"expires_at":"2026-06-04T12:15:00Z","resolved_at":null,"receipt":null}]}
            """.utf8))
        }

        if path == "/api/agents/agent-1/runs/run-1/actions/action-1/resolve", method == "POST" {
            let body = try jsonBody(from: request)
            XCTAssertEqual(body["decision"] as? String, "once")
            return (response, Data(#"{"action_id":"action-1","status":"executed","run_status":"done","recipient":null}"#.utf8))
        }

        if path == "/api/reminders", method == "GET" {
            return (response, Data("""
            {"reminders":[{"id":"reminder-1","text":"Check launch metrics","due_at":"2026-06-04T18:30:00Z","status":"pending","source":"mac","source_ref":null,"sent_at":null,"failed_at":null,"error":null,"metadata":{},"created_at":"2026-06-04T12:00:00Z","updated_at":"2026-06-04T12:00:00Z"}]}
            """.utf8))
        }

        if path == "/api/reminders", method == "POST" {
            let body = try jsonBody(from: request)
            XCTAssertEqual(body["text"] as? String, "Review launch")
            XCTAssertEqual(body["source"] as? String, "mac")
            XCTAssertEqual((body["metadata"] as? [String: Any])?["origin"] as? String, "mac_agents")
            return (response, Data("""
            {"id":"reminder-1","text":"Review launch","due_at":"2026-06-04T18:30:00Z","status":"pending","source":"mac","source_ref":null,"sent_at":null,"failed_at":null,"error":null,"metadata":{},"created_at":"2026-06-04T12:00:00Z","updated_at":"2026-06-04T12:00:00Z"}
            """.utf8))
        }

        if path == "/api/reminders/reminder-1/cancel", method == "POST" {
            return (response, Data("""
            {"id":"reminder-1","text":"Check launch metrics","due_at":"2026-06-04T18:30:00Z","status":"cancelled","source":"mac","source_ref":null,"sent_at":null,"failed_at":null,"error":null,"metadata":{},"created_at":"2026-06-04T12:00:00Z","updated_at":"2026-06-04T12:01:00Z"}
            """.utf8))
        }

        XCTFail("Unhandled request \(method) \(path)")
        return (HTTPURLResponse(url: request.url!, statusCode: 404, httpVersion: nil, headerFields: nil)!, Data())
    }

    private func jsonBody(from request: URLRequest) throws -> [String: Any] {
        let data: Data
        if let httpBody = request.httpBody {
            data = httpBody
        } else if let stream = request.httpBodyStream {
            stream.open()
            defer { stream.close() }
            let buffer = UnsafeMutablePointer<UInt8>.allocate(capacity: 8192)
            defer { buffer.deallocate() }
            let read = stream.read(buffer, maxLength: 8192)
            data = Data(bytes: buffer, count: read)
        } else {
            XCTFail("Expected request body")
            throw APIError.noData
        }
        return try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
    }
}

private final class RequestRecorder: @unchecked Sendable {
    private let lock = NSLock()
    private var requests: [String] = []

    func append(_ value: String) {
        lock.lock()
        requests.append(value)
        lock.unlock()
    }

    func values() -> [String] {
        lock.lock()
        defer { lock.unlock() }
        return requests
    }
}

private final class MacAgentsMockURLProtocol: URLProtocol, @unchecked Sendable {
    static var requestHandler: ((URLRequest) throws -> (HTTPURLResponse, Data))?

    override class func canInit(with request: URLRequest) -> Bool {
        true
    }

    override class func canonicalRequest(for request: URLRequest) -> URLRequest {
        request
    }

    override func startLoading() {
        guard let handler = Self.requestHandler else {
            client?.urlProtocol(self, didFailWithError: APIError.noData)
            return
        }

        do {
            let (response, data) = try handler(request)
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        } catch {
            client?.urlProtocol(self, didFailWithError: error)
        }
    }

    override func stopLoading() {}
}
