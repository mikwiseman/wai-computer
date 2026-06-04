import Foundation
import XCTest

@testable import WaiComputerKit

private final class FakeTransport: MacEdgeTransport, @unchecked Sendable {
    var heartbeatDeviceId = "dev-1"
    var heartbeatCalls: [String?] = []
    var queue = DesktopActionQueue(actions: [])
    var reports:
        [(
            chatId: String, actionId: String, deviceId: String, status: DesktopResultStatus,
            payload: [String: CompanionJSONValue]?
        )] = []
    var agentReports:
        [(
            agentId: String, runId: String, actionId: String, deviceId: String,
            status: DesktopResultStatus,
            payload: [String: CompanionJSONValue]?
        )] = []
    var failReports = false

    func deviceHeartbeat(
        platform: String, name: String?, deviceId: String?
    ) async throws -> DeviceHeartbeatResponse {
        heartbeatCalls.append(deviceId)
        return DeviceHeartbeatResponse(deviceId: heartbeatDeviceId, online: true)
    }
    func drainDesktopActions(deviceId: String) async throws -> DesktopActionQueue { queue }
    func reportDesktopResult(
        chatId: String, actionId: String, deviceId: String, status: DesktopResultStatus,
        payload: [String: CompanionJSONValue]?
    ) async throws -> DesktopResultResponse {
        if failReports { throw URLError(.notConnectedToInternet) }
        reports.append((chatId, actionId, deviceId, status, payload))
        return DesktopResultResponse(actionId: actionId, status: status.rawValue)
    }
    func reportAgentDesktopResult(
        agentId: String, runId: String, actionId: String, deviceId: String,
        status: DesktopResultStatus,
        payload: [String: CompanionJSONValue]?
    ) async throws -> DesktopResultResponse {
        if failReports { throw URLError(.notConnectedToInternet) }
        agentReports.append((agentId, runId, actionId, deviceId, status, payload))
        return DesktopResultResponse(actionId: actionId, status: status.rawValue)
    }
}

private final class CountingActuator: DesktopActuator, @unchecked Sendable {
    var openURLCount = 0
    func frontmostBundleId() async throws -> String? { "com.apple.TextEdit" }
    func openURL(_ url: URL) async throws { openURLCount += 1 }
    func openApp(name: String) async throws {}
    func typeText(_ text: String) async throws {}
    func click(index: Int) async throws {}
    func snapshot() async throws -> DesktopUISnapshot {
        DesktopUISnapshot(
            app: "Test",
            elements: [DesktopUIElement(index: 0, role: "AXButton", title: "OK", actionable: true)]
        )
    }
}

final class MacEdgeCoordinatorTests: XCTestCase {
    private func make() -> (FakeTransport, CountingActuator, MacEdgeCoordinator) {
        let transport = FakeTransport()
        let actuator = CountingActuator()
        let executor = DesktopActionExecutor(
            router: DesktopActionRouter(
                safety: DesktopSafetyPolicy(ownBundleId: "is.waiwai.computer")
            ),
            actuator: actuator
        )
        return (transport, actuator, MacEdgeCoordinator(transport: transport, executor: executor))
    }

    private func openAction(_ id: String, _ target: String) -> DesktopActionItem {
        DesktopActionItem(
            actionId: id, chatId: "c1", tool: "desktop_open",
            args: ["target": .string(target)], preview: "p"
        )
    }

    func testPollExecutesDrainedActionAndReports() async throws {
        let (transport, actuator, coord) = make()
        transport.queue = DesktopActionQueue(actions: [openAction("a1", "mailto:a@x.com")])
        let outcomes = try await coord.pollOnce()
        XCTAssertEqual(outcomes, [.executed])
        XCTAssertEqual(actuator.openURLCount, 1)
        XCTAssertEqual(transport.reports.count, 1)
        XCTAssertEqual(transport.reports[0].chatId, "c1")
        XCTAssertEqual(transport.reports[0].deviceId, "dev-1")
        XCTAssertEqual(transport.reports[0].status, .executed)
        // The first heartbeat has no device id yet.
        XCTAssertEqual(transport.heartbeatCalls, [nil])
    }

