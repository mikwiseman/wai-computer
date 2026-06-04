import Foundation
import XCTest
@testable import WaiComputerKit

private final class NewEndpointRequestPathRecorder: @unchecked Sendable {
    private let lock = NSLock()
    private var paths: [String] = []

    func append(_ path: String) {
        lock.lock()
        defer { lock.unlock() }
        paths.append(path)
    }

    var snapshot: [String] {
        lock.lock()
        defer { lock.unlock() }
        return paths
    }
}

final class APIClientNewEndpointsTests: XCTestCase {
    override func setUp() {
        super.setUp()
        MockURLProtocol.requestHandler = nil
    }

    private func makeClient(baseURL: URL = URL(string: "https://api.example.com")!) -> APIClient {
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [MockURLProtocol.self]
        let session = URLSession(configuration: config)
        return APIClient(baseURL: baseURL, session: session)
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

    private final class RequestPathRecorder: @unchecked Sendable {
        private let lock = NSLock()
        private var paths: [String] = []

        func append(_ path: String) {
            lock.lock()
            paths.append(path)
            lock.unlock()
        }

        func values() -> [String] {
            lock.lock()
            defer { lock.unlock() }
            return paths
        }
    }

    // MARK: - System & Self-hosting

    func testGetSystemInfoUsesSystemEndpoint() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertEqual(request.url?.path, "/api/system/info")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {
              "app_name": "WaiComputer",
              "deployment_mode": "wai_cloud",
              "public_base_url": "https://wai.computer",
              "cloud_base_url": "https://wai.computer",
              "mcp_url": "https://wai.computer/mcp",
              "git_sha": null,
              "git_dirty": false,
              "audio_retention_policy": "delete_after_processing",
              "self_hosting_available": true,
              "billing_mode": "cloud"
            }
            """.data(using: .utf8)!
            return (response, payload)
        }

        let info = try await client.getSystemInfo()

        XCTAssertEqual(info.deploymentMode, .waiCloud)
        XCTAssertEqual(info.publicBaseURL, "https://wai.computer")
        XCTAssertTrue(info.selfHostingAvailable)
    }

    func testStartSelfHostProvisionSendsOptionalDomainAndPassword() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { [self] request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/api/self-host/provision")

            let body = try jsonBody(from: request)
            XCTAssertEqual(body["vps_ip"] as? String, "203.0.113.10")
            XCTAssertEqual(body["ssh_username"] as? String, "root")
            XCTAssertEqual(body["auth_method"] as? String, "password")
            XCTAssertEqual(body["ssh_password"] as? String, "temporary-bootstrap-password")
            XCTAssertFalse(body.keys.contains("hostname"))

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 202,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {
              "job_id": "selfhost_demo",
              "status": "manual_review_required",
              "hostname": null,
              "vps_ip": "203.0.113.10",
              "message": "Provisioning inputs are valid.",
              "steps": [
                {
                  "id": "validate_inputs",
                  "label": "Validate VPS address and SSH access",
                  "status": "manual_review_required"
                }
              ]
            }
            """.data(using: .utf8)!
            return (response, payload)
        }

        let result = try await client.startSelfHostProvision(
            SelfHostProvisionRequest(
                hostname: nil,
                vpsIP: "203.0.113.10",
                sshUsername: "root",
                authMethod: .password,
                sshPublicKey: nil,
                sshPassword: "temporary-bootstrap-password"
            )
        )

