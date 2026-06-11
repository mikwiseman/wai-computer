import Foundation

/// A single hosted-read tool invocation (brain query / web search) within a
/// "Tool actions" card. `summary == nil` means it is still running.
public struct CompanionToolAction: Equatable, Identifiable, Sendable {
    public let callId: String
    public var tool: String
    public var summary: String?
    public var ok: Bool?

    public var id: String { callId }
    public var isRunning: Bool { summary == nil }

    public init(callId: String, tool: String, summary: String? = nil, ok: Bool? = nil) {
        self.callId = callId
        self.tool = tool
        self.summary = summary
        self.ok = ok
    }
}

/// The outcome of a proposed action once the user resolves it.
public enum CompanionActionResolution: Equatable, Sendable {
    case executing
    case resolved(status: String, detail: String)
}

/// One rendered block within an assistant turn. The SSE event stream is folded
/// into an ordered list of these so the client can render openclaw-style cards:
/// a collapsible Thinking block, a grouped "Tool actions · N steps" card, a live
/// plan checklist, web source links, streamed assistant markdown, and inline
/// approval cards.
public enum CompanionTurnItem: Equatable, Identifiable, Sendable {
    case thinking(id: String, text: String)
    case tools(id: String, actions: [CompanionToolAction])
    case plan(id: String, steps: [CompanionPlanStep])
    case artifact(id: String, artifact: CompanionArtifact)
    case webCitations(id: String, citations: [CompanionWebCitation])
    case text(id: String, markdown: String)
    case action(id: String, proposal: CompanionActionProposal, resolution: CompanionActionResolution?)

    public var id: String {
        switch self {
        case .thinking(let id, _): return id
        case .tools(let id, _): return id
        case .plan(let id, _): return id
        case .artifact(let id, _): return id
        case .webCitations(let id, _): return id
        case .text(let id, _): return id
        case .action(let id, _, _): return id
        }
    }
}

/// Folds the Companion SSE event stream into an ordered list of structured
/// timeline items. Pure + deterministic so the folding is unit-tested without
/// SwiftUI. Consecutive same-kind deltas (thinking text, assistant tokens)
/// coalesce into one block; consecutive tool calls group into one card; a plan
/// update replaces the existing plan card in place; an action result resolves
/// its proposal card.
public struct CompanionTurnReducer: Equatable, Sendable {
    public private(set) var items: [CompanionTurnItem] = []
    public private(set) var citations: [CompanionStreamCitation] = []
    private var counter: Int = 0

    public init() {}

    public var isEmpty: Bool { items.isEmpty && citations.isEmpty }

    public static func storedItems(from toolCalls: [CompanionJSONValue]?) -> [CompanionTurnItem] {
        guard let toolCalls else { return [] }

        var items: [CompanionTurnItem] = []
        for call in toolCalls {
            guard case .object(let object) = call else { continue }
            if object["type"]?.stringValue == "tools",
                let actions = storedToolActions(from: object["actions"]) {
                items.append(.tools(id: "stored-tools-\(items.count)", actions: actions))
            } else if object["type"]?.stringValue == "web_citations",
                let citations = storedWebCitations(from: object["citations"]) {
                items.append(.webCitations(
                    id: "stored-web-citations-\(items.count)",
                    citations: citations
                ))
            } else if object["type"]?.stringValue == "artifact",
                let artifactId = object["artifact_id"]?.stringValue,
                let title = object["title"]?.stringValue,
                let kind = object["kind"]?.stringValue,
                let content = object["content"]?.stringValue {
                items.append(.artifact(
                    id: "stored-artifact-\(artifactId)",
                    artifact: CompanionArtifact(
                        artifactId: artifactId,
                        title: title,
                        kind: kind,
                        content: content,
                        language: object["language"]?.stringValue ?? ""
                    )
                ))
            } else if object["type"]?.stringValue == "action_proposed",
                let actionId = object["action_id"]?.stringValue,
                let kind = object["kind"]?.stringValue,
                let tool = object["tool"]?.stringValue,
                let preview = object["preview"]?.stringValue,
                let expiresAt = object["expires_at"]?.stringValue {
                items.append(.action(
                    id: "stored-action-\(actionId)",
                    proposal: CompanionActionProposal(
                        actionId: actionId,
                        kind: kind,
                        tool: tool,
                        preview: preview,
                        expiresAt: expiresAt,
                        recipient: object["recipient"]?.stringValue
                    ),
                    resolution: storedActionResolution(from: object["resolution"])
                ))
            } else if object["type"]?.stringValue == "plan",
                let steps = storedPlanSteps(from: object["steps"]) {
                items.append(.plan(id: "stored-plan-\(items.count)", steps: steps))
            }
        }
        return items
    }

