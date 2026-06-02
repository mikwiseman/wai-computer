import Foundation

/// One element in a desktop UI snapshot, addressed by a stable index. The cloud
/// brain never sees raw accessibility handles — it sees this index-based list,
/// picks a target, and emits `desktop_click(index)`; the Mac maps the index back
/// to the real element. (OpenAI/computer-use-style index addressing — far
/// cheaper and more robust than coordinates.)
public struct DesktopUIElement: Sendable, Equatable, Codable {
    public let index: Int
    public let role: String  // e.g. "AXButton", "AXTextField", "AXMenuItem"
    public let title: String  // accessibility title/label/value (may be empty)
    public let actionable: Bool  // supports a press/activate action

    public init(index: Int, role: String, title: String, actionable: Bool) {
        self.index = index
        self.role = role
        self.title = title
        self.actionable = actionable
    }
}

/// A point-in-time, index-addressed view of the focused app's accessible UI.
/// The Mac produces it; the brain reads ``modelDigest`` to choose a target; the
/// actuator resolves an index back to its element via ``element(at:)``.
public struct DesktopUISnapshot: Sendable, Equatable, Codable {
    public let app: String?  // frontmost app name/bundle, for the model's context
    public let elements: [DesktopUIElement]

    public init(app: String? = nil, elements: [DesktopUIElement]) {
        self.app = app
        self.elements = elements
    }

    /// The element at a model-provided index, or nil if out of range. The
    /// actuator must treat nil as a refusal (never click an unknown element).
    public func element(at index: Int) -> DesktopUIElement? {
        guard index >= 0, index < elements.count else { return nil }
        return elements[index]
    }

    /// A compact, privacy-bounded rendering for the model: one line per element
    /// as `index: role "title"`. Titles are truncated and, by default, only
    /// actionable elements are listed — enough to choose a target without
    /// dumping the whole tree (token + privacy bound).
    public func modelDigest(maxTitleLength: Int = 60, actionableOnly: Bool = true) -> String {
        elements
            .filter { !actionableOnly || $0.actionable }
            .map { element in
                let trimmed = element.title.trimmingCharacters(in: .whitespacesAndNewlines)
                let title =
                    trimmed.count > maxTitleLength
                    ? String(trimmed.prefix(maxTitleLength)) + "…"
                    : trimmed
                return title.isEmpty
                    ? "\(element.index): \(element.role)"
                    : "\(element.index): \(element.role) \"\(title)\""
            }
            .joined(separator: "\n")
    }
}
