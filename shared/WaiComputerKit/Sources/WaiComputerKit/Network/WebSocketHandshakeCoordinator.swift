import Foundation
import os

private let handshakeLog = Logger(subsystem: "is.waiwai.computer.kit", category: "wsHandshake")

/// `URLSessionWebSocketDelegate` adapter that lets a caller `await`
/// `urlSession(_:webSocketTask:didOpenWithProtocol:)` — i.e. the moment the
/// HTTP→WebSocket upgrade actually completes — instead of returning
/// optimistically after `task.resume()`. If the server closes the upgrade
/// (e.g. proxy responds with `close 1008` on a bad token) or any URLSession
/// error fires before `didOpen`, the awaiter throws.
///
/// Why this matters: `URLSessionWebSocketTask.resume()` is non-blocking and
/// has no built-in async "did open" signal. Yielding `.opened` synthetically
/// right after `resume()` (the previous implementation) means downstream
/// state machines transition to `.listening` before the handshake completes
/// — and any close that arrives during the handshake window gets dropped on
/// the floor by guards that only act when state is already `.listening`.
public final class WebSocketHandshakeCoordinator: NSObject, URLSessionWebSocketDelegate, @unchecked Sendable {

    public enum HandshakeError: Error, LocalizedError {
        case closedBeforeOpen(closeCode: URLSessionWebSocketTask.CloseCode, reason: String?)
        case completedBeforeOpen(error: Error?)
        case timedOut

        public var errorDescription: String? {
            switch self {
            case .closedBeforeOpen(let code, let reason):
                return "WebSocket closed before handshake completed (code: \(code.rawValue), reason: \(reason ?? "(none)"))"
            case .completedBeforeOpen(let error):
                if let error {
                    return "WebSocket task completed before handshake: \(error.localizedDescription)"
                }
                return "WebSocket task completed before handshake"
            case .timedOut:
                return "WebSocket handshake timed out"
            }
        }
    }

    private let lock = NSLock()
    private var continuations: [ObjectIdentifier: CheckedContinuation<Void, Error>] = [:]
    /// Terminal outcome recorded by a delegate callback that fired BEFORE the
    /// awaiter registered (the fast-upgrade lost-wakeup race that wedged
    /// dictation on "Подключаемся…"). Replayed to the next `waitForOpen` so the
    /// wakeup is never lost. Keyed by task identity; consumed/cleared within a
    /// single connect attempt.
    private var resolved: [ObjectIdentifier: Result<Void, Error>] = [:]

    public override init() {
        super.init()
    }

    /// Suspend until the given task either reports `didOpenWithProtocol`
    /// (success) or closes / completes with an error (throw). The caller must
    /// invoke this AFTER `task.resume()`.
    public func waitForOpen(task: URLSessionWebSocketTask) async throws {
        try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
            let id = ObjectIdentifier(task)
            lock.lock()
            if let pending = resolved.removeValue(forKey: id) {
                lock.unlock()
                // A delegate callback already fired for this task before we
                // registered — replay its outcome instead of parking forever.
                // Resume OUTSIDE the lock to avoid re-entrant acquisition.
                continuation.resume(with: pending)
                return
            }
            continuations[id] = continuation
            lock.unlock()
        }
    }

    /// Drop a pending awaiter for `task` without throwing — used when the
    /// task is being cancelled before the handshake completed (e.g. session
    /// `cancel()`). If no awaiter is registered, this is a no-op.
    public func cancelPending(for task: URLSessionWebSocketTask) {
        let id = ObjectIdentifier(task)
        lock.lock()
        let continuation = continuations.removeValue(forKey: id)
        // Drop any latched outcome too, so a stale result can't leak to a
        // future task that happens to reuse this ObjectIdentifier.
        resolved.removeValue(forKey: id)
        lock.unlock()
        continuation?.resume(throwing: HandshakeError.completedBeforeOpen(error: nil))
    }

    private func resumeWith(task: URLSessionWebSocketTask, result: Result<Void, Error>) -> Bool {
        let id = ObjectIdentifier(task)
        lock.lock()
        if let continuation = continuations.removeValue(forKey: id) {
            lock.unlock()
            continuation.resume(with: result)
            return true
        }
        // No awaiter registered yet — the delegate won the race. Latch the
        // FIRST terminal outcome so a slightly-later waitForOpen can replay it;
        // subsequent callbacks (e.g. didComplete after didClose) must not
        // clobber it.
        if resolved[id] == nil {
            resolved[id] = result
        }
        lock.unlock()
        return false
    }

    // MARK: - URLSessionWebSocketDelegate

    public func urlSession(
        _ session: URLSession,
        webSocketTask: URLSessionWebSocketTask,
        didOpenWithProtocol protocolName: String?
    ) {
        _ = resumeWith(task: webSocketTask, result: .success(()))
        handshakeLog.debug("[handshake] didOpen protocol=\(protocolName ?? "(none)", privacy: .public)")
    }

    public func urlSession(
        _ session: URLSession,
        webSocketTask: URLSessionWebSocketTask,
        didCloseWith closeCode: URLSessionWebSocketTask.CloseCode,
        reason: Data?
    ) {
        let reasonString = reason.flatMap { String(data: $0, encoding: .utf8) }
        _ = resumeWith(
            task: webSocketTask,
            result: .failure(HandshakeError.closedBeforeOpen(closeCode: closeCode, reason: reasonString))
        )
        handshakeLog.debug("[handshake] didClose code=\(closeCode.rawValue, privacy: .public)")
    }

    public func urlSession(
        _ session: URLSession,
        task: URLSessionTask,
        didCompleteWithError error: Error?
    ) {
        guard let webSocketTask = task as? URLSessionWebSocketTask else { return }
        // didCompleteWithError fires AFTER didCloseWithCode in normal
        // close paths, so the continuations dict is usually empty here.
        // We still try to resume to catch errors that bypass didCloseWith
        // (DNS failures, TLS errors, dropped sockets).
        _ = resumeWith(
            task: webSocketTask,
            result: .failure(HandshakeError.completedBeforeOpen(error: error))
        )
    }
}