    private static func storedToolActions(
        from value: CompanionJSONValue?
    ) -> [CompanionToolAction]? {
        guard case .array(let rawActions) = value else { return nil }
        let actions = rawActions.compactMap { rawAction -> CompanionToolAction? in
            guard case .object(let object) = rawAction,
                  let callId = object["call_id"]?.stringValue,
                  let tool = object["tool"]?.stringValue
            else { return nil }

            let summary: String?
            switch object["summary"] {
            case .some(.string(let value)):
                summary = value
            case .some(.null), .none:
                summary = nil
            default:
                return nil
            }

            let ok: Bool?
            switch object["ok"] {
            case .some(.bool(let value)):
                ok = value
            case .some(.null), .none:
                ok = nil
            default:
                return nil
            }

            return CompanionToolAction(callId: callId, tool: tool, summary: summary, ok: ok)
        }
        return actions.isEmpty ? nil : actions
    }

    private static func storedWebCitations(
        from value: CompanionJSONValue?
    ) -> [CompanionWebCitation]? {
        guard case .array(let rawCitations) = value else { return nil }
        let citations = rawCitations.compactMap { rawCitation -> CompanionWebCitation? in
            guard case .object(let object) = rawCitation,
                  let title = object["title"]?.stringValue,
                  let url = object["url"]?.stringValue
            else { return nil }

            return CompanionWebCitation(
                title: title,
                url: url,
                startIndex: intValue(from: object["start_index"]),
                endIndex: intValue(from: object["end_index"])
            )
        }
        return citations.isEmpty ? nil : citations
    }

    private static func intValue(from value: CompanionJSONValue?) -> Int? {
        switch value {
        case .some(.int(let value)):
            return value
        case .some(.double(let value)):
            return Int(value)
        default:
            return nil
        }
    }

    public static func toolCalls(
        _ toolCalls: [CompanionJSONValue]?,
        settingActionResolution actionId: String,
        resolution: CompanionActionResolution
    ) -> [CompanionJSONValue]? {
        guard let toolCalls else { return nil }

        var changed = false
        let resolutionPayload = storedActionResolutionPayload(resolution)
        let next = toolCalls.map { call -> CompanionJSONValue in
            guard case .object(var object) = call,
                  object["type"]?.stringValue == "action_proposed",
                  object["action_id"]?.stringValue == actionId
            else { return call }

            object["resolution"] = resolutionPayload
            changed = true
            return .object(object)
        }
        return changed ? next : toolCalls
    }

    private static func storedActionResolution(
        from value: CompanionJSONValue?
    ) -> CompanionActionResolution? {
        guard case .object(let object) = value else { return nil }
        if object["state"]?.stringValue == "executing" {
            return .executing
        }
        guard object["state"]?.stringValue == "resolved",
              let status = object["status"]?.stringValue,
              let detail = object["detail"]?.stringValue
        else { return nil }
        return .resolved(status: status, detail: detail)
    }

    private static func storedPlanSteps(
        from value: CompanionJSONValue?
    ) -> [CompanionPlanStep]? {
        guard case .array(let rawSteps) = value else { return nil }
        let steps = rawSteps.compactMap { rawStep -> CompanionPlanStep? in
            guard case .object(let object) = rawStep,
                  let title = object["title"]?.stringValue,
                  let status = object["status"]?.stringValue
            else { return nil }
            return CompanionPlanStep(title: title, status: status)
        }
        return steps.isEmpty ? nil : steps
    }

    private static func storedActionResolutionPayload(
        _ resolution: CompanionActionResolution
    ) -> CompanionJSONValue {
        switch resolution {
        case .executing:
            return .object(["state": .string("executing")])
        case .resolved(let status, let detail):
            return .object([
                "state": .string("resolved"),
                "status": .string(status),
                "detail": .string(detail),
            ])
        }
    }

    /// True while at least one tool action is still running — used to keep the
    /// "Tool actions" card spinning.
    public var hasRunningTool: Bool {
        items.contains { item in
            if case .tools(_, let actions) = item {
                return actions.contains { $0.isRunning }
            }
            return false
        }
    }

