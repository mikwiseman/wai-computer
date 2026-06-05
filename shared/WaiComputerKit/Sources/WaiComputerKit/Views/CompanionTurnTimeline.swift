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
/// plan checklist, streamed assistant markdown, and inline approval cards.
public enum CompanionTurnItem: Equatable, Identifiable, Sendable {
    case thinking(id: String, text: String)
    case tools(id: String, actions: [CompanionToolAction])
    case plan(id: String, steps: [CompanionPlanStep])
    case artifact(id: String, artifact: CompanionArtifact)
    case text(id: String, markdown: String)
    case action(id: String, proposal: CompanionActionProposal, resolution: CompanionActionResolution?)

    public var id: String {
        switch self {
        case .thinking(let id, _): return id
        case .tools(let id, _): return id
        case .plan(let id, _): return id
        case .artifact(let id, _): return id
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
