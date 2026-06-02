import Foundation

/// Host-enforced guardrails for native computer-use, evaluated BEFORE any
/// accessibility action runs. Pure value logic (no AX) so it is fully tested;
/// the actuator that executes a command must consult it and refuse on a
/// non-allow decision. Non-negotiable: the agent may never drive WaiComputer's
/// own UI (so it cannot click its own approval dialog), and a set of dangerous
/// verbs is refused outright regardless of approval.
public struct DesktopCommandRequest: Sendable, Equatable {
    public let verb: String         // open | type | click | read | scroll | delete | ...
    public let bundleId: String?    // target app bundle id (nil for a URL/file open)

    public init(verb: String, bundleId: String? = nil) {
        self.verb = verb
        self.bundleId = bundleId
    }
}

public enum DesktopDecision: Sendable, Equatable {
    case allow
    case refuse(reason: String)

    public var isAllowed: Bool {
        if case .allow = self { return true }
        return false
    }
}

public struct DesktopSafetyPolicy: Sendable {
    public let ownBundleId: String
    public let blockedBundleIds: Set<String>
    public let refusedVerbs: Set<String>

    /// Verbs the actuator never performs even with approval — irreversible or
    /// high-blast-radius actions are not part of the computer-use surface.
    public static let defaultRefusedVerbs: Set<String> = [
        "delete", "purchase", "pay", "charge", "keychain", "erase", "format",
    ]

    public init(
        ownBundleId: String,
        blockedBundleIds: Set<String> = [],
        refusedVerbs: Set<String> = DesktopSafetyPolicy.defaultRefusedVerbs
    ) {
        self.ownBundleId = ownBundleId
        self.blockedBundleIds = blockedBundleIds
        self.refusedVerbs = refusedVerbs
    }

    public func decide(_ command: DesktopCommandRequest) -> DesktopDecision {
        if let bundleId = command.bundleId {
            // Own-UI exclusion — the agent can never drive WaiComputer itself
            // (and thus can never click its own approval dialog).
            if bundleId == ownBundleId {
                return .refuse(reason: "own UI is excluded from actuation")
            }
            if blockedBundleIds.contains(bundleId) {
                return .refuse(reason: "target app is blocked")
            }
        }
        if refusedVerbs.contains(command.verb.lowercased()) {
            return .refuse(reason: "verb '\(command.verb)' is not permitted")
        }
        return .allow
    }
}
