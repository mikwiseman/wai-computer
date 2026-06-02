import Foundation
import XCTest

@testable import WaiComputerKit

private final class FakeActuator: DesktopActuator, @unchecked Sendable {
    var openedURLs: [URL] = []
    var openedApps: [String] = []
    var typed: [String] = []
    var clicked: [Int] = []
    var shouldThrow = false

    struct Boom: Error { let target: String }

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
}

final class DesktopActionExecutorTests: XCTestCase {
    private func makeExecutor(_ actuator: FakeActuator) -> DesktopActionExecutor {
        DesktopActionExecutor(
            router: DesktopActionRouter(
                safety: DesktopSafetyPolicy(ownBundleId: "is.waiwai.computer")
            ),
            actuator: actuator
        )
    }

    private func item(_ tool: String, _ args: [String: CompanionJSONValue]) -> DesktopActionItem {
        DesktopActionItem(actionId: "a1", tool: tool, args: args, preview: "p")
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

    func testRefusalSkipsActuator() async {
        let actuator = FakeActuator()
        let outcome = await makeExecutor(actuator).execute(item("desktop_open", [:]))
        XCTAssertEqual(outcome.status, .refused)
        XCTAssertTrue(actuator.openedURLs.isEmpty)
        XCTAssertTrue(actuator.openedApps.isEmpty)
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