    public func notificationPreview(maxCharacters: Int) -> String? {
        guard maxCharacters > 0 else { return nil }

        let markdown = items.compactMap { item -> String? in
            if case .text(_, let markdown) = item { return markdown }
            return nil
        }
        .joined(separator: " ")

        // Notification bodies are plain text (UNNotificationContent.body):
        // strip markdown so "**Итог:**" / "# Plan" never reach Notification
        // Center as literal symbols, then collapse whitespace and truncate.
        let text = Self.plainText(fromMarkdown: markdown)
            .split(whereSeparator: { $0.isWhitespace })
            .joined(separator: " ")

        guard !text.isEmpty else { return nil }
        guard text.count > maxCharacters else { return text }

        let ellipsis = "..."
        let characterLimit = max(maxCharacters - ellipsis.count, 1)
        let hardLimitIndex = text.index(text.startIndex, offsetBy: characterLimit)
        var prefix = String(text[..<hardLimitIndex]).trimmingCharacters(in: .whitespacesAndNewlines)
        if let lastSpace = prefix.lastIndex(of: " "), lastSpace > prefix.startIndex {
            prefix = String(prefix[..<lastSpace])
        }
        return "\(prefix)\(ellipsis)"
    }

    /// Markdown → plain text for one-line previews. Block syntax (heading
    /// hashes, list markers, blockquotes, code fences) is stripped line by
    /// line — inline parsing leaves it untouched — then inline syntax
    /// (bold/italic/code/links) is resolved via `AttributedString` with
    /// `.inlineOnlyPreservingWhitespace`, the kit's established parse mode.
    /// A parse failure keeps the block-stripped text, matching the kit's
    /// render-time markdown fallback.
    static func plainText(fromMarkdown markdown: String) -> String {
        let blockStripped = markdown
            .components(separatedBy: "\n")
            .compactMap { line -> String? in
                var stripped = line.trimmingCharacters(in: .whitespaces)
                // Drop code-fence lines themselves; fenced content stays.
                if stripped.hasPrefix("```") { return nil }
                // ATX heading hashes: "# Plan" -> "Plan".
                if stripped.hasPrefix("#") {
                    stripped = String(stripped.drop(while: { $0 == "#" }))
                        .trimmingCharacters(in: .whitespaces)
                }
                // Blockquote marker.
                if stripped.hasPrefix("> ") {
                    stripped = String(stripped.dropFirst(2))
                }
                // Unordered list markers.
                if stripped.hasPrefix("- ") || stripped.hasPrefix("* ") || stripped.hasPrefix("• ") {
                    stripped = String(stripped.dropFirst(2))
                } else if let dot = stripped.firstIndex(of: "."),
                    dot != stripped.startIndex,
                    stripped[stripped.startIndex..<dot].allSatisfy(\.isNumber),
                    stripped[dot...].hasPrefix(". ") {
                    // Ordered list markers: "1. Step" -> "Step".
                    stripped = String(stripped[stripped.index(dot, offsetBy: 2)...])
                }
                return stripped
            }
            .joined(separator: "\n")

        guard let attributed = try? AttributedString(
            markdown: blockStripped,
            options: AttributedString.MarkdownParsingOptions(
                interpretedSyntax: .inlineOnlyPreservingWhitespace
            )
        ) else { return blockStripped }
        return String(attributed.characters)
    }

    private mutating func nextId(_ prefix: String) -> String {
        counter += 1
        return "\(prefix)-\(counter)"
    }

    public mutating func ingest(_ event: CompanionStreamEvent) {
        switch event {
        case .thinking(let text):
            appendThinking(text)
        case .toolCall(let callId, let tool):
            appendToolCall(callId: callId, tool: tool)
        case .toolResult(let callId, let summary, let ok):
            applyToolResult(callId: callId, summary: summary, ok: ok)
        case .plan(let steps):
            upsertPlan(steps)
        case .artifact(let artifact):
            items.append(.artifact(id: nextId("artifact"), artifact: artifact))
        case .webCitations(let citations):
            appendWebCitations(citations)
        case .token(let text):
            appendText(text)
        case .citation(let citation):
            appendCitation(citation)
        case .actionProposed(let proposal):
            items.append(.action(id: nextId("action"), proposal: proposal, resolution: nil))
        case .actionResult(let actionId, let status, let detail, _):
            applyActionResult(actionId: actionId, status: status, detail: detail)
        case .turnStart, .memoryUpdated, .narration, .desktopAction, .done, .error:
            break
        }
    }

