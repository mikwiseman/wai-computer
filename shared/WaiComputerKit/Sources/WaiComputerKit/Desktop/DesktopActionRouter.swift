import Foundation

/// Maps an approved desktop action drained from the Mac-edge channel to a
/// concrete execution plan, applying ``DesktopSafetyPolicy`` first. This is the
/// cheapest-first tier decision (plan P4): a `desktop_open` resolves to a
/// deterministic, zero-permission `NSWorkspace` open (Tier A); `desktop_type`/
/// `desktop_click` resolve to accessibility actions (Tier C). Pure value logic
/// with no platform calls, so it is fully testable; the executor performs the
/// side-effect that matches the returned plan and surfaces any failure (no
/// silent tier fallback).
public enum DesktopExecutionPlan: Sendable, Equatable {
    /// Tier A — open a URL (mailto/compose/https) with `NSWorkspace.open`.
    case openURL(URL)
    /// Tier A — launch an app by name with `NSWorkspace`.
    case openApp(name: String)
    /// Tier C — type into the focused field via accessibility.
    case typeText(String)
    /// Tier C — click an element by snapshot index via accessibility.
    case click(index: Int)
    /// Tier C — observe the focused app's UI (the brain's "look" step).
    case snapshot
    /// The action is not permitted or is malformed; surfaced to the user.
    case refuse(reason: String)

    public var isRefusal: Bool {
        if case .refuse = self { return true }
        return false
    }
}

public struct DesktopActionRouter: Sendable {
    public let safety: DesktopSafetyPolicy
    public let allowedURLSchemes: Set<String>

    /// Tier-A deterministic surface: a Gmail/compose `mailto:` or a web URL.
    /// Anything else (e.g. `javascript:` or local `file:`) is refused — opening
    /// it is neither low-risk nor deterministic without a narrower policy.
    public static let defaultAllowedURLSchemes: Set<String> = [
        "mailto", "http", "https",
    ]

    public init(
        safety: DesktopSafetyPolicy,
        allowedURLSchemes: Set<String> = DesktopActionRouter.defaultAllowedURLSchemes
    ) {
        self.safety = safety
        self.allowedURLSchemes = allowedURLSchemes
    }

    public func plan(tool: String, args: [String: CompanionJSONValue]) -> DesktopExecutionPlan {
        switch tool {
        case "desktop_open":
            return planOpen(args)
        case "desktop_type":
            guard case .string(let text)? = args["text"], !text.isEmpty else {
                return .refuse(reason: "missing text to type")
            }
            return gated(verb: "type", bundleId: nil) { .typeText(text) }
        case "desktop_click":
            guard let index = intArg(args["index"]) else {
                return .refuse(reason: "missing element index")
            }
            return gated(verb: "click", bundleId: nil) { .click(index: index) }
        case "desktop_snapshot":
            return gated(verb: "snapshot", bundleId: nil) { .snapshot }
        default:
            return .refuse(reason: "unknown desktop tool '\(tool)'")
        }
    }

    // MARK: - Private

    private func planOpen(_ args: [String: CompanionJSONValue]) -> DesktopExecutionPlan {
        guard case .string(let raw)? = args["target"] else {
            return .refuse(reason: "missing open target")
        }
        let target = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !target.isEmpty else {
            return .refuse(reason: "missing open target")
        }
        // A target with a URL scheme is a URL open; a bare string is an app name.
        if let scheme = urlScheme(of: target) {
            guard allowedURLSchemes.contains(scheme) else {
                return .refuse(reason: "URL scheme '\(scheme)' is not permitted")
            }
            guard let url = URL(string: target) else {
                return .refuse(reason: "malformed URL")
            }
            return gated(verb: "open", bundleId: nil) { .openURL(url) }
        }
        return gated(verb: "open", bundleId: nil) { .openApp(name: target) }
    }

    /// Run the safety policy for a verb/app and produce the plan only on allow;
    /// otherwise surface the policy's refusal reason verbatim.
    private func gated(
        verb: String, bundleId: String?, _ makePlan: () -> DesktopExecutionPlan
    ) -> DesktopExecutionPlan {
        let decision = safety.decide(DesktopCommandRequest(verb: verb, bundleId: bundleId))
        switch decision {
        case .allow:
            return makePlan()
        case .refuse(let reason):
            return .refuse(reason: reason)
        }
    }

    /// A scheme like "mailto" / "https" if `target` starts with `<scheme>:`,
    /// else nil (a bare app name such as "Mail"). Mirrors `URLComponents`
    /// without requiring `//`, so `mailto:` is recognised.
    private func urlScheme(of target: String) -> String? {
        guard let colon = target.firstIndex(of: ":") else { return nil }
        let scheme = target[target.startIndex..<colon]
        guard !scheme.isEmpty else { return nil }
        // A scheme is alphanumerics plus +/-/. (RFC 3986); a drive-letter path
        // or a stray colon in an app name should not read as a scheme.
        let valid = scheme.allSatisfy { $0.isLetter || $0.isNumber || $0 == "+" || $0 == "-" || $0 == "." }
        guard valid, scheme.first?.isLetter == true else { return nil }
        return scheme.lowercased()
    }

    private func intArg(_ value: CompanionJSONValue?) -> Int? {
        switch value {
        case .int(let i): return i
        case .double(let d): return Int(d)
        default: return nil
        }
    }
}
