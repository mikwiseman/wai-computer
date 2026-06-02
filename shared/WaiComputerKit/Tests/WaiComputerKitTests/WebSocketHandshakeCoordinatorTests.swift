import XCTest
import Foundation
@testable import WaiComputerKit

/// Coverage for the `WebSocketHandshakeCoordinator` lost-wakeup race — the
/// root cause of the stuck-dictation ("Подключаемся…") incident.
///
/// `ProviderBackedRealtimeSession.open()` calls `task.resume()` and only then
/// registers the handshake awaiter via a task-group child. Because the URLSession
/// is built with `delegateQueue: nil`, `didOpen`/`didClose`/`didComplete` fire on
/// URLSession's own serial queue — concurrently with, and sometimes *before*, the
/// awaiter registers. Before the settled-result latch, such an early callback was
/// dropped (`resumeWith` returned `false`, discarded with `_ =`), so `waitForOpen`
/// hung the full 10s handshake window and dictation sat on "Подключаемся…".
///
/// Tests 1/2/3/6 are RED on the pre-latch code (they resolve to `.didNotFinish`
/// because `waitForOpen` never wakes); the `within(_:)` guard bounds that to a
/// fast assertion failure instead of a hung suite.
final class WebSocketHandshakeCoordinatorTests: XCTestCase {

    /// Sendable, Equatable summary of how `waitForOpen` resolved. The thrown
    /// error (a non-Sendable `any Error`) is mapped to a case INSIDE the child
    /// task, so it never crosses the task-group boundary (Swift 6 concurrency).
    private enum Probe: Sendable, Equatable {
        case opened
        case closedBeforeOpen
        case completedBeforeOpen
        case timedOutError
        case otherError
        case didNotFinish
    }

    /// A throwaway WS task that exists only for a stable `ObjectIdentifier`.
    /// Never resumed — no network is performed.
    private static func makeTask() -> URLSessionWebSocketTask {
        URLSession(configuration: .ephemeral)
            .webSocketTask(with: URL(string: "wss://example.invalid/stream")!)
    }

    /// The coordinator ignores the delegate's `session` argument and keys purely
    /// on the task identity, so any session works for invoking the callbacks.
    private static func anySession() -> URLSession { URLSession(configuration: .ephemeral) }

    private static func awaitOpen(
        _ c: WebSocketHandshakeCoordinator,
        _ task: URLSessionWebSocketTask
    ) async -> Probe {
        do {
            try await c.waitForOpen(task: task)
            return .opened
        } catch let error as WebSocketHandshakeCoordinator.HandshakeError {
            switch error {
            case .closedBeforeOpen: return .closedBeforeOpen
            case .completedBeforeOpen: return .completedBeforeOpen
            case .timedOut: return .timedOutError
            }
        } catch {
            return .otherError
        }
    }

    /// One-shot guard so whichever racer (op vs timeout) finishes first wins.
    private final class Once: @unchecked Sendable {
        private let lock = NSLock()
        private var done = false
        func claim() -> Bool {
            lock.lock(); defer { lock.unlock() }
            if done { return false }
            done = true
            return true
        }
    }

    /// Run `op`, but never let a regression hang the suite: if it does not
    /// finish within `timeout`, resolve to `.didNotFinish`.
    ///
    /// Uses UNSTRUCTURED tasks (not a task group) on purpose: when `op` is
    /// expected to park forever (e.g. `waitForOpen` after `cancelPending`
    /// cleared the latch), a structured group would await the parked child at
    /// scope exit and hang — `CheckedContinuation` is not cancellation-aware.
    /// Here the losing task is simply abandoned.
    private func within(
        _ timeout: Double = 1.5,
        _ op: @escaping @Sendable () async -> Probe
    ) async -> Probe {
        let once = Once()
        return await withCheckedContinuation { (cont: CheckedContinuation<Probe, Never>) in
            Task {
                let probe = await op()
                if once.claim() { cont.resume(returning: probe) }
            }
            Task {
                try? await Task.sleep(nanoseconds: UInt64(timeout * 1_000_000_000))
                if once.claim() { cont.resume(returning: .didNotFinish) }
            }
        }
    }

    // 1. didOpen BEFORE waitForOpen must be latched + replayed (the P0).
    func testDidOpenBeforeWaitForOpenIsReplayed() async {
        let c = WebSocketHandshakeCoordinator()
        let task = Self.makeTask()
        c.urlSession(Self.anySession(), webSocketTask: task, didOpenWithProtocol: nil)
        let probe = await within { await Self.awaitOpen(c, task) }
        XCTAssertEqual(probe, .opened, "didOpen that fired before waitForOpen was dropped — lost-wakeup regression")
    }

    // 2. didClose BEFORE waitForOpen must surface as a fast, accurate throw.
    func testDidCloseBeforeWaitForOpenThrows() async {
        let c = WebSocketHandshakeCoordinator()
        let task = Self.makeTask()
        c.urlSession(Self.anySession(), webSocketTask: task,
                     didCloseWith: .policyViolation, reason: Data("AUTH_INVALID".utf8))
        let probe = await within { await Self.awaitOpen(c, task) }
        XCTAssertEqual(probe, .closedBeforeOpen)
    }

    // 3. didCompleteWithError BEFORE waitForOpen must surface as a fast throw.
    func testDidCompleteBeforeWaitForOpenThrows() async {
        let c = WebSocketHandshakeCoordinator()
        let task = Self.makeTask()
        c.urlSession(Self.anySession(), task: task, didCompleteWithError: URLError(.timedOut))
        let probe = await within { await Self.awaitOpen(c, task) }
        XCTAssertEqual(probe, .completedBeforeOpen)
    }

    // 4. Normal order (awaiter registers first, then didOpen) still resolves.
    func testWaitForOpenThenDidOpenResolves() async {
        let c = WebSocketHandshakeCoordinator()
        let task = Self.makeTask()
        let probe = await within {
            let waiter = Task { await Self.awaitOpen(c, task) }
            try? await Task.sleep(nanoseconds: 150_000_000) // let waitForOpen register
            c.urlSession(Self.anySession(), webSocketTask: task, didOpenWithProtocol: nil)
            return await waiter.value
        }
        XCTAssertEqual(probe, .opened)
    }

    // 5. cancelPending clears a latched outcome so a reused task identity is not poisoned.
    func testCancelPendingClearsLatch() async {
        let c = WebSocketHandshakeCoordinator()
        let task = Self.makeTask()
        c.urlSession(Self.anySession(), webSocketTask: task, didOpenWithProtocol: nil) // latch success
        c.cancelPending(for: task)                                                      // must clear it
        let probe = await within(0.5) { await Self.awaitOpen(c, task) }
        XCTAssertEqual(probe, .didNotFinish, "waitForOpen consumed a stale latched outcome after cancelPending")
    }

    // 6. Only the FIRST terminal outcome is latched (didClose wins over a later didComplete).
    func testOnlyFirstTerminalOutcomeIsLatched() async {
        let c = WebSocketHandshakeCoordinator()
        let task = Self.makeTask()
        c.urlSession(Self.anySession(), webSocketTask: task, didCloseWith: .policyViolation, reason: nil)
        c.urlSession(Self.anySession(), task: task, didCompleteWithError: URLError(.networkConnectionLost))
        let probe = await within { await Self.awaitOpen(c, task) }
        XCTAssertEqual(probe, .closedBeforeOpen)
    }
}
