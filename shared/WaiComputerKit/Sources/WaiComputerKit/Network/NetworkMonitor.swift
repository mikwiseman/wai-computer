import Foundation
import Network
import os
import Sentry

/// Observes network connectivity via NWPathMonitor and triggers
/// pending-recording sync whenever connectivity is restored.
public final class NetworkMonitor: Sendable {
    public static let shared = NetworkMonitor()

    private let monitor: NWPathMonitor
    private let queue = DispatchQueue(label: "is.waiwai.waicomputer.network-monitor")
    private let log = Logger(subsystem: "is.waiwai.waicomputer", category: "network")

    /// Current connectivity state (read from any thread).
    public private(set) var isConnected: Bool {
        get { _isConnected.wrappedValue }
        set { _isConnected.wrappedValue = newValue }
    }

    private let _isConnected = SendableAtomic(false)
    private let _isStarted = SendableAtomic(false)
    private let _callback = SendableAtomic<(@Sendable () -> Void)?>(nil)

    private init() {
        monitor = NWPathMonitor()
    }

    /// Internal initializer for testing.
    init(monitor: NWPathMonitor) {
        self.monitor = monitor
    }

    /// Start monitoring. Call once at app launch. Subsequent calls are ignored.
    /// - Parameter onRestored: Closure invoked each time the path transitions
    ///   from unsatisfied → satisfied. Runs on an internal serial queue.
    public func start(onRestored: @escaping @Sendable () -> Void) {
        guard !_isStarted.wrappedValue else {
            log.warning("NetworkMonitor.start() called more than once — ignored")
            return
        }
        _isStarted.wrappedValue = true
        _callback.wrappedValue = onRestored

        let wasConnected = SendableAtomic(false)

        monitor.pathUpdateHandler = { [weak self] path in
            guard let self else { return }
            let nowConnected = path.status == .satisfied
            let previouslyConnected = wasConnected.wrappedValue
            wasConnected.wrappedValue = nowConnected
            self.isConnected = nowConnected

            if nowConnected && !previouslyConnected {
                self.log.info("Network connectivity restored")
                SentryHelper.addBreadcrumb(
                    category: "network",
                    message: "connectivity restored",
                    data: ["interface": "\(path.availableInterfaces.first?.type ?? .other)"]
                )
                self._callback.wrappedValue?()
            } else if !nowConnected {
                self.log.info("Network connectivity lost")
                SentryHelper.addBreadcrumb(
                    category: "network",
                    message: "connectivity lost"
                )
            }
        }

        monitor.start(queue: queue)
        log.info("NetworkMonitor started")
    }

    public func stop() {
        monitor.cancel()
        _isStarted.wrappedValue = false
        log.info("NetworkMonitor stopped")
    }
}

/// Minimal thread-safe wrapper for a value, used internally by NetworkMonitor.
final class SendableAtomic<Value: Sendable>: @unchecked Sendable {
    private var _value: Value
    private let lock = NSLock()

    init(_ value: Value) {
        _value = value
    }

    var wrappedValue: Value {
        get { lock.withLock { _value } }
        set { lock.withLock { _value = newValue } }
    }
}
