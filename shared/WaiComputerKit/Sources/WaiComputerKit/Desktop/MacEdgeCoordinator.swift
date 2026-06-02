import Foundation

/// The transport the Mac-edge pump needs: the subset of `APIClient` that the
/// channel uses. Declared narrowly so the coordinator is testable with a fake;
/// `APIClient` conforms as-is.
public protocol MacEdgeTransport: Sendable {
    func deviceHeartbeat(
        platform: String, name: String?, deviceId: String?
    ) async throws -> DeviceHeartbeatResponse
    func drainDesktopActions(deviceId: String) async throws -> DesktopActionQueue
    func reportDesktopResult(
        chatId: String, actionId: String, status: DesktopResultStatus,
        payload: [String: CompanionJSONValue]?
    ) async throws -> DesktopResultResponse
}

/// Drives the Mac-edge channel for this device: advertise presence, drain
/// approved desktop actions, execute each via the tiered executor, and report
/// the outcome back. The app calls ``pollOnce()`` on a timer (timing lives in
/// the app, not here, so this stays deterministically testable).
///
/// Effectively-once: a drained action is executed at most once per session even
/// if reporting its result fails. The server only drops an action from the
/// queue once a result lands, so a transient report failure would otherwise
/// re-drain and re-run the side effect (e.g. open the compose window twice).
/// We remember the local outcome and, on re-drain, retry only the report.
public actor MacEdgeCoordinator {
    private let transport: MacEdgeTransport
    private let executor: DesktopActionExecutor
    private let platform: String
    private let deviceName: String?

    private var deviceId: String?
    /// Actions executed locally but whose result has not yet been accepted by
    /// the server. Keyed by action id; cleared once the report succeeds.
    private var unreported: [String: DesktopActuationOutcome] = [:]

    public init(
        transport: MacEdgeTransport,
        executor: DesktopActionExecutor,
        platform: String = "macos",
        deviceName: String? = nil
    ) {
        self.transport = transport
        self.executor = executor
        self.platform = platform
        self.deviceName = deviceName
    }

    /// One poll cycle. Heartbeats (registering on the first call), then drains
    /// and processes each queued action. Returns each action's outcome.
    @discardableResult
    public func pollOnce() async throws -> [DesktopActuationOutcome] {
        let heartbeat = try await transport.deviceHeartbeat(
            platform: platform, name: deviceName, deviceId: deviceId
        )
        deviceId = heartbeat.deviceId

        let queue = try await transport.drainDesktopActions(deviceId: heartbeat.deviceId)
        var outcomes: [DesktopActuationOutcome] = []
        for action in queue.actions {
            // Execute at most once: reuse a prior outcome if the side effect
            // already ran but its report has not yet been accepted.
            let outcome: DesktopActuationOutcome
            if let prior = unreported[action.actionId] {
                outcome = prior
            } else {
                outcome = await executor.execute(action)
                unreported[action.actionId] = outcome
            }
            outcomes.append(outcome)

            do {
                _ = try await transport.reportDesktopResult(
                    chatId: action.chatId,
                    actionId: action.actionId,
                    status: outcome.status,
                    payload: Self.reportPayload(for: outcome)
                )
                // Server is now authoritative; the action leaves the queue.
                unreported[action.actionId] = nil
            } catch {
                // Keep the outcome so the next cycle retries the report instead
                // of re-running the side effect.
            }
        }
        return outcomes
    }

    /// The result payload to report: the captured UI for an observe, a generic
    /// reason for a refusal/failure, or nothing for a plain executed action.
    private static func reportPayload(
        for outcome: DesktopActuationOutcome
    ) -> [String: CompanionJSONValue]? {
        if let snapshot = outcome.snapshot {
            if let value = try? encodeToJSONValue(snapshot) {
                return ["snapshot": value]
            }
            return nil
        }
        return outcome.reason.map { ["reason": .string($0)] }
    }

    private static func encodeToJSONValue<T: Encodable>(_ value: T) throws -> CompanionJSONValue {
        let data = try JSONEncoder().encode(value)
        return try JSONDecoder().decode(CompanionJSONValue.self, from: data)
    }
}

extension APIClient: MacEdgeTransport {}
