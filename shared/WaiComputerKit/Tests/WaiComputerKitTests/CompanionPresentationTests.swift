import XCTest
@testable import WaiComputerKit

final class CompanionPresentationTests: XCTestCase {
    func testUntitledThreadLabelUsesLocalizedDateFallback() {
        let created = Date(timeIntervalSince1970: 1_768_545_600) // 2026-01-14T00:00:00Z
        let label = CompanionChatPresentation.chatLabel(
            title: nil,
            createdAt: created,
            lastMessageAt: nil,
            locale: Locale(identifier: "ru_RU")
        )

        XCTAssertTrue(label.hasPrefix("Диалог · "))
        XCTAssertFalse(label.contains("Untitled"))
    }

    func testChatLabelUsesNonEmptyServerTitle() {
        let created = Date(timeIntervalSince1970: 1_768_545_600)
        let label = CompanionChatPresentation.chatLabel(
            title: "   Pricing follow-ups   ",
            createdAt: created,
            lastMessageAt: nil,
            locale: Locale(identifier: "en_US")
        )

        XCTAssertEqual(label, "Pricing follow-ups")
    }

    func testComposerMetricsKeepPlaceholderAndEditorInsetsAligned() {
        XCTAssertEqual(
            CompanionComposerMetrics.textInsets,
            CompanionComposerMetrics.placeholderInsets
        )
        XCTAssertGreaterThanOrEqual(CompanionComposerMetrics.minHeight, 44)
        XCTAssertGreaterThan(
            CompanionComposerMetrics.maxHeight,
            CompanionComposerMetrics.minHeight
        )
    }

    func testFormatTokenCount() {
        XCTAssertEqual(CompanionChatPresentation.formatTokenCount(0), "0")
        XCTAssertEqual(CompanionChatPresentation.formatTokenCount(999), "999")
        XCTAssertEqual(CompanionChatPresentation.formatTokenCount(1000), "1.0k")
        XCTAssertEqual(CompanionChatPresentation.formatTokenCount(1234), "1.2k")
        XCTAssertEqual(CompanionChatPresentation.formatTokenCount(272000), "272.0k")
    }

    // MARK: - Turn timeline reducer

    private func reduce(_ events: [CompanionStreamEvent]) -> CompanionTurnReducer {
        var reducer = CompanionTurnReducer()
        for event in events { reducer.ingest(event) }
        return reducer
    }

    func testReducerCoalescesThinkingAndTokenDeltas() {
        let reducer = reduce([
            .thinking(text: "Let me "),
            .thinking(text: "think."),
            .token(text: "Hello "),
            .token(text: "world."),
        ])
        XCTAssertEqual(reducer.items.count, 2)
        guard case .thinking(_, let thought) = reducer.items[0] else {
            return XCTFail("expected thinking block")
        }
        XCTAssertEqual(thought, "Let me think.")
        guard case .text(_, let markdown) = reducer.items[1] else {
            return XCTFail("expected text block")
        }
        XCTAssertEqual(markdown, "Hello world.")
    }

    func testReducerGroupsToolCallsAndAppliesResults() {
        let reducer = reduce([
            .toolCall(callId: "a", tool: "search"),
            .toolCall(callId: "b", tool: "web_search"),
            .toolResult(callId: "a", summary: "3 results", ok: true),
            .toolResult(callId: "b", summary: "Failed", ok: false),
        ])
        XCTAssertEqual(reducer.items.count, 1)
        guard case .tools(_, let actions) = reducer.items[0] else {
            return XCTFail("expected one grouped tools card")
        }
        XCTAssertEqual(actions.count, 2)
        XCTAssertEqual(actions[0].summary, "3 results")
        XCTAssertEqual(actions[0].ok, true)
        XCTAssertFalse(actions[0].isRunning)
        XCTAssertEqual(actions[1].ok, false)
        XCTAssertFalse(reducer.hasRunningTool)
    }

    func testReducerSplitsToolGroupsAroundText() {
        let reducer = reduce([
            .toolCall(callId: "a", tool: "search"),
            .token(text: "Working…"),
            .toolCall(callId: "b", tool: "search"),
        ])
        XCTAssertEqual(reducer.items.count, 3)
        if case .tools = reducer.items[0] {} else { XCTFail("0 should be tools") }
        if case .text = reducer.items[1] {} else { XCTFail("1 should be text") }
        if case .tools = reducer.items[2] {} else { XCTFail("2 should be tools") }
    }

    func testReducerUpdatesPlanInPlace() {
        let reducer = reduce([
            .plan(steps: [CompanionPlanStep(title: "A", status: "in_progress")]),
            .token(text: "…"),
            .plan(steps: [
                CompanionPlanStep(title: "A", status: "done"),
                CompanionPlanStep(title: "B", status: "in_progress"),
            ]),
        ])
        let planItems = reducer.items.filter {
            if case .plan = $0 { return true }
            return false
        }
        XCTAssertEqual(planItems.count, 1)
        guard case .plan(_, let steps) = planItems[0] else {
            return XCTFail("expected plan card")
        }
        XCTAssertEqual(steps.count, 2)
        XCTAssertEqual(steps[0].status, "done")
    }

    func testReducerResolvesActionProposal() {
        let proposal = CompanionActionProposal(
            actionId: "act1",
            kind: "send",
            tool: "send_message_telegram",
            preview: "Send hi",
            expiresAt: "2026-06-05T10:00:00Z",
            recipient: "you"
        )
        let reducer = reduce([
            .actionProposed(proposal),
            .actionResult(actionId: "act1", status: "executed", detail: "sent", undoToken: nil),
        ])
        XCTAssertEqual(reducer.items.count, 1)
        guard case .action(_, let resolved, let resolution) = reducer.items[0] else {
            return XCTFail("expected action card")
        }
        XCTAssertEqual(resolved.actionId, "act1")
        XCTAssertEqual(resolution, .resolved(status: "executed", detail: "sent"))
    }

    func testReducerDedupesCitationsAndIgnoresControlEvents() {
        let citation = CompanionStreamCitation(
            index: 1, segmentId: "s1", recordingId: "r1",
            startMs: 0, endMs: 1, spanStart: 0, spanEnd: 5
        )
        let reducer = reduce([
            .turnStart(messageId: "m", conversationId: "c"),
            .citation(citation),
            .citation(citation),
            .done(messageId: "m", model: "gpt", latencyMs: 1),
        ])
        XCTAssertEqual(reducer.citations.count, 1)
        XCTAssertTrue(reducer.items.isEmpty)
    }

    func testFailRunningToolsMarksPendingAsFailed() {
        var reducer = reduce([.toolCall(callId: "a", tool: "search")])
        XCTAssertTrue(reducer.hasRunningTool)
        reducer.failRunningTools(summary: "Stopped")
        XCTAssertFalse(reducer.hasRunningTool)
        guard case .tools(_, let actions) = reducer.items[0] else {
            return XCTFail("expected tools card")
        }
        XCTAssertEqual(actions[0].ok, false)
        XCTAssertEqual(actions[0].summary, "Stopped")
    }
}
