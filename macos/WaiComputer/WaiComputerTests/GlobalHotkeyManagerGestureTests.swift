import Carbon
import XCTest

@MainActor
final class GlobalHotkeyManagerGestureTests: XCTestCase {
    func testShortTapDoesNotStartPushToTalk() async throws {
        let manager = GlobalHotkeyManager()
        var starts = 0
        var taps = 0
        manager.onPushToTalkStart = { starts += 1 }
        manager.onSingleTap = { taps += 1 }

        manager.testingPressHotkey()
        try await Task.sleep(for: .milliseconds(35))
        manager.testingReleaseHotkey()
        try await Task.sleep(for: .milliseconds(200))

        XCTAssertEqual(starts, 0)
        XCTAssertEqual(taps, 1)
    }

    func testHoldStartsAndStopsPushToTalk() async throws {
        let manager = GlobalHotkeyManager()
        var starts = 0
        var stops = 0
        manager.onPushToTalkStart = { starts += 1 }
        manager.onPushToTalkStop = { stops += 1 }

        manager.testingPressHotkey()
        try await Task.sleep(for: .milliseconds(180))
        XCTAssertEqual(starts, 1)

        manager.testingReleaseHotkey()
        XCTAssertEqual(stops, 1)
    }

    func testRightCommandFlagsChangedStartsAndStopsPushToTalk() async throws {
        let manager = GlobalHotkeyManager()
        var starts = 0
        var stops = 0
        manager.onPushToTalkStart = { starts += 1 }
        manager.onPushToTalkStop = { stops += 1 }

        manager.testingHandleFlagsChanged(
            keyCode: UInt16(kVK_RightCommand),
            flags: [.command]
        )
        try await Task.sleep(for: .milliseconds(100))
        XCTAssertEqual(starts, 1)

        manager.testingHandleFlagsChanged(
            keyCode: UInt16(kVK_RightCommand),
            flags: []
        )
        XCTAssertEqual(stops, 1)
    }

    func testDoubleTapTogglesHandsFreeWithoutPushToTalkStart() async throws {
        let manager = GlobalHotkeyManager()
        var starts = 0
        var toggles = 0
        manager.onPushToTalkStart = { starts += 1 }
        manager.onHandsFreeToggle = { toggles += 1 }

        manager.testingPressHotkey()
        try await Task.sleep(for: .milliseconds(40))
        manager.testingReleaseHotkey()
        try await Task.sleep(for: .milliseconds(80))
        manager.testingPressHotkey()
        try await Task.sleep(for: .milliseconds(40))
        manager.testingReleaseHotkey()
        try await Task.sleep(for: .milliseconds(200))

        XCTAssertEqual(starts, 0)
        XCTAssertEqual(toggles, 1)
    }
}
