import Foundation
import XCTest

@testable import WaiComputerKit

private final class FakeActuator: DesktopActuator, @unchecked Sendable {
    var openedURLs: [URL] = []
    var openedApps: [String] = []
    var typed: [String] = []
    var clicked: [Int] = []
    var snapshotCalls = 0
    var shouldThrow = false
    var shouldThrowOnFrontmost = false
    var frontmostBundleIdValue: String? = "com.apple.TextEdit"

    struct Boom: Error { let target: String }

    func frontmostBundleId() async throws -> String? {
        if shouldThrowOnFrontmost { throw Boom(target: "frontmost") }
        return frontmostBundleIdValue
    }

    func openURL(_ url: URL) async throws {
        if shouldThrow { throw Boom(target: url.absoluteString) }
        openedURLs.append(url)
    }
    func openApp(name: String) async throws {
        if shouldThrow { throw Boom(target: name) }
        openedApps.append(name)
    }
    func typeText(_ text: String) async throws {
        if shouldThrow { throw Boom(target: text) }
        typed.append(text)
    }
    func click(index: Int) async throws {
        if shouldThrow { throw Boom(target: "\(index)") }
        clicked.append(index)
    }
    var snapshotToReturn = DesktopUISnapshot(
        app: "Test",
        elements: [DesktopUIElement(index: 0, role: "AXButton", title: "OK", actionable: true)]
    )
    func snapshot() async throws -> DesktopUISnapshot {
        if shouldThrow { throw Boom(target: "snapshot") }
        snapshotCalls += 1
        return snapshotToReturn
    }
}

final class DesktopActionExecutorTests: XCTestCase {
    private func makeExecutor(
        _ actuator: FakeActuator,
        safety: DesktopSafetyPolicy = DesktopSafetyPolicy(ownBundleId: "is.waiwai.computer")
    ) -> DesktopActionExecutor {
        DesktopActionExecutor(
            router: DesktopActionRouter(safety: safety),
            actuator: actuator
        )
    }

    private func item(_ tool: String, _ args: [String: CompanionJSONValue]) -> DesktopActionItem {
        DesktopActionItem(actionId: "a1", chatId: "c1", tool: tool, args: args, preview: "p")
    }

    func testOpenURLDispatchesAndSucceeds() async {
        let actuator = FakeActuator()
        let outcome = await makeExecutor(actuator)
            .execute(item("desktop_open", ["target": .string("mailto:a@x.com")]))
        XCTAssertEqual(outcome, .executed)
        XCTAssertEqual(outcome.status, .executed)
        XCTAssertEqual(actuator.openedURLs.map(\.scheme), ["mailto"])
    }

    func testOpenAppDispatches() async {
        let actuator = FakeActuator()
        _ = await makeExecutor(actuator)
            .execute(item("desktop_open", ["target": .string("Mail")]))
        XCTAssertEqual(actuator.openedApps, ["Mail"])
    }

    func testTypeDispatches() async {
        let actuator = FakeActuator()
        _ = await makeExecutor(actuator)
            .execute(item("desktop_type", ["text": .string("hi")]))
        XCTAssertEqual(actuator.typed, ["hi"])
    }

    func testClickDispatches() async {
        let actuator = FakeActuator()
        _ = await makeExecutor(actuator)
            .execute(item("desktop_click", ["index": .int(7)]))
        XCTAssertEqual(actuator.clicked, [7])
    }

    func testTypeRefusesOwnFrontmostBundleBeforeActuating() async {
        let actuator = FakeActuator()
        actuator.frontmostBundleIdValue = "is.waiwai.computer"
        let outcome = await makeExecutor(actuator)
            .execute(item("desktop_type", ["text": .string("hi")]))
        XCTAssertEqual(outcome.status, .refused)
        XCTAssertTrue(actuator.typed.isEmpty)
        XCTAssertEqual(outcome.reason, "own UI is excluded from actuation")
    }

    func testClickRefusesBlockedFrontmostBundleBeforeActuating() async {
        let actuator = FakeActuator()
        actuator.frontmostBundleIdValue = "com.apple.Terminal"
        let outcome = await makeExecutor(
            actuator,
            safety: DesktopSafetyPolicy(
                ownBundleId: "is.waiwai.computer",
                blockedBundleIds: ["com.apple.Terminal"]
            )
        ).execute(item("desktop_click", ["index": .int(7)]))
        XCTAssertEqual(outcome.status, .refused)
        XCTAssertTrue(actuator.clicked.isEmpty)
        XCTAssertEqual(outcome.reason, "target app is blocked")
    }

    func testSnapshotRefusesWhenFrontmostTargetCannotBeResolved() async {
        let actuator = FakeActuator()
        actuator.frontmostBundleIdValue = nil
        let outcome = await makeExecutor(actuator).execute(item("desktop_snapshot", [:]))
        XCTAssertEqual(outcome.status, .refused)
        XCTAssertEqual(actuator.snapshotCalls, 0)
        XCTAssertEqual(outcome.reason, "target app unavailable")
    }

    func testFrontmostInspectionFailureIsFailedBeforeActuating() async {
        let actuator = FakeActuator()
        actuator.shouldThrowOnFrontmost = true
        let outcome = await makeExecutor(actuator)
            .execute(item("desktop_type", ["text": .string("hi")]))
        XCTAssertEqual(outcome.status, .failed)
        XCTAssertTrue(actuator.typed.isEmpty)
        XCTAssertEqual(outcome.reason, "could not verify target app")
    }

    func testRefusalSkipsActuator() async {
        let actuator = FakeActuator()
        let outcome = await makeExecutor(actuator).execute(item("desktop_open", [:]))
        XCTAssertEqual(outcome.status, .refused)
        XCTAssertTrue(actuator.openedURLs.isEmpty)
        XCTAssertTrue(actuator.openedApps.isEmpty)
    }

    func testSnapshotIsObservedAndCarriesUI() async {
        let actuator = FakeActuator()
        let outcome = await makeExecutor(actuator).execute(item("desktop_snapshot", [:]))
        XCTAssertEqual(outcome.status, .executed)
        XCTAssertEqual(outcome.snapshot?.elements.first?.title, "OK")
    }

    func testSnapshotFailureIsFailed() async {
        let actuator = FakeActuator()
        actuator.shouldThrow = true
        let outcome = await makeExecutor(actuator).execute(item("desktop_snapshot", [:]))
        XCTAssertEqual(outcome.status, .failed)
        XCTAssertNil(outcome.snapshot)
    }

    func testActuatorThrowBecomesFailedWithGenericReason() async {
        let actuator = FakeActuator()
        actuator.shouldThrow = true
        let outcome = await makeExecutor(actuator)
            .execute(item("desktop_open", ["target": .string("mailto:secret@x.com")]))
        XCTAssertEqual(outcome.status, .failed)
        // The wire reason must not leak the raw target.
        XCTAssertNotNil(outcome.reason)
        XCTAssertFalse(outcome.reason!.contains("secret@x.com"))
    }
}
