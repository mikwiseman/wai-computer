import Foundation
import Network
import XCTest
@testable import WaiComputerKit

final class NetworkMonitorTests: XCTestCase {

    func testStartSetsIsConnectedOnRealNetwork() {
        let monitor = NetworkMonitor(monitor: NWPathMonitor())
        let connected = expectation(description: "isConnected becomes true")

        monitor.start {
            connected.fulfill()
        }

        // On a machine with network, the first path update should report connected.
        // The callback fires on a serial queue, so give it a moment.
        wait(for: [connected], timeout: 2)
        XCTAssertTrue(monitor.isConnected)
        monitor.stop()
    }

    func testStopDoesNotCrashWhenCalledBeforeStart() {
        let monitor = NetworkMonitor(monitor: NWPathMonitor())
        // Calling stop without start should not crash
        monitor.stop()
    }

    func testIsConnectedDefaultsToFalse() {
        let monitor = NetworkMonitor(monitor: NWPathMonitor())
        XCTAssertFalse(monitor.isConnected)
    }

    func testCallbackNotFiredOnSubsequentSatisfiedPaths() {
        let monitor = NetworkMonitor(monitor: NWPathMonitor())
        var callCount = 0
        let firstCall = expectation(description: "first callback")

        monitor.start {
            callCount += 1
            if callCount == 1 {
                firstCall.fulfill()
            }
        }

        wait(for: [firstCall], timeout: 2)

        // After the initial connection, wait a bit to see if callback fires again
        // (it shouldn't, since network stays connected)
        let noSecondCall = expectation(description: "no second callback")
        noSecondCall.isInverted = true

        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
            if callCount > 1 {
                noSecondCall.fulfill()
            }
        }

        wait(for: [noSecondCall], timeout: 1)
        XCTAssertEqual(callCount, 1)
        monitor.stop()
    }

    func testSecondStartCallIsIgnored() {
        let monitor = NetworkMonitor(monitor: NWPathMonitor())
        var callCount = 0
        let firstCall = expectation(description: "first callback")

        monitor.start {
            callCount += 1
            if callCount == 1 {
                firstCall.fulfill()
            }
        }

        wait(for: [firstCall], timeout: 2)

        // Second start should be silently ignored
        var secondCallbackFired = false
        monitor.start {
            secondCallbackFired = true
        }

        let noSecondCallback = expectation(description: "second start ignored")
        noSecondCallback.isInverted = true
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
            if secondCallbackFired {
                noSecondCallback.fulfill()
            }
        }

        wait(for: [noSecondCallback], timeout: 1)
        XCTAssertFalse(secondCallbackFired)
        XCTAssertEqual(callCount, 1)
        monitor.stop()
    }

    func testStopThenStartWorksCorrectly() {
        let monitor = NetworkMonitor(monitor: NWPathMonitor())
        let firstConnected = expectation(description: "first start connected")

        monitor.start {
            firstConnected.fulfill()
        }

        wait(for: [firstConnected], timeout: 2)
        XCTAssertTrue(monitor.isConnected)
        monitor.stop()

        // After stop, a new monitor instance should be used
        // (NWPathMonitor can't be restarted after cancel)
        let monitor2 = NetworkMonitor(monitor: NWPathMonitor())
        let secondConnected = expectation(description: "second monitor connected")

        monitor2.start {
            secondConnected.fulfill()
        }

        wait(for: [secondConnected], timeout: 2)
        XCTAssertTrue(monitor2.isConnected)
        monitor2.stop()
    }
}
