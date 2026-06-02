import Foundation

/// The platform seam for performing a planned desktop action. The Tier-A
/// deterministic conformance wraps `NSWorkspace`; the Tier-C conformance wraps
/// the native accessibility actuator (AXorcist). Kept as a protocol so the
/// orchestration in ``DesktopActionExecutor`` is fully testable without a real
/// Mac, and so a failure in any tier surfaces as a thrown error (no silent
/// fallback to another tier).
public protocol DesktopActuator: Sendable {
    func openURL(_ url: URL) async throws
    func openApp(name: String) async throws
    func typeText(_ text: String) async throws
    func click(index: Int) async throws
}

/// Outcome of executing one drained action, mapped to the wire status reported
/// back over the Mac-edge channel. Reasons are generic categories only — never
/// the raw target, typed text, or underlying error string (privacy-safe).
public enum DesktopActuationOutcome: Sendable, Equatable {
    case executed
    case refused(reason: String)
    case failed(reason: String)

    public var status: DesktopResultStatus {
        switch self {
        case .executed: return .executed
        case .refused: return .refused
        case .failed: return .failed
        }
    }

    public var reason: String? {
        switch self {
        case .executed: return nil
        case .refused(let reason), .failed(let reason): return reason
        }
    }
}

/// Orchestrates one approved desktop action end to end: plan via the router
/// (which applies the safety policy), dispatch to the actuator, and map the
/// result to a wire status. The caller drains the action, runs `execute`, and
/// reports `outcome.status` back to the cloud.
public struct DesktopActionExecutor: Sendable {
    public let router: DesktopActionRouter
    public let actuator: DesktopActuator

    public init(router: DesktopActionRouter, actuator: DesktopActuator) {
        self.router = router
        self.actuator = actuator
    }

    public func execute(_ item: DesktopActionItem) async -> DesktopActuationOutcome {
        let plan = router.plan(tool: item.tool, args: item.args)
        switch plan {
        case .refuse(let reason):
            return .refused(reason: reason)
        case .openURL(let url):
            return await perform("could not open target") { try await actuator.openURL(url) }
        case .openApp(let name):
            return await perform("could not open app") { try await actuator.openApp(name: name) }
        case .typeText(let text):
            return await perform("could not type") { try await actuator.typeText(text) }
        case .click(let index):
            return await perform("could not click") { try await actuator.click(index: index) }
        }
    }

    private func perform(
        _ failureReason: String, _ body: () async throws -> Void
    ) async -> DesktopActuationOutcome {
        do {
            try await body()
            return .executed
        } catch {
            // Generic category only — the raw error may carry the target.
            return .failed(reason: failureReason)
        }
    }
}
