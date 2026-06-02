#if canImport(AppKit)
import AppKit
import Foundation

/// Tier-A deterministic actuator (plan P4): opens URLs and launches apps via
/// `NSWorkspace`, which requires no Accessibility grant. This is the cheapest,
/// lowest-risk path and handles the flagship "open email and write to X" via a
/// Gmail/`mailto:` compose URL. Tier-C verbs (type/click) need the native
/// accessibility actuator and are NOT served here — they throw so the failure
/// is surfaced rather than silently degrading to another tier.
public struct DeterministicDesktopActuator: DesktopActuator {
    public init() {}

    public func openURL(_ url: URL) async throws {
        guard NSWorkspace.shared.open(url) else {
            throw DesktopActuationError.openFailed
        }
    }

    public func openApp(name: String) async throws {
        guard let appURL = Self.applicationURL(forName: name) else {
            throw DesktopActuationError.appNotFound
        }
        let configuration = NSWorkspace.OpenConfiguration()
        _ = try await NSWorkspace.shared.openApplication(at: appURL, configuration: configuration)
    }

    public func typeText(_ text: String) async throws {
        throw DesktopActuationError.tierUnavailable("type requires the accessibility actuator")
    }

    public func click(index: Int) async throws {
        throw DesktopActuationError.tierUnavailable("click requires the accessibility actuator")
    }

    /// Resolve a bare app name to a bundle URL deterministically, without
    /// deprecated launch-by-name APIs: an absolute path is used directly,
    /// otherwise the standard application directories are searched.
    static func applicationURL(forName name: String) -> URL? {
        let fileManager = FileManager.default
        if name.hasPrefix("/") {
            let url = URL(fileURLWithPath: name)
            return fileManager.fileExists(atPath: url.path) ? url : nil
        }
        let bundleName = name.hasSuffix(".app") ? name : "\(name).app"
        let directories = [
            "/Applications", "/System/Applications", "/System/Applications/Utilities",
        ]
        for directory in directories {
            let candidate = URL(fileURLWithPath: directory).appendingPathComponent(bundleName)
            if fileManager.fileExists(atPath: candidate.path) { return candidate }
        }
        return nil
    }
}

public enum DesktopActuationError: Error, Sendable, Equatable {
    case openFailed
    case appNotFound
    /// A verb that this tier cannot perform; the caller surfaces it.
    case tierUnavailable(String)
}
#endif
