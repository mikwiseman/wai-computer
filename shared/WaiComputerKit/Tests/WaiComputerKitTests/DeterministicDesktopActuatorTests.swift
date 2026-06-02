#if canImport(AppKit)
import Foundation
import XCTest

@testable import WaiComputerKit

final class DeterministicDesktopActuatorTests: XCTestCase {
    private let actuator = DeterministicDesktopActuator()

    func testTypeThrowsTierUnavailable() async {
        do {
            try await actuator.typeText("hi")
            XCTFail("expected throw")
        } catch let error as DesktopActuationError {
            guard case .tierUnavailable = error else {
                return XCTFail("expected tierUnavailable, got \(error)")
            }
        } catch {
            XCTFail("wrong error type")
        }
    }

    func testClickThrowsTierUnavailable() async {
        do {
            try await actuator.click(index: 1)
            XCTFail("expected throw")
        } catch let error as DesktopActuationError {
            guard case .tierUnavailable = error else {
                return XCTFail("expected tierUnavailable, got \(error)")
            }
        } catch {
            XCTFail("wrong error type")
        }
    }

    func testSnapshotThrowsTierUnavailable() async {
        do {
            _ = try await actuator.snapshot()
            XCTFail("expected throw")
        } catch let error as DesktopActuationError {
            guard case .tierUnavailable = error else {
                return XCTFail("expected tierUnavailable, got \(error)")
            }
        } catch {
            XCTFail("wrong error type")
        }
    }

    func testApplicationResolutionMissingNameIsNil() {
        XCTAssertNil(
            DeterministicDesktopActuator.applicationURL(forName: "NoSuchApp_zzz_123")
        )
    }

    func testApplicationResolutionMissingAbsolutePathIsNil() {
        XCTAssertNil(
            DeterministicDesktopActuator.applicationURL(forName: "/nope/Missing.app")
        )
    }
}
#endif
