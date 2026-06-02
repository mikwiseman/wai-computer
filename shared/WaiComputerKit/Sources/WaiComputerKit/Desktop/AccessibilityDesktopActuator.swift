#if canImport(AppKit)
import AppKit
import ApplicationServices
import Foundation

/// Tier-C actuator: native accessibility. Snapshots the focused app's UI into an
/// index-addressed ``DesktopUISnapshot`` and resolves ``click(index:)`` to an
/// `AXPress` on the real element; ``typeText(_:)`` sets the focused field's
/// value. Tier-A verbs (open URL/app) delegate to ``DeterministicDesktopActuator``.
///
/// Requires the Accessibility (AX) grant — WaiComputer already holds one for
/// dictation, so no new TCC prompt. Every AX failure (no grant, no focus,
/// unknown index, action error) is surfaced as a ``DesktopActuationError``; we
/// never report a click that did not happen (no silent success). `@MainActor`
/// because AX actions affect UI and must not race the snapshot's element map.
///
/// `click(index:)` resolves against the LAST ``snapshot()``; with no snapshot it
/// refuses (``elementNotInSnapshot``) rather than guessing.
@MainActor
public final class AccessibilityDesktopActuator: DesktopActuator {
    private let tierA = DeterministicDesktopActuator()
    private let maxElements: Int
    private var elementMap: [Int: AXUIElement] = [:]

    public init(maxElements: Int = 200) {
        self.maxElements = maxElements
    }

    // MARK: - Tier A (delegated, no AX grant needed)

    public func openURL(_ url: URL) async throws { try await tierA.openURL(url) }
    public func openApp(name: String) async throws { try await tierA.openApp(name: name) }

    // MARK: - Tier C (native accessibility)

    public func typeText(_ text: String) async throws {
        guard AXIsProcessTrusted() else { throw DesktopActuationError.accessibilityNotTrusted }
        let systemWide = AXUIElementCreateSystemWide()
        guard let focused = Self.copyAttr(systemWide, kAXFocusedUIElementAttribute) else {
            throw DesktopActuationError.noFocusedElement
        }
        let element = focused as! AXUIElement
        let err = AXUIElementSetAttributeValue(
            element, kAXValueAttribute as CFString, text as CFTypeRef
        )
        guard err == .success else { throw DesktopActuationError.axActionFailed }
    }

    public func click(index: Int) async throws {
        guard AXIsProcessTrusted() else { throw DesktopActuationError.accessibilityNotTrusted }
        guard let element = elementMap[index] else {
            throw DesktopActuationError.elementNotInSnapshot
        }
        let err = AXUIElementPerformAction(element, kAXPressAction as CFString)
        guard err == .success else { throw DesktopActuationError.axActionFailed }
    }

    /// Walk the frontmost app's accessibility tree into an index-addressed
    /// snapshot and remember the index→element map for a later ``click(index:)``.
    public func snapshot() async throws -> DesktopUISnapshot {
        guard AXIsProcessTrusted() else { throw DesktopActuationError.accessibilityNotTrusted }
        guard let app = NSWorkspace.shared.frontmostApplication else {
            throw DesktopActuationError.noFrontmostApp
        }
        let root = AXUIElementCreateApplication(app.processIdentifier)
        var elements: [DesktopUIElement] = []
        var map: [Int: AXUIElement] = [:]
        var queue: [AXUIElement] = [root]
        var nextIndex = 0
        while !queue.isEmpty, elements.count < maxElements {
            let node = queue.removeFirst()
            let role = Self.string(node, kAXRoleAttribute) ?? ""
            // The app root is a container only — descend, but don't list it.
            if !role.isEmpty, role != (kAXApplicationRole as String) {
                let title =
                    Self.string(node, kAXTitleAttribute)
                    ?? Self.string(node, kAXValueAttribute)
                    ?? Self.string(node, kAXDescriptionAttribute) ?? ""
                elements.append(
                    DesktopUIElement(
                        index: nextIndex,
                        role: role,
                        title: title,
                        actionable: Self.isActionable(node)
                    )
                )
                map[nextIndex] = node
                nextIndex += 1
            }
            queue.append(contentsOf: Self.children(node))
        }
        elementMap = map
        return DesktopUISnapshot(app: app.localizedName, elements: elements)
    }

    // MARK: - AX helpers

    private static func copyAttr(_ element: AXUIElement, _ attribute: String) -> CFTypeRef? {
        var value: CFTypeRef?
        let err = AXUIElementCopyAttributeValue(element, attribute as CFString, &value)
        return err == .success ? value : nil
    }

    private static func string(_ element: AXUIElement, _ attribute: String) -> String? {
        copyAttr(element, attribute) as? String
    }

    private static func children(_ element: AXUIElement) -> [AXUIElement] {
        guard let value = copyAttr(element, kAXChildrenAttribute) else { return [] }
        return value as? [AXUIElement] ?? []
    }

    private static func isActionable(_ element: AXUIElement) -> Bool {
        var actions: CFArray?
        let err = AXUIElementCopyActionNames(element, &actions)
        guard err == .success, let names = actions as? [String] else { return false }
        return names.contains(kAXPressAction as String)
    }
}
#endif