    func testDeviceIdReusedOnSubsequentHeartbeat() async throws {
        let (transport, _, coord) = make()
        _ = try await coord.pollOnce()
        _ = try await coord.pollOnce()
        XCTAssertEqual(transport.heartbeatCalls, [nil, "dev-1"])
    }

    func testReportFailureNeverReexecutesSideEffect() async throws {
        let (transport, actuator, coord) = make()
        transport.queue = DesktopActionQueue(actions: [openAction("a1", "mailto:a@x.com")])
        transport.failReports = true

        _ = try await coord.pollOnce()  // executes, report fails
        XCTAssertEqual(actuator.openURLCount, 1)
        XCTAssertEqual(transport.reports.count, 0)

        _ = try await coord.pollOnce()  // re-drained, still failing — must NOT re-run
        XCTAssertEqual(actuator.openURLCount, 1)

        transport.failReports = false
        _ = try await coord.pollOnce()  // report finally lands
        XCTAssertEqual(actuator.openURLCount, 1)
        XCTAssertEqual(transport.reports.count, 1)
    }

    func testSnapshotActionReportsCapturedUIInPayload() async throws {
        let (transport, _, coord) = make()
        transport.queue = DesktopActionQueue(actions: [
            DesktopActionItem(
                actionId: "s1", chatId: "c1", tool: "desktop_snapshot", args: [:],
                preview: "look"
            )
        ])
        let outcomes = try await coord.pollOnce()
        XCTAssertEqual(outcomes.first?.status, .executed)
        XCTAssertEqual(transport.reports.count, 1)
        // The observe result carries the captured UI back to the brain.
        XCTAssertNotNil(transport.reports[0].payload?["snapshot"])
    }

    func testAgentActionReportsToAgentEndpoint() async throws {
        let (transport, actuator, coord) = make()
        transport.queue = DesktopActionQueue(actions: [
            DesktopActionItem(
                actionId: "a1",
                agentId: "agent-1",
                agentRunId: "run-1",
                tool: "desktop_open",
                args: ["target": .string("mailto:a@x.com")],
                preview: "p"
            )
        ])
        let outcomes = try await coord.pollOnce()
        XCTAssertEqual(outcomes, [.executed])
        XCTAssertEqual(actuator.openURLCount, 1)
        XCTAssertEqual(transport.reports.count, 0)
        XCTAssertEqual(transport.agentReports.count, 1)
        XCTAssertEqual(transport.agentReports[0].agentId, "agent-1")
        XCTAssertEqual(transport.agentReports[0].runId, "run-1")
        XCTAssertEqual(transport.agentReports[0].deviceId, "dev-1")
    }

    func testRefusalIsReportedAndSkipsActuator() async throws {
        let (transport, actuator, coord) = make()
        // Missing target → router refuses.
        transport.queue = DesktopActionQueue(actions: [
            DesktopActionItem(
                actionId: "a2", chatId: "c1", tool: "desktop_open", args: [:], preview: "p"
            )
        ])
        let outcomes = try await coord.pollOnce()
        XCTAssertEqual(outcomes.map(\.status), [.refused])
        XCTAssertEqual(actuator.openURLCount, 0)
        XCTAssertEqual(transport.reports.count, 1)
        XCTAssertEqual(transport.reports[0].status, .refused)
    }

    func testMalformedActionWithoutReportTargetNeverExecutesSideEffect() async throws {
        let (transport, actuator, coord) = make()
        transport.queue = DesktopActionQueue(actions: [
            DesktopActionItem(
                actionId: "bad-target",
                tool: "desktop_open",
                args: ["target": .string("mailto:a@x.com")],
                preview: "p"
            )
        ])

        let outcomes = try await coord.pollOnce()

        XCTAssertEqual(outcomes.map(\.status), [.refused])
        XCTAssertEqual(actuator.openURLCount, 0)
        XCTAssertEqual(transport.reports.count, 0)
        XCTAssertEqual(transport.agentReports.count, 0)
    }
}