        XCTAssertNil(result.hostname)
        XCTAssertEqual(result.vpsIP, "203.0.113.10")
        XCTAssertEqual(result.steps.first?.label, "Validate VPS address and SSH access")
    }

    func testGetSelfHostMigrationContractUsesContractEndpoint() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertEqual(request.url?.path, "/api/self-host/migration/contract")
            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {
              "schema_version": "2026-06-03",
              "archive_format": "wai-self-host-export-v1",
              "requires_same_alembic_head": true,
              "preserve_user_ids": true,
              "collision_policy": "reject",
              "secret_policy": "reconnect_or_bring_your_own",
              "owned_exportable": {"tables": [{"table":"agents"}], "artifacts": []},
              "reconnect_required": {"tables": [], "artifacts": []},
              "server_local": {"tables": [], "artifacts": []},
              "excluded": {"tables": [], "artifacts": []}
            }
            """.data(using: .utf8)!
            return (response, payload)
        }

        let contract = try await client.getSelfHostMigrationContract()

        XCTAssertEqual(contract.schemaVersion, "2026-06-03")
        XCTAssertEqual(contract.archiveFormat, "wai-self-host-export-v1")
        XCTAssertEqual(contract.ownedExportable.tables.first?["table"]?.stringValue, "agents")
    }

    func testAgentControlPlaneEndpoints() async throws {
        let client = makeClient()
        let seenPaths = RequestPathRecorder()
        let nextRunAt = try XCTUnwrap(
            ISO8601DateFormatter().date(from: "2026-06-04T08:15:00Z")
        )

        MockURLProtocol.requestHandler = { [self] request in
            seenPaths.append(request.url?.path ?? "")
            let path = request.url?.path ?? ""
            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: path == "/api/agents/agent-1" && request.httpMethod == "DELETE" ? 204 : 200,
                httpVersion: nil,
                headerFields: nil
            )!

            if path == "/api/agents/capabilities" {
                let payload = """
                {
                  "schema_version": "2026-06-04",
                  "deployment_mode": "wai_cloud",
                  "max_steps": 20,
                  "runtime_modes": [{"id":"wai_cloud","label":"Wai Cloud","description":"cloud","available":true}],
                  "capabilities": [{
                    "id": "wai.search",
                    "label": "Search Wai data",
                    "category": "memory",
                    "description": "Search",
                    "availability": "available",
                    "runtime_tool": "search_wai",
                    "surfaces": ["web", "mac", "telegram"],
                    "requires_approval": false,
                    "cloud_supported": true,
                    "self_host_supported": true,
                    "local_gateway_required": false,
                    "risk_level": "read_only",
                    "permission_scopes": ["search:read"],
                    "safety_notes": "Read-only"
                  }],
                  "tool_contracts": [{
                    "name": "search_wai",
                    "capability_id": "wai.search",
                    "kind": "runtime",
                    "description": "Search",
                    "side_effect": "none",
                    "requires_approval": false,
                    "args_schema": {"type":"object"},
                    "result_schema": {"type":"object"},
                    "permission_scopes": ["search:read"]
                  }]
                }
                """.data(using: .utf8)!
                return (response, payload)
            }

            if path == "/api/agents" && request.httpMethod == "GET" {
                let payload = """
                {"agents":[{"id":"agent-1","name":"Daily","kind":"brief","trigger_type":"manual","config":{},"autonomy":"propose","enabled":true,"next_run_at":null,"last_run_at":null,"created_at":"2026-06-03T12:00:00Z","updated_at":"2026-06-03T12:00:00Z"}]}
                """.data(using: .utf8)!
                return (response, payload)
            }

            if path == "/api/agents" && request.httpMethod == "POST" {
                let body = try jsonBody(from: request)
                XCTAssertEqual(body["name"] as? String, "Daily")
                XCTAssertEqual(body["next_run_at"] as? String, "2026-06-04T08:15:00Z")
                let payload = """
                {"id":"agent-1","name":"Daily","kind":"brief","trigger_type":"manual","config":{},"autonomy":"propose","enabled":true,"next_run_at":null,"last_run_at":null,"created_at":"2026-06-03T12:00:00Z","updated_at":"2026-06-03T12:00:00Z"}
                """.data(using: .utf8)!
                return (response, payload)
            }

            if path == "/api/agents/agent-1/runs" && request.httpMethod == "POST" {
                let body = try jsonBody(from: request)
                XCTAssertEqual(body["idempotency_key"] as? String, "same")
                let payload = """
                {"id":"run-1","agent_id":"agent-1","parent_run_id":null,"parent_step_idx":null,"trigger_key":"manual:agent-1:same","trigger_kind":"manual","trigger_payload":{"objective":"brief"},"status":"pending","plan":null,"done_spec":null,"result":null,"content_hash":null,"error":null,"next_step_idx":0,"heartbeat_at":null,"started_at":null,"finished_at":null,"cancel_requested_at":null,"created_at":"2026-06-03T12:00:00Z","updated_at":"2026-06-03T12:00:00Z"}
                """.data(using: .utf8)!
                return (response, payload)
            }

            if path == "/api/agents/agent-1/runs" && request.httpMethod == "GET" {
                return (response, #"{"runs":[]}"#.data(using: .utf8)!)
            }

            if path == "/api/agents/actions" && request.httpMethod == "GET" {
                XCTAssertEqual(request.url?.query, "status=pending&limit=3")
                let payload = """
                {"actions":[{"id":"action-1","agent_id":"agent-1","run_id":"run-1","step_idx":2,"kind":"approval","tool":"desktop_open","status":"pending","preview":"Open Mail","recipient":null,"expires_at":"2026-06-03T12:15:00Z","resolved_at":null,"receipt":null}]}
                """.data(using: .utf8)!
                return (response, payload)
            }

            if path == "/api/agents/agent-1/runs/run-1/actions/action-1/resolve" {
                let body = try jsonBody(from: request)
                XCTAssertEqual(body["decision"] as? String, "once")
                return (response, #"{"action_id":"action-1","status":"executed","run_status":"done","recipient":"you"}"#.data(using: .utf8)!)
            }

            if path == "/api/agents/agent-1" && request.httpMethod == "DELETE" {
                return (response, Data())
            }

            return (response, Data("{}".utf8))
        }

        let caps = try await client.getAgentCapabilities()
        XCTAssertEqual(caps.capabilities.first?.id, "wai.search")
        XCTAssertEqual(caps.capabilities.first?.permissionScopes, ["search:read"])
        XCTAssertEqual(caps.toolContracts.first?.name, "search_wai")
        let agents = try await client.listAgents(limit: 10)
        XCTAssertEqual(agents.agents.first?.name, "Daily")
        let created = try await client.createAgent(
            AgentCreateRequest(name: "Daily", kind: "brief", nextRunAt: nextRunAt)
        )
        XCTAssertEqual(created.id, "agent-1")
        let run = try await client.startAgentRun(
            agentId: "agent-1",
            StartAgentRunRequest(
                triggerKind: .manual,
                triggerPayload: ["objective": .string("brief")],
                idempotencyKey: "same"
            )
        )
        XCTAssertEqual(run.id, "run-1")
        _ = try await client.listAgentRuns(agentId: "agent-1", status: "pending", limit: 5)
        let actions = try await client.listAgentActions(status: "pending", limit: 3)
        XCTAssertEqual(actions.actions.first?.agentId, "agent-1")
        let resolved = try await client.resolveAgentAction(
            agentId: "agent-1",
            runId: "run-1",
            actionId: "action-1",
            ResolveAgentActionRequest(decision: "once")
        )
        XCTAssertEqual(resolved.runStatus, "done")
        try await client.deleteAgent(agentId: "agent-1")

        XCTAssertEqual(
            seenPaths.values(),
            [
                "/api/agents/capabilities",
                "/api/agents",
                "/api/agents",
                "/api/agents/agent-1/runs",
                "/api/agents/agent-1/runs",
                "/api/agents/actions",
                "/api/agents/agent-1/runs/run-1/actions/action-1/resolve",
                "/api/agents/agent-1"
            ]
        )
    }

    func testReminderEndpoints() async throws {
        let client = makeClient()
        let seenPaths = RequestPathRecorder()

        MockURLProtocol.requestHandler = { [self] request in
            let path = request.url?.path ?? ""
            seenPaths.append(path)
            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: path.hasSuffix("/cancel") ? 200 : 200,
                httpVersion: nil,
                headerFields: nil
            )!

            if path == "/api/reminders" && request.httpMethod == "GET" {
                XCTAssertEqual(request.url?.query, "status=pending&limit=5")
                let payload = """
                {"reminders":[{"id":"reminder-1","text":"Check launch metrics","due_at":"2026-06-04T18:30:00Z","status":"pending","source":"web","source_ref":null,"sent_at":null,"failed_at":null,"error":null,"metadata":{"origin":"dashboard"},"created_at":"2026-06-04T12:00:00Z","updated_at":"2026-06-04T12:00:00Z"}]}
                """.data(using: .utf8)!
                return (response, payload)
            }

            if path == "/api/reminders" && request.httpMethod == "POST" {
                let body = try jsonBody(from: request)
                XCTAssertEqual(body["text"] as? String, "Check launch metrics")
                XCTAssertEqual(body["due_at"] as? String, "2026-06-04T18:30:00Z")
                XCTAssertEqual(body["source"] as? String, "mac")
                let payload = """
                {"id":"reminder-1","text":"Check launch metrics","due_at":"2026-06-04T18:30:00Z","status":"pending","source":"mac","source_ref":null,"sent_at":null,"failed_at":null,"error":null,"metadata":{},"created_at":"2026-06-04T12:00:00Z","updated_at":"2026-06-04T12:00:00Z"}
                """.data(using: .utf8)!
                return (response, payload)
            }

            if path == "/api/reminders/reminder-1/cancel" && request.httpMethod == "POST" {
                let payload = """
                {"id":"reminder-1","text":"Check launch metrics","due_at":"2026-06-04T18:30:00Z","status":"cancelled","source":"mac","source_ref":null,"sent_at":null,"failed_at":null,"error":null,"metadata":{},"created_at":"2026-06-04T12:00:00Z","updated_at":"2026-06-04T12:01:00Z"}
                """.data(using: .utf8)!
                return (response, payload)
            }

            return (response, Data("{}".utf8))
        }

        let reminders = try await client.listReminders(status: "pending", limit: 5)
        XCTAssertEqual(reminders.reminders.first?.metadata["origin"]?.stringValue, "dashboard")

        let dueAt = Date(timeIntervalSince1970: 1_780_597_800)
        let created = try await client.createReminder(
            ReminderCreateRequest(text: "Check launch metrics", dueAt: dueAt)
        )
        XCTAssertEqual(created.source, "mac")

        let cancelled = try await client.cancelReminder(reminderId: "reminder-1")
        XCTAssertEqual(cancelled.status, "cancelled")

        XCTAssertEqual(
            seenPaths.values(),
            [
                "/api/reminders",
                "/api/reminders",
                "/api/reminders/reminder-1/cancel"
            ]
        )
    }

    // MARK: - WaiBrain Spaces

    func testBrainSpaceEndpointsUseCanonicalSpaceRoutes() async throws {
        let client = makeClient()
        let seenPaths = RequestPathRecorder()

        MockURLProtocol.requestHandler = { [self] request in
            seenPaths.append(request.url?.path ?? "")
            let path = request.url?.path ?? ""
            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: path == "/api/brain/spaces" && request.httpMethod == "POST" ? 201 : 200,
                httpVersion: nil,
                headerFields: nil
            )!

            if path == "/api/brain/spaces" && request.httpMethod == "GET" {
                let payload = """
                {"spaces":[{"id":"space-1","owner_user_id":"user-1","name":"Wai School","slug":"wai-school","kind":"work","engine_profile":"waibrain","visibility":"private","description":null,"metadata":{},"role":"owner","created_at":"2026-06-04T09:00:00Z","updated_at":"2026-06-04T09:00:00Z"}]}
                """.data(using: .utf8)!
                return (response, payload)
            }

            if path == "/api/brain/spaces" && request.httpMethod == "POST" {
                let body = try jsonBody(from: request)
                XCTAssertEqual(body["name"] as? String, "Wai School")
                XCTAssertEqual(body["engine_profile"] as? String, "waibrain")
                let payload = """
                {"id":"space-1","owner_user_id":"user-1","name":"Wai School","slug":"wai-school","kind":"work","engine_profile":"waibrain","visibility":"private","description":null,"metadata":{},"role":"owner","created_at":"2026-06-04T09:00:00Z","updated_at":"2026-06-04T09:00:00Z"}
                """.data(using: .utf8)!
                return (response, payload)
            }

            if path == "/api/brain/spaces/space-1/home" {
                let payload = """
                {"space":{"id":"space-1","owner_user_id":"user-1","name":"Wai School","slug":"wai-school","kind":"work","engine_profile":"waibrain","visibility":"private","description":null,"metadata":{},"role":"owner","created_at":"2026-06-04T09:00:00Z","updated_at":"2026-06-04T09:00:00Z"},"page_count":1,"source_count":1,"claim_counts":{"workflow_rule":1},"source_counts":{"item":1},"pending_review_count":1,"recent_pages":[{"id":"page-1","space_id":"space-1","title":"Customer stage rules","slug":"customer-stage-rules","kind":"workflow","status":"active","markdown":"---\\nwai_type: brain_page\\n---","frontmatter":{},"version":1,"claims":[{"id":"claim-1","space_id":"space-1","page_id":"page-1","kind":"workflow_rule","status":"active","text":"Use 40 minute intro sessions.","confidence":0.9,"authority":"self","salience":null,"evidence":[],"source_refs":[],"metadata":{}}],"created_at":"2026-06-04T09:00:00Z","updated_at":"2026-06-04T09:00:00Z"}],"engine_profiles":["waibrain","obsidian","gbrain","mempalace"]}
                """.data(using: .utf8)!
                return (response, payload)
            }

            if path == "/api/brain/spaces/space-1/pages" && request.httpMethod == "GET" {
                let payload = """
                {"pages":[{"id":"page-1","space_id":"space-1","title":"Customer stage rules","slug":"customer-stage-rules","kind":"workflow","status":"active","markdown":"body","frontmatter":{},"version":1,"claims":[],"created_at":null,"updated_at":null}]}
                """.data(using: .utf8)!
                return (response, payload)
            }

            if path == "/api/brain/spaces/space-1/pages" && request.httpMethod == "POST" {
                let body = try jsonBody(from: request)
                XCTAssertEqual(body["title"] as? String, "Customer stage rules")
                let payload = """
                {"id":"page-1","space_id":"space-1","title":"Customer stage rules","slug":"customer-stage-rules","kind":"workflow","status":"active","markdown":"body","frontmatter":{},"version":1,"claims":[],"created_at":null,"updated_at":null}
                """.data(using: .utf8)!
                return (response, payload)
            }

            if path == "/api/brain/spaces/space-1/review-packs" {
                XCTAssertEqual(request.url?.query, "status=pending")
                let payload = """
                {"review_packs":[{"id":"pack-1","space_id":"space-1","kind":"bridge","risk":"medium","status":"pending","title":"Bridge","summary":"Review customer rules.","proposals":[],"evidence":[],"created_by_user_id":"user-1","decided_by_user_id":null,"decision_reason":null,"created_at":"2026-06-04T09:00:00Z","decided_at":null}],"pending_count":1}
                """.data(using: .utf8)!
                return (response, payload)
            }

            if path == "/api/brain/spaces/space-1/review-packs/pack-1/accept" {
                let payload = """
                {"id":"pack-1","space_id":"space-1","kind":"bridge","risk":"medium","status":"accepted","title":"Bridge","summary":"Review customer rules.","proposals":[],"evidence":[],"created_by_user_id":"user-1","decided_by_user_id":"user-1","decision_reason":null,"created_at":"2026-06-04T09:00:00Z","decided_at":"2026-06-04T09:01:00Z"}
                """.data(using: .utf8)!
                return (response, payload)
            }

            if path == "/api/brain/spaces/space-1/review-packs/pack-1/reject" {
                let body = try jsonBody(from: request)
                XCTAssertEqual(body["reason"] as? String, "wrong space")
                let payload = """
                {"id":"pack-1","space_id":"space-1","kind":"bridge","risk":"medium","status":"rejected","title":"Bridge","summary":"Review customer rules.","proposals":[],"evidence":[],"created_by_user_id":"user-1","decided_by_user_id":"user-1","decision_reason":"wrong space","created_at":"2026-06-04T09:00:00Z","decided_at":"2026-06-04T09:01:00Z"}
                """.data(using: .utf8)!
                return (response, payload)
            }

            if path == "/api/brain/spaces/space-1/match" {
                let body = try jsonBody(from: request)
                XCTAssertEqual(body["other_space_id"] as? String, "space-2")
                let payload = """
                {"id":"pack-2","space_id":"space-1","kind":"bridge","risk":"medium","status":"pending","title":"Bridge","summary":"Matched space.","proposals":[],"evidence":[],"created_by_user_id":"user-1","decided_by_user_id":null,"decision_reason":null,"created_at":"2026-06-04T09:00:00Z","decided_at":null}
                """.data(using: .utf8)!
                return (response, payload)
            }

            if path == "/api/brain/spaces/space-1/context" {
                let body = try jsonBody(from: request)
                XCTAssertEqual(body["task"] as? String, "Write a parent call script.")
                let payload = """
                {"space":{"id":"space-1","owner_user_id":"user-1","name":"Wai School","slug":"wai-school","kind":"work","engine_profile":"waibrain","visibility":"private","description":null,"metadata":{},"role":"owner","created_at":null,"updated_at":null},"markdown":"# Wai School\\n\\nUse 40 minute intro sessions.","claim_count":1}
                """.data(using: .utf8)!
                return (response, payload)
            }

            if path == "/api/brain/spaces/space-1/export" {
                XCTAssertEqual(request.url?.query, "profile=obsidian")
                let payload = """
                {"space":{"id":"space-1","owner_user_id":"user-1","name":"Wai School","slug":"wai-school","kind":"work","engine_profile":"waibrain","visibility":"private","description":null,"metadata":{},"role":"owner","created_at":null,"updated_at":null},"profile":"obsidian","files":[{"path":"Customer stage rules.md","markdown":"body"}]}
                """.data(using: .utf8)!
                return (response, payload)
            }

            return (response, Data("{}".utf8))
        }

        let spaces = try await client.listBrainSpaces()
        XCTAssertEqual(spaces.spaces.first?.name, "Wai School")

        let created = try await client.createBrainSpace(
            BrainSpaceCreateRequest(name: "Wai School", kind: "work", engineProfile: "waibrain")
        )
        XCTAssertEqual(created.slug, "wai-school")

        let home = try await client.getBrainSpaceHome(spaceId: "space-1")
        XCTAssertEqual(home.recentPages.first?.claims.first?.text, "Use 40 minute intro sessions.")

        let pages = try await client.listBrainSpacePages(spaceId: "space-1")
        XCTAssertEqual(pages.pages.first?.title, "Customer stage rules")

        let createdPage = try await client.createBrainSpacePage(
            spaceId: "space-1",
            BrainSpacePageCreateRequest(title: "Customer stage rules", kind: "workflow")
        )
        XCTAssertEqual(createdPage.slug, "customer-stage-rules")

        let review = try await client.listBrainReviewPacks(spaceId: "space-1")
        XCTAssertEqual(review.pendingCount, 1)

        let accepted = try await client.acceptBrainReviewPack(spaceId: "space-1", packId: "pack-1")
        XCTAssertEqual(accepted.status, "accepted")

        let rejected = try await client.rejectBrainReviewPack(
            spaceId: "space-1",
            packId: "pack-1",
            reason: "wrong space"
        )
        XCTAssertEqual(rejected.decisionReason, "wrong space")

        let matched = try await client.matchBrainSpaces(spaceId: "space-1", otherSpaceId: "space-2")
        XCTAssertEqual(matched.id, "pack-2")

        let context = try await client.buildBrainContext(
            spaceId: "space-1",
            task: "Write a parent call script.",
            limit: 40
        )
        XCTAssertEqual(context.claimCount, 1)

        let exported = try await client.exportBrainSpace(spaceId: "space-1", profile: "obsidian")
        XCTAssertEqual(exported.files.first?.path, "Customer stage rules.md")

        XCTAssertEqual(
            seenPaths.values(),
            [
                "/api/brain/spaces",
                "/api/brain/spaces",
                "/api/brain/spaces/space-1/home",
                "/api/brain/spaces/space-1/pages",
                "/api/brain/spaces/space-1/pages",
                "/api/brain/spaces/space-1/review-packs",
                "/api/brain/spaces/space-1/review-packs/pack-1/accept",
                "/api/brain/spaces/space-1/review-packs/pack-1/reject",
                "/api/brain/spaces/space-1/match",
                "/api/brain/spaces/space-1/context",
                "/api/brain/spaces/space-1/export"
            ]
        )
    }

    // MARK: - Recordings

    func testStartSummaryGenerationUsesDurableEndpoint() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/api/recordings/rec-1/summary-generation")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 202,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {
              "job_id": "job-1",
              "recording_id": "rec-1",
              "status": "queued",
              "stage": "queued",
              "progress_percent": 5,
              "message": "Summary generation is queued.",
              "requested_at": "2026-05-27T09:00:00Z",
              "started_at": null,
              "completed_at": null,
              "failed_at": null,
              "error_code": null,
              "error_message": null
            }
            """.data(using: .utf8)!
            return (response, payload)
        }

        let state = try await client.startSummaryGeneration(recordingId: "rec-1")

        XCTAssertEqual(state.jobId, "job-1")
        XCTAssertEqual(state.recordingId, "rec-1")
        XCTAssertEqual(state.status, "queued")
        XCTAssertEqual(state.progressPercent, 5)
        XCTAssertTrue(state.isActive)
    }

    func testGetSummaryGenerationUsesDurableEndpoint() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertEqual(request.url?.path, "/api/recordings/rec-1/summary-generation")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {
              "job_id": "job-1",
              "recording_id": "rec-1",
              "status": "failed",
              "stage": "failed",
              "progress_percent": 100,
              "message": "Summary generation failed.",
              "requested_at": "2026-05-27T09:00:00Z",
              "started_at": "2026-05-27T09:00:02Z",
              "completed_at": null,
              "failed_at": "2026-05-27T09:00:05Z",
              "error_code": "summarization_failed",
              "error_message": "We couldn't generate the summary right now. Please try again."
            }
            """.data(using: .utf8)!
            return (response, payload)
        }

        let state = try await client.getSummaryGeneration(recordingId: "rec-1")

        XCTAssertEqual(state.jobId, "job-1")
        XCTAssertEqual(state.status, "failed")
        XCTAssertEqual(state.errorCode, "summarization_failed")
        XCTAssertTrue(state.isFailed)
    }

    func testRecordingSummaryAudioEndpointsUseDurableAudioPaths() async throws {
        let client = makeClient()
        let seenPaths = NewEndpointRequestPathRecorder()

        MockURLProtocol.requestHandler = { request in
            seenPaths.append(request.url?.path ?? "")
            let isFile = request.url?.path.hasSuffix("/file") == true
            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: isFile ? 200 : 202,
                httpVersion: nil,
                headerFields: ["Content-Type": isFile ? "audio/mpeg" : "application/json"]
            )!
            if isFile {
                return (response, Data("ID3".utf8))
            }
            let payload = """
            {
              "artifact_id": "audio-1",
              "source_kind": "recording",
              "source_id": "rec-1",
              "status": "queued",
              "stage": "queued",
              "progress_percent": 5,
              "message": "Summary audio generation is queued.",
              "provider": "xai",
              "model": "xai-text-to-speech",
              "voice_id": "ara",
              "language": "auto",
              "content_type": null,
              "byte_size": null,
              "duration_seconds": null,
              "audio_url": null,
              "requested_at": "2026-06-04T09:00:00Z",
              "started_at": null,
              "completed_at": null,
              "failed_at": null,
              "error_code": null,
              "error_message": null
            }
            """.data(using: .utf8)!
            return (response, payload)
        }

        let state = try await client.startRecordingSummaryAudio(recordingId: "rec-1")
        _ = try await client.getRecordingSummaryAudio(recordingId: "rec-1")
        let audio = try await client.downloadRecordingSummaryAudio(recordingId: "rec-1")

        XCTAssertEqual(state.artifactId, "audio-1")
        XCTAssertEqual(state.sourceKind, "recording")
        XCTAssertEqual(state.voiceId, "ara")
        XCTAssertTrue(state.isActive)
        XCTAssertEqual(audio, Data("ID3".utf8))
        XCTAssertEqual(seenPaths.snapshot, [
            "/api/recordings/rec-1/summary/audio",
            "/api/recordings/rec-1/summary/audio",
            "/api/recordings/rec-1/summary/audio/file"
        ])
    }

    func testItemSummaryAudioEndpointsUseDurableAudioPaths() async throws {
        let client = makeClient()
        let seenPaths = NewEndpointRequestPathRecorder()

        MockURLProtocol.requestHandler = { request in
            seenPaths.append(request.url?.path ?? "")
            let isFile = request.url?.path.hasSuffix("/file") == true
            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: isFile ? 200 : 202,
                httpVersion: nil,
                headerFields: ["Content-Type": isFile ? "audio/mpeg" : "application/json"]
            )!
            if isFile {
                return (response, Data("ID3".utf8))
            }
            let payload = """
            {
              "artifact_id": "audio-1",
              "source_kind": "item",
              "source_id": "item-1",
              "status": "succeeded",
              "stage": "complete",
              "progress_percent": 100,
              "message": "Summary audio is ready.",
              "provider": "xai",
              "model": "xai-text-to-speech",
              "voice_id": "ara",
              "language": "auto",
              "content_type": "audio/mpeg",
              "byte_size": 3,
              "duration_seconds": null,
              "audio_url": "/api/items/item-1/summary/audio/file",
              "requested_at": "2026-06-04T09:00:00Z",
              "started_at": "2026-06-04T09:00:01Z",
              "completed_at": "2026-06-04T09:00:02Z",
              "failed_at": null,
              "error_code": null,
              "error_message": null
            }
            """.data(using: .utf8)!
            return (response, payload)
        }

        let state = try await client.startItemSummaryAudio(itemId: "item-1")
        _ = try await client.getItemSummaryAudio(itemId: "item-1")
        let audio = try await client.downloadItemSummaryAudio(itemId: "item-1")

        XCTAssertEqual(state.artifactId, "audio-1")
        XCTAssertEqual(state.sourceKind, "item")
        XCTAssertEqual(state.audioUrl, "/api/items/item-1/summary/audio/file")
        XCTAssertFalse(state.isActive)
        XCTAssertEqual(audio, Data("ID3".utf8))
        XCTAssertEqual(seenPaths.snapshot, [
            "/api/items/item-1/summary/audio",
            "/api/items/item-1/summary/audio",
            "/api/items/item-1/summary/audio/file"
        ])
    }

    // MARK: - Companion

    func testPatchCompanionChatSendsRenameBody() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { [self] request in
            XCTAssertEqual(request.httpMethod, "PATCH")
            XCTAssertEqual(request.url?.path, "/api/companion/chats/chat-1")

            let body = try jsonBody(from: request)
            XCTAssertEqual(body["title"] as? String, "Roadmap follow-ups")
            XCTAssertNil(body["scope"] as? [String: Any])
            XCTAssertNil(body["pinned"] as? Bool)
            XCTAssertNil(body["archived"] as? Bool)

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {"id":"chat-1","title":"Roadmap follow-ups","scope":null,"pinned_at":null,
             "last_message_at":null,"archived_at":null,
             "created_at":"2026-05-18T09:00:00Z","updated_at":"2026-05-18T09:00:00Z"}
            """.data(using: .utf8)!
            return (response, payload)
        }

        let chat = try await client.patchCompanionChat(
            chatId: "chat-1",
            title: "Roadmap follow-ups"
        )
        XCTAssertEqual(chat.title, "Roadmap follow-ups")
    }

    func testDeleteCompanionChatUsesDeleteEndpoint() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "DELETE")
            XCTAssertEqual(request.url?.path, "/api/companion/chats/chat-1")
            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 204,
                httpVersion: nil,
                headerFields: nil
            )!
            return (response, Data())
        }

        try await client.deleteCompanionChat(chatId: "chat-1")
    }

    // MARK: - Billing

    func testCreateBillingCheckoutSendsExplicitTinkoffProvider() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { [self] request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/api/billing/checkout")

            let body = try jsonBody(from: request)
            XCTAssertEqual(body["plan"] as? String, "pro")
            XCTAssertEqual(body["period"] as? String, "month")
            XCTAssertEqual(body["provider"] as? String, "tinkoff")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {
              "provider": "tinkoff",
              "checkout_url": "https://securepay.tinkoff.ru/test-checkout"
            }
            """.data(using: .utf8)!
            return (response, payload)
        }

        let checkout = try await client.createBillingCheckout(
            plan: "pro",
            period: "month",
            provider: "tinkoff"
        )

        XCTAssertEqual(checkout.provider, "tinkoff")
        XCTAssertEqual(checkout.checkoutUrl, "https://securepay.tinkoff.ru/test-checkout")
    }

    func testCreateBillingCheckoutSendsPromoCodeWhenProvided() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { [self] request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/api/billing/checkout")

            let body = try jsonBody(from: request)
            XCTAssertEqual(body["plan"] as? String, "pro")
            XCTAssertEqual(body["period"] as? String, "year")
            XCTAssertEqual(body["provider"] as? String, "stripe")
            XCTAssertEqual(body["promo_code"] as? String, "TESTSALE")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {
              "provider": "stripe",
              "checkout_url": "https://checkout.stripe.test/session"
            }
            """.data(using: .utf8)!
            return (response, payload)
        }

        let checkout = try await client.createBillingCheckout(
            plan: "pro",
            period: "year",
            provider: "stripe",
            promoCode: "TESTSALE"
        )

        XCTAssertEqual(checkout.provider, "stripe")
        XCTAssertEqual(checkout.checkoutUrl, "https://checkout.stripe.test/session")
    }

    func testClaimBillingPromoCodeSendsCodeAndDecodesSubscription() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { [self] request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/api/billing/promo/claim")

            let body = try jsonBody(from: request)
            XCTAssertEqual(body["code"] as? String, "WAI-TEST-30")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {
              "plan": {
                "code": "pro",
                "name": "Pro",
                "description": null,
                "usd_amount_monthly": 12,
                "usd_amount_yearly": 96,
                "rub_amount_monthly": 999,
                "rub_amount_yearly": 7999,
                "word_cap_per_week": null,
                "memory_retention_days": null,
                "features": {
                  "billing": true
                }
              },
              "status": "active",
              "provider": "promo",
              "billing_period": "month",
              "current_period_end": "2026-06-21T12:00:00Z",
              "cancel_at_period_end": true,
              "trial_end": null,
              "enforcement_enabled": true
            }
            """.data(using: .utf8)!
            return (response, payload)
        }

        let subscription = try await client.claimBillingPromoCode("WAI-TEST-30")

        XCTAssertTrue(subscription.isPro)
        XCTAssertEqual(subscription.provider, "promo")
        XCTAssertTrue(subscription.cancelAtPeriodEnd)
    }

    func testGetBillingSubscriptionDecodesActiveTinkoffProStatus() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertEqual(request.url?.path, "/api/billing/subscription")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {
              "plan": {
                "code": "pro",
                "name": "Pro",
                "description": null,
                "usd_amount_monthly": 12,
                "usd_amount_yearly": 96,
                "rub_amount_monthly": 999,
                "rub_amount_yearly": 7999,
                "word_cap_per_week": null,
                "memory_retention_days": null,
                "features": {
                  "billing": true
                }
              },
              "status": "active",
              "provider": "tinkoff",
              "billing_period": "month",
              "current_period_end": "2026-06-21T12:00:00Z",
              "cancel_at_period_end": false,
              "trial_end": null,
              "enforcement_enabled": true
            }
            """.data(using: .utf8)!
            return (response, payload)
        }

        let subscription = try await client.getBillingSubscription()

        XCTAssertTrue(subscription.isPro)
        XCTAssertEqual(subscription.status, "active")
        XCTAssertEqual(subscription.provider, "tinkoff")
        XCTAssertEqual(subscription.billingPeriod, "month")
        XCTAssertTrue(subscription.enforcementEnabled)
    }

    // MARK: - Star Recording

    func testStarRecordingSendsPostToCorrectPath() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/api/recordings/rec-42/star")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {
                "id":"rec-42",
                "title":"Starred Recording",
                "type":"note",
                "starred_at":"2026-03-15T12:00:00Z",
                "created_at":"2026-03-01T10:00:00Z"
            }
            """.data(using: .utf8)!
            return (response, payload)
        }

        let recording = try await client.starRecording(id: "rec-42")
        XCTAssertEqual(recording.id, "rec-42")
        XCTAssertEqual(recording.title, "Starred Recording")
        XCTAssertNotNil(recording.starredAt)
    }

    func testStarRecordingReturnsUpdatedRecordingWithStarredAt() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {
                "id":"rec-7",
                "title":"Meeting Notes",
                "type":"meeting",
                "starred_at":"2026-03-17T08:30:00Z",
                "created_at":"2026-03-10T09:00:00Z"
            }
            """.data(using: .utf8)!
            return (response, payload)
        }

        let recording = try await client.starRecording(id: "rec-7")
        XCTAssertEqual(recording.type, .meeting)
        XCTAssertNotNil(recording.starredAt)
    }

    // MARK: - Unstar Recording

    func testUnstarRecordingSendsDeleteToCorrectPath() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "DELETE")
            XCTAssertEqual(request.url?.path, "/api/recordings/rec-42/star")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {
                "id":"rec-42",
                "title":"Unstarred Recording",
                "type":"note",
                "starred_at":null,
                "created_at":"2026-03-01T10:00:00Z"
            }
            """.data(using: .utf8)!
            return (response, payload)
        }

        let recording = try await client.unstarRecording(id: "rec-42")
        XCTAssertEqual(recording.id, "rec-42")
        XCTAssertNil(recording.starredAt)
    }

    func testUnstarRecordingClearsStarredAtField() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "DELETE")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {
                "id":"rec-99",
                "title":"Was Starred",
                "type":"reflection",
                "created_at":"2026-02-20T14:00:00Z"
            }
            """.data(using: .utf8)!
            return (response, payload)
        }

        let recording = try await client.unstarRecording(id: "rec-99")
        XCTAssertEqual(recording.type, .reflection)
        XCTAssertNil(recording.starredAt)
    }

    // MARK: - List Starred Recordings

    func testListStarredRecordingsSendsGetWithStarredQueryParam() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "GET")
            XCTAssertEqual(request.url?.path, "/api/recordings")
            let query = request.url?.query ?? ""
            XCTAssertTrue(query.contains("starred=true"),
                          "Expected starred=true in query, got: \(query)")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            [
                {
                    "id":"rec-1",
                    "title":"Fav 1",
                    "type":"note",
                    "starred_at":"2026-03-15T12:00:00Z",
                    "created_at":"2026-03-01T10:00:00Z"
                },
                {
                    "id":"rec-2",
                    "title":"Fav 2",
                    "type":"meeting",
                    "starred_at":"2026-03-16T09:00:00Z",
                    "created_at":"2026-03-02T11:00:00Z"
                }
            ]
            """.data(using: .utf8)!
            return (response, payload)
        }

        let recordings = try await client.listStarredRecordings()
        XCTAssertEqual(recordings.count, 2)
        XCTAssertEqual(recordings[0].id, "rec-1")
        XCTAssertNotNil(recordings[0].starredAt)
        XCTAssertEqual(recordings[1].id, "rec-2")
        XCTAssertNotNil(recordings[1].starredAt)
    }

    func testListStarredRecordingsReturnsEmptyArrayWhenNoneStarred() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertTrue(request.url?.query?.contains("starred=true") == true)

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            return (response, Data("[]".utf8))
        }

        let recordings = try await client.listStarredRecordings()
        XCTAssertTrue(recordings.isEmpty)
    }

    // MARK: - Pin Chat Session



    // MARK: - Unpin Chat Session



    // MARK: - Search Chat Sessions




    // MARK: - Export Chat Session




    // MARK: - Delete Action Item

    func testDeleteActionItemSendsDeleteToCorrectPath() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "DELETE")
            XCTAssertEqual(request.url?.path, "/api/action-items/ai-55")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 204,
                httpVersion: nil,
                headerFields: nil
            )!
            return (response, Data())
        }

        try await client.deleteActionItem(id: "ai-55")
    }

    func testDeleteActionItemDoesNotIncludeRequestBody() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "DELETE")
            XCTAssertEqual(request.url?.path, "/api/action-items/ai-99")

            // Verify no request body is sent
            let bodyData: Data?
            if let data = request.httpBody {
                bodyData = data
            } else if let stream = request.httpBodyStream {
                stream.open()
                defer { stream.close() }
                let buffer = UnsafeMutablePointer<UInt8>.allocate(capacity: 1024)
                defer { buffer.deallocate() }
                let read = stream.read(buffer, maxLength: 1024)
                bodyData = read > 0 ? Data(bytes: buffer, count: read) : nil
            } else {
                bodyData = nil
            }
            XCTAssertNil(bodyData, "DELETE action item should not send a body")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 204,
                httpVersion: nil,
                headerFields: nil
            )!
            return (response, Data())
        }

        try await client.deleteActionItem(id: "ai-99")
    }

    func testDeleteActionItemThrowsOn404() async {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 404,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {"detail":"Action item not found"}
            """.data(using: .utf8)!
            return (response, payload)
        }

        do {
            try await client.deleteActionItem(id: "ai-nonexistent")
            XCTFail("Expected httpError for 404")
        } catch let error as APIError {
            switch error {
            case .httpError(let statusCode, _):
                XCTAssertEqual(statusCode, 404)
            default:
                XCTFail("Expected httpError(404), got \(error)")
            }
        } catch {
            XCTFail("Expected APIError, got \(error)")
        }
    }

    // MARK: - Realtime Transcription

    func testCreateRealtimeTranscriptionSessionSendsLanguageAndChannels() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/api/transcription/session")

            let body = try self.jsonBody(from: request)
            XCTAssertEqual(body["language"] as? String, "multi")
            XCTAssertEqual(body["channels"] as? Int, 1)
            XCTAssertEqual(body["purpose"] as? String, "recording")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {
                "provider":"deepgram",
                "token":"dg_token_123",
                "expires_in_seconds":60,
                "sample_rate":16000,
                "audio_format":"linear16",
                "language":"multi",
                "channels":1,
                "model":"nova-3",
                "websocket_url":"wss://wai.computer/api/transcription/stream",
                "auth_scheme":"bearer",
                "keep_alive_interval_seconds":4
            }
            """.data(using: .utf8)!
            return (response, payload)
        }

        let config = try await client.createRealtimeTranscriptionSession(language: "multi", channels: 1)
        XCTAssertEqual(config.provider, "deepgram")
        XCTAssertEqual(config.token, "dg_token_123")
        XCTAssertEqual(config.sampleRate, 16_000)
        XCTAssertEqual(config.model, "nova-3")
        XCTAssertEqual(config.websocketURL, "wss://wai.computer/api/transcription/stream")
        XCTAssertEqual(config.authScheme, "bearer")
        XCTAssertEqual(config.keepAliveIntervalSeconds, 4)
    }

    func testCreateRealtimeTranscriptionSessionSendsDictationPurpose() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/api/transcription/session")

            let body = try self.jsonBody(from: request)
            XCTAssertEqual(body["purpose"] as? String, "dictation")

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {
                "provider":"deepgram",
                "token":"dg_token_test",
                "expires_in_seconds":60,
                "sample_rate":16000,
                "audio_format":"linear16",
                "language":"multi",
                "channels":1,
                "model":"nova-3",
                "websocket_url":"wss://wai.computer/api/transcription/stream",
                "auth_scheme":"bearer",
                "keep_alive_interval_seconds":4
            }
            """.data(using: .utf8)!
            return (response, payload)
        }

        let config = try await client.createRealtimeTranscriptionSession(
            language: "multi",
            channels: 1,
            purpose: .dictation
        )
        XCTAssertEqual(config.provider, "deepgram")
        XCTAssertEqual(config.sampleRate, 16_000)
        XCTAssertEqual(config.authScheme, "bearer")
    }

    func testCreateRealtimeVoiceSessionSendsMode() async throws {
        let client = makeClient()

        MockURLProtocol.requestHandler = { request in
            XCTAssertEqual(request.httpMethod, "POST")
            XCTAssertEqual(request.url?.path, "/api/voice/session")

            let body = try self.jsonBody(from: request)
            XCTAssertEqual(body["mode"] as? String, "conversation")
            XCTAssertNil(body["agent_id"])

            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: 200,
                httpVersion: nil,
                headerFields: nil
            )!
            let payload = """
            {
                "provider":"elevenlabs",
                "mode":"conversation",
                "agent_id":"agent-123",
                "signed_url":"wss://api.elevenlabs.io/v1/convai/conversation?token=signed",
                "expires_in_seconds":900,
                "environment":"production",
                "branch_id":null
            }
            """.data(using: .utf8)!
            return (response, payload)
        }

        let session = try await client.createRealtimeVoiceSession(mode: .conversation)
        XCTAssertEqual(session.provider, "elevenlabs")
        XCTAssertEqual(session.agentId, "agent-123")
        XCTAssertTrue(session.signedURL.contains("api.elevenlabs.io"))
    }
}
