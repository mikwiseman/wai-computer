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

    func testCompanionMarkdownRenderingCachesParsedBlocksForRepeatedRows() {
        let markdown = """
        # Answer

        - First **point**
        - Second `point`

        Final paragraph with [link](https://wai.computer).
        """

        CompanionMarkdownRenderer.resetCacheForTesting()

        _ = CompanionMarkdownRenderer.blocks(for: markdown)
        let firstBlockParses = CompanionMarkdownRenderer.blockParseCountForTesting
        let firstInlineParses = CompanionMarkdownRenderer.inlineParseCountForTesting

        _ = CompanionMarkdownRenderer.blocks(for: markdown)

        XCTAssertEqual(CompanionMarkdownRenderer.blockParseCountForTesting, firstBlockParses)
        XCTAssertEqual(CompanionMarkdownRenderer.inlineParseCountForTesting, firstInlineParses)
    }

    func testCompanionMarkdownRenderingBypassesCacheForLiveStreamingText() {
        let partialMarkdown = "Live **partial** response"

        CompanionMarkdownRenderer.resetCacheForTesting()

        _ = CompanionMarkdownRenderer.blocks(for: partialMarkdown, usingCache: false)
        _ = CompanionMarkdownRenderer.blocks(for: partialMarkdown + ".", usingCache: false)

        XCTAssertEqual(CompanionMarkdownRenderer.blockParseCountForTesting, 2)
        XCTAssertEqual(CompanionMarkdownRenderer.cachedBlockCountForTesting, 0)
        XCTAssertEqual(CompanionMarkdownRenderer.cachedInlineCountForTesting, 0)
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

    func testMarkInterruptedSettlesPlanAndAddsStoppedSummary() {
        var reducer = reduce([
            .plan(steps: [CompanionPlanStep(title: "Check sources", status: "in_progress")]),
            .toolCall(callId: "web-1", tool: "web_search"),
        ])

        reducer.markInterrupted(summary: "Stopped.")

        XCTAssertFalse(reducer.hasRunningTool)
        XCTAssertEqual(reducer.items.count, 3)
        guard case .plan(_, let steps) = reducer.items[0] else {
            return XCTFail("expected plan card")
        }
        XCTAssertEqual(steps, [CompanionPlanStep(title: "Check sources", status: "failed")])
        guard case .tools(_, let actions) = reducer.items[1] else {
            return XCTFail("expected tools card")
        }
        XCTAssertEqual(actions[0].summary, "Stopped.")
        XCTAssertEqual(actions[0].ok, false)
        guard case .text(_, let markdown) = reducer.items[2] else {
            return XCTFail("expected stopped text")
        }
        XCTAssertEqual(markdown, "Stopped.")
    }

    func testMarkInterruptedKeepsPartialText() {
        var reducer = reduce([
            .toolCall(callId: "web-1", tool: "web_search"),
            .token(text: "Partial answer"),
        ])

        reducer.markInterrupted(summary: "Stopped.")

        let texts = reducer.items.compactMap { item -> String? in
            if case .text(_, let markdown) = item { return markdown }
            return nil
        }
        XCTAssertEqual(texts, ["Partial answer"])
    }

    func testReducerAppendsArtifact() {
        let artifact = CompanionArtifact(
            artifactId: "a1", title: "Landing", kind: "html",
            content: "<h1>Hi</h1>", language: ""
        )
        let reducer = reduce([
            .thinking(text: "Building…"),
            .artifact(artifact),
            .token(text: "Done."),
        ])
        let arts = reducer.items.compactMap { item -> CompanionArtifact? in
            if case .artifact(_, let a) = item { return a }
            return nil
        }
        XCTAssertEqual(arts.count, 1)
        XCTAssertEqual(arts[0].kind, "html")
        XCTAssertEqual(arts[0].title, "Landing")
    }

    func testReducerAppendsWebCitations() {
        let citations = [
            CompanionWebCitation(
                title: "Serverless GPU Inference | Runpod",
                url: "https://www.runpod.io/serverless-gpu",
                startIndex: 4,
                endIndex: 10
            ),
        ]
        let reducer = reduce([
            .token(text: "Use Runpod."),
            .webCitations(citations),
        ])

        XCTAssertEqual(reducer.items.count, 2)
        guard case .webCitations(_, let restored) = reducer.items[1] else {
            return XCTFail("expected web citations item")
        }
        XCTAssertEqual(restored, citations)
    }

    func testStoredToolCallsRestoreArtifactTimelineItems() {
        let items = CompanionTurnReducer.storedItems(from: [
            .object([
                "type": .string("artifact"),
                "artifact_id": .string("call_1"),
                "title": .string("Landing"),
                "kind": .string("html"),
                "content": .string("<!doctype html><h1>Hi</h1>"),
                "language": .string(""),
            ]),
            .object([
                "type": .string("function_call"),
                "name": .string("web_search"),
            ]),
            .null,
        ])

        XCTAssertEqual(items.count, 1)
        guard case .artifact(let id, let artifact) = items[0] else {
            return XCTFail("expected stored artifact item")
        }
        XCTAssertEqual(id, "stored-artifact-call_1")
        XCTAssertEqual(artifact.artifactId, "call_1")
        XCTAssertEqual(artifact.title, "Landing")
        XCTAssertEqual(artifact.kind, "html")
        XCTAssertEqual(artifact.content, "<!doctype html><h1>Hi</h1>")
    }

    func testStoredToolCallsRestoreActionTimelineItems() {
        let items = CompanionTurnReducer.storedItems(from: [
            .object([
                "type": .string("action_proposed"),
                "action_id": .string("act1"),
                "kind": .string("send"),
                "tool": .string("send_message_telegram"),
                "preview": .string("Send Telegram message to your linked chat: late"),
                "expires_at": .string("2026-06-05T12:40:00+00:00"),
                "recipient": .string("you"),
            ]),
        ])

        XCTAssertEqual(items.count, 1)
        guard case .action(let id, let proposal, let resolution) = items[0] else {
            return XCTFail("expected stored action item")
        }
        XCTAssertEqual(id, "stored-action-act1")
        XCTAssertEqual(proposal.actionId, "act1")
        XCTAssertEqual(proposal.kind, "send")
        XCTAssertEqual(proposal.tool, "send_message_telegram")
        XCTAssertEqual(proposal.preview, "Send Telegram message to your linked chat: late")
        XCTAssertEqual(proposal.expiresAt, "2026-06-05T12:40:00+00:00")
        XCTAssertEqual(proposal.recipient, "you")
        XCTAssertNil(resolution)
    }

    func testStoredToolCallsApplyActionResolution() {
        let toolCalls: [CompanionJSONValue] = [
            .object([
                "type": .string("action_proposed"),
                "action_id": .string("act1"),
                "kind": .string("send"),
                "tool": .string("send_message_telegram"),
                "preview": .string("Send Telegram message to your linked chat: late"),
                "expires_at": .string("2026-06-05T12:40:00+00:00"),
                "recipient": .string("you"),
            ]),
        ]

        let updated = CompanionTurnReducer.toolCalls(
            toolCalls,
            settingActionResolution: "act1",
            resolution: .resolved(status: "executed", detail: "")
        )
        let items = CompanionTurnReducer.storedItems(from: updated)

        guard case .action(_, _, let resolution) = items.first else {
            return XCTFail("expected stored action item")
        }
        XCTAssertEqual(resolution, .resolved(status: "executed", detail: ""))
    }

    func testStoredToolCallsRestorePlanTimelineItems() {
        let items = CompanionTurnReducer.storedItems(from: [
            .object([
                "type": .string("plan"),
                "steps": .array([
                    .object([
                        "title": .string("Search"),
                        "status": .string("done"),
                    ]),
                    .object([
                        "title": .string("Summarize"),
                        "status": .string("in_progress"),
                    ]),
                ]),
            ]),
        ])

        XCTAssertEqual(items.count, 1)
        guard case .plan(let id, let steps) = items[0] else {
            return XCTFail("expected stored plan item")
        }
        XCTAssertEqual(id, "stored-plan-0")
        XCTAssertEqual(steps, [
            CompanionPlanStep(title: "Search", status: "done"),
            CompanionPlanStep(title: "Summarize", status: "in_progress"),
        ])
    }

    func testStoredToolCallsRestoreToolTimelineItems() {
        let items = CompanionTurnReducer.storedItems(from: [
            .object([
                "type": .string("tools"),
                "actions": .array([
                    .object([
                        "call_id": .string("mcp_1"),
                        "tool": .string("search"),
                        "summary": .string("3 results"),
                        "ok": .bool(true),
                    ]),
                    .object([
                        "call_id": .string("web_1"),
                        "tool": .string("web_search"),
                        "summary": .null,
                        "ok": .null,
                    ]),
                ]),
            ]),
        ])

        XCTAssertEqual(items.count, 1)
        guard case .tools(let id, let actions) = items[0] else {
            return XCTFail("expected stored tools item")
        }
        XCTAssertEqual(id, "stored-tools-0")
        XCTAssertEqual(actions, [
            CompanionToolAction(callId: "mcp_1", tool: "search", summary: "3 results", ok: true),
            CompanionToolAction(callId: "web_1", tool: "web_search"),
        ])
    }

    func testStoredToolCallsRestoreWebCitationTimelineItems() {
        let items = CompanionTurnReducer.storedItems(from: [
            .object([
                "type": .string("web_citations"),
                "citations": .array([
                    .object([
                        "title": .string("Serverless GPU Inference | Runpod"),
                        "url": .string("https://www.runpod.io/serverless-gpu"),
                        "start_index": .int(4),
                        "end_index": .int(10),
                    ]),
                    .object([
                        "title": .string("Missing URL"),
                    ]),
                ]),
            ]),
        ])

        XCTAssertEqual(items.count, 1)
        guard case .webCitations(let id, let citations) = items[0] else {
            return XCTFail("expected stored web citations item")
        }
        XCTAssertEqual(id, "stored-web-citations-0")
        XCTAssertEqual(citations, [
            CompanionWebCitation(
                title: "Serverless GPU Inference | Runpod",
                url: "https://www.runpod.io/serverless-gpu",
                startIndex: 4,
                endIndex: 10
            ),
        ])
    }

    func testReducerBuildsCompactedNotificationPreviewFromAssistantText() {
        let reducer = reduce([
            .thinking(text: "Searching..."),
            .token(text: "Here are the direct links\n\n"),
            .token(text: "for GPU rental providers and pricing pages."),
        ])

        XCTAssertEqual(
            reducer.notificationPreview(maxCharacters: 48),
            "Here are the direct links for GPU rental..."
        )
    }
}