    /// Mark every still-running tool as failed — used when a turn is cancelled
    /// or errors so no spinner is left hanging.
    public mutating func failRunningTools(summary: String) {
        for index in items.indices {
            if case .tools(let id, var actions) = items[index] {
                var changed = false
                for actionIdx in actions.indices where actions[actionIdx].isRunning {
                    actions[actionIdx].summary = summary
                    actions[actionIdx].ok = false
                    changed = true
                }
                if changed { items[index] = .tools(id: id, actions: actions) }
            }
        }
    }

    /// Preserve an interrupted turn as visible, settled timeline state.
    public mutating func markInterrupted(summary: String) {
        failRunningTools(summary: summary)
        for index in items.indices {
            if case .plan(let id, let steps) = items[index],
               steps.contains(where: { $0.status == "in_progress" }) {
                items[index] = .plan(
                    id: id,
                    steps: steps.map { step in
                        if step.status == "in_progress" {
                            return CompanionPlanStep(title: step.title, status: "failed")
                        }
                        return step
                    }
                )
            }
        }
        let hasText = items.contains { item in
            if case .text(_, let markdown) = item {
                return !markdown.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            }
            return false
        }
        if !hasText {
            appendText(summary)
        }
    }

    /// Set the resolution on a proposed-action card by id. Returns false if no
    /// matching action card exists in this turn.
    @discardableResult
    public mutating func setActionResolution(
        actionId: String,
        resolution: CompanionActionResolution
    ) -> Bool {
        for index in items.indices.reversed() {
            if case .action(let id, let proposal, _) = items[index], proposal.actionId == actionId {
                items[index] = .action(id: id, proposal: proposal, resolution: resolution)
                return true
            }
        }
        return false
    }

    // MARK: - Folding

    private mutating func appendThinking(_ text: String) {
        if case .thinking(let id, let existing) = items.last {
            items[items.count - 1] = .thinking(id: id, text: existing + text)
        } else {
            items.append(.thinking(id: nextId("thinking"), text: text))
        }
    }

    private mutating func appendText(_ text: String) {
        if case .text(let id, let existing) = items.last {
            items[items.count - 1] = .text(id: id, markdown: existing + text)
        } else {
            items.append(.text(id: nextId("text"), markdown: text))
        }
    }

    private mutating func appendToolCall(callId: String, tool: String) {
        let action = CompanionToolAction(callId: callId, tool: tool)
        if case .tools(let id, var actions) = items.last {
            actions.append(action)
            items[items.count - 1] = .tools(id: id, actions: actions)
        } else {
            items.append(.tools(id: nextId("tools"), actions: [action]))
        }
    }

    private mutating func appendWebCitations(_ citations: [CompanionWebCitation]) {
        guard !citations.isEmpty else { return }
        items.append(.webCitations(id: nextId("web-citations"), citations: citations))
    }

    private mutating func applyToolResult(callId: String, summary: String, ok: Bool) {
        for index in items.indices.reversed() {
            if case .tools(let id, var actions) = items[index],
                let actionIdx = actions.lastIndex(where: { $0.callId == callId }) {
                actions[actionIdx].summary = summary
                actions[actionIdx].ok = ok
                items[index] = .tools(id: id, actions: actions)
                return
            }
        }
    }

    private mutating func upsertPlan(_ steps: [CompanionPlanStep]) {
        for index in items.indices {
            if case .plan(let id, _) = items[index] {
                items[index] = .plan(id: id, steps: steps)
                return
            }
        }
        items.append(.plan(id: nextId("plan"), steps: steps))
    }

    private mutating func applyActionResult(actionId: String, status: String, detail: String) {
        for index in items.indices.reversed() {
            if case .action(let id, let proposal, _) = items[index], proposal.actionId == actionId {
                items[index] = .action(
                    id: id,
                    proposal: proposal,
                    resolution: .resolved(status: status, detail: detail)
                )
                return
            }
        }
    }

    private mutating func appendCitation(_ citation: CompanionStreamCitation) {
        let isDuplicate = citations.contains {
            $0.index == citation.index
                && $0.segmentId == citation.segmentId
                && $0.spanStart == citation.spanStart
        }
        if !isDuplicate { citations.append(citation) }
    }
}
