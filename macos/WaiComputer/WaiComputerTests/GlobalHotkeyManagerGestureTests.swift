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
        try await Task.sleep(for: .milliseconds(250))
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
        // holdThreshold is 150 ms; wait safely past it so the timer has
        // dispatched the start callback on the main queue.
        try await Task.sleep(for: .milliseconds(220))
        XCTAssertEqual(starts, 1)

        manager.testingHandleFlagsChanged(
            keyCode: UInt16(kVK_RightCommand),
            flags: []
        )
        XCTAssertEqual(stops, 1)
    }

    func testRightCommandShiftStartsAndStopsTranslationWithoutPushToTalk() async throws {
        let manager = GlobalHotkeyManager()
        var pushStarts = 0
        var translationStarts = 0
        var translationStops = 0
        manager.onPushToTalkStart = { pushStarts += 1 }
        manager.onTranslationStart = { translationStarts += 1 }
        manager.onTranslationStop = { translationStops += 1 }

        manager.testingHandleFlagsChanged(
            keyCode: UInt16(kVK_RightCommand),
            flags: [.command]
        )
        try await Task.sleep(for: .milliseconds(40))
        manager.testingHandleFlagsChanged(
            keyCode: UInt16(kVK_Shift),
            flags: [.command, .shift]
        )

        XCTAssertEqual(translationStarts, 1)
        try await Task.sleep(for: .milliseconds(220))
        XCTAssertEqual(pushStarts, 0)

        manager.testingHandleFlagsChanged(
            keyCode: UInt16(kVK_Shift),
            flags: [.command]
        )
        XCTAssertEqual(translationStops, 1)
    }

    func testRightCommandSpaceStartsAndStopsAskAnythingWithoutPushToTalk() async throws {
        let manager = GlobalHotkeyManager()
        var pushStarts = 0
        var askStarts = 0
        var askStops = 0
        manager.onPushToTalkStart = { pushStarts += 1 }
        manager.onAskAnythingStart = { askStarts += 1 }
        manager.onAskAnythingStop = { askStops += 1 }

        manager.testingHandleFlagsChanged(
            keyCode: UInt16(kVK_RightCommand),
            flags: [.command]
        )
        try await Task.sleep(for: .milliseconds(40))
        manager.testingHandleKeyDown(keyCode: UInt16(kVK_Space))

        XCTAssertEqual(askStarts, 1)
        try await Task.sleep(for: .milliseconds(220))
        XCTAssertEqual(pushStarts, 0)

        manager.testingHandleFlagsChanged(
            keyCode: UInt16(kVK_RightCommand),
            flags: []
        )
        XCTAssertEqual(askStops, 1)
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

    func testPrimaryHotkeyPressStopsActiveHandsFreeWithoutEnteringPushToTalk() async throws {
        let manager = GlobalHotkeyManager()
        manager.isHandsFreeModeActive = true
        var starts = 0
        var toggles = 0
        manager.onPushToTalkStart = { starts += 1 }
        manager.onHandsFreeToggle = { toggles += 1 }

        manager.testingHandleFlagsChanged(
            keyCode: UInt16(kVK_RightCommand),
            flags: [.command]
        )

        XCTAssertEqual(toggles, 1)
        try await Task.sleep(for: .milliseconds(120))
        XCTAssertEqual(starts, 0)

        manager.testingHandleFlagsChanged(
            keyCode: UInt16(kVK_RightCommand),
            flags: []
        )
        XCTAssertEqual(toggles, 1)
    }

    func testFastDoubleTapWithHumanPacingTogglesHandsFree() async throws {
        // The bug this guards against: with the old 80 ms holdThreshold, a
        // user's "fast" double-tap (~100 ms per press) had each press
        // exceed 80 ms wall-clock → promoted to push-to-talk → never reached
        // registerTap → lastTapTime never set → no double-tap detected.
        // Researched across 6 agents on 2026-05-28 — this is the documented
        // failure pattern Mik reported.
        let manager = GlobalHotkeyManager()
        var starts = 0
        var toggles = 0
        manager.onPushToTalkStart = { starts += 1 }
        manager.onHandsFreeToggle = { toggles += 1 }

        // First press: 100 ms (well under the new 150 ms threshold, but
        // would have exceeded the old 80 ms one).
        manager.testingPressHotkey()
        try await Task.sleep(for: .milliseconds(100))
        manager.testingReleaseHotkey()
        // Inter-tap gap: 80 ms (human-realistic fast double-tap).
        try await Task.sleep(for: .milliseconds(80))
        // Second press: 100 ms.
        manager.testingPressHotkey()
        try await Task.sleep(for: .milliseconds(100))
        manager.testingReleaseHotkey()
        try await Task.sleep(for: .milliseconds(50))

        XCTAssertEqual(starts, 0, "Neither tap should have started push-to-talk")
        XCTAssertEqual(toggles, 1, "Fast double-tap with ~100 ms presses must toggle hands-free")
    }

    func testPushToTalkStopClearsLastTapTimeAgainstFalseDoubleTap() async throws {
        // State-leak fix: after a real push-to-talk hold, a subsequent quick
        // tap should NOT pair with a tap that happened before the hold —
        // even if the time gap is < doubleTapInterval. Previously
        // `lastTapTime` survived holds, so a sequence
        //   tap → 200 ms → 300 ms hold (PTT) → 100 ms → tap
        // would falsely fire onHandsFreeToggle on the second tap (the gap
        // from the FIRST tap to the second is 600 ms but each segment was
        // shorter, and the policy reads lastTapTime directly).
        let manager = GlobalHotkeyManager()
        var toggles = 0
        var stops = 0
        manager.onHandsFreeToggle = { toggles += 1 }
        manager.onPushToTalkStop = { stops += 1 }

        // Tap #1: seeds lastTapTime
        manager.testingPressHotkey()
        try await Task.sleep(for: .milliseconds(80))
        manager.testingReleaseHotkey()
        // Hold (PTT) immediately after
        try await Task.sleep(for: .milliseconds(50))
        manager.testingPressHotkey()
        try await Task.sleep(for: .milliseconds(250))  // past 150 ms threshold
        manager.testingReleaseHotkey()
        XCTAssertEqual(stops, 1, "PTT must have stopped cleanly")
        // A new tap shortly after the PTT must NOT toggle hands-free
        try await Task.sleep(for: .milliseconds(80))
        manager.testingPressHotkey()
        try await Task.sleep(for: .milliseconds(60))
        manager.testingReleaseHotkey()
        try await Task.sleep(for: .milliseconds(50))

        XCTAssertEqual(toggles, 0, "Tap after PTT-stop must not falsely toggle hands-free")
    }

    func testHandsFreeStopReleaseDoesNotSeedNextDoubleTapAfterCleanup() async throws {
        let manager = GlobalHotkeyManager()
        manager.isHandsFreeModeActive = true
        var toggles = 0
        manager.onHandsFreeToggle = { toggles += 1 }

        manager.testingHandleFlagsChanged(
            keyCode: UInt16(kVK_RightCommand),
            flags: [.command]
        )
        XCTAssertEqual(toggles, 1)

        manager.isHandsFreeModeActive = false
        manager.testingHandleFlagsChanged(
            keyCode: UInt16(kVK_RightCommand),
            flags: []
        )

        manager.testingHandleFlagsChanged(
            keyCode: UInt16(kVK_RightCommand),
            flags: [.command]
        )
        try await Task.sleep(for: .milliseconds(35))
        manager.testingHandleFlagsChanged(
            keyCode: UInt16(kVK_RightCommand),
            flags: []
        )

        XCTAssertEqual(toggles, 1)
    }

    func testEscapeCancelsDictation() {
        let manager = GlobalHotkeyManager()
        var cancels = 0
        manager.onCancelled = { cancels += 1 }

        manager.testingHandleKeyDown(keyCode: UInt16(kVK_Escape))

        XCTAssertEqual(cancels, 1)
    }
}
