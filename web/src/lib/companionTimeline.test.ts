import { describe, it, expect } from "vitest";

import {
  emptyTurn,
  failRunningTools,
  ingestEvent,
  itemsFromStoredToolCalls,
  setActionResolution,
  turnHasRunningTool,
} from "./companionTimeline";
import type { CompanionEvent } from "./types";

function reduce(events: CompanionEvent[]) {
  return events.reduce((turn, event) => ingestEvent(turn, event), emptyTurn());
}

describe("companionTimeline reducer", () => {
  it("coalesces thinking and token deltas into single blocks", () => {
    const turn = reduce([
      { type: "thinking", text: "Let me " },
      { type: "thinking", text: "think." },
      { type: "token", text: "Hello " },
      { type: "token", text: "world." },
    ]);
    expect(turn.items).toHaveLength(2);
    expect(turn.items[0]).toMatchObject({ kind: "thinking", text: "Let me think." });
    expect(turn.items[1]).toMatchObject({ kind: "text", markdown: "Hello world." });
  });

  it("groups consecutive tool calls and applies their results", () => {
    const turn = reduce([
      { type: "tool_call", call_id: "a", tool: "search", args: {} },
      { type: "tool_call", call_id: "b", tool: "web_search", args: {} },
      { type: "tool_result", call_id: "a", summary: "3 results", ok: true },
      { type: "tool_result", call_id: "b", summary: "Failed", ok: false },
    ]);
    expect(turn.items).toHaveLength(1);
    const tools = turn.items[0];
    expect(tools.kind).toBe("tools");
    if (tools.kind === "tools") {
      expect(tools.actions).toHaveLength(2);
      expect(tools.actions[0]).toMatchObject({ summary: "3 results", ok: true });
      expect(tools.actions[1]).toMatchObject({ ok: false });
    }
    expect(turnHasRunningTool(turn)).toBe(false);
  });

  it("splits tool groups around interleaved text", () => {
    const turn = reduce([
      { type: "tool_call", call_id: "a", tool: "search", args: {} },
      { type: "token", text: "Working…" },
      { type: "tool_call", call_id: "b", tool: "search", args: {} },
    ]);
    expect(turn.items.map((i) => i.kind)).toEqual(["tools", "text", "tools"]);
  });

  it("updates the plan card in place", () => {
    const turn = reduce([
      { type: "plan", steps: [{ title: "A", status: "in_progress" }] },
      { type: "token", text: "…" },
      {
        type: "plan",
        steps: [
          { title: "A", status: "done" },
          { title: "B", status: "in_progress" },
        ],
      },
    ]);
    const plans = turn.items.filter((i) => i.kind === "plan");
    expect(plans).toHaveLength(1);
    if (plans[0].kind === "plan") expect(plans[0].steps).toHaveLength(2);
  });

  it("resolves an action proposal", () => {
    const proposed = reduce([
      {
        type: "action_proposed",
        action_id: "act1",
        kind: "send",
        tool: "send_message_telegram",
        preview: "Send hi",
        expires_at: "x",
        recipient: "you",
      },
    ]);
    expect(proposed.items[0].kind).toBe("action");
    const resolved = setActionResolution(proposed, "act1", {
      state: "resolved",
      status: "executed",
      detail: "sent",
    });
    const item = resolved.items[0];
    expect(item.kind).toBe("action");
    if (item.kind === "action") {
      expect(item.resolution).toEqual({ state: "resolved", status: "executed", detail: "sent" });
    }
  });

  it("dedupes citations and ignores control events", () => {
    const citation: CompanionEvent = {
      type: "citation",
      index: 1,
      segment_id: "s1",
      recording_id: "r1",
      start_ms: 0,
      end_ms: 1,
      span_start: 0,
      span_end: 5,
    };
    const turn = reduce([
      { type: "turn_start", message_id: "m", conversation_id: "c" },
      citation,
      citation,
      {
        type: "done",
        message_id: "m",
        model: "gpt",
        latency_ms: 1,
        input_tokens: null,
        output_tokens: null,
        cached_tokens: null,
      },
    ]);
    expect(turn.citations).toHaveLength(1);
    expect(turn.items).toHaveLength(0);
  });

  it("fails running tools when cancelled", () => {
    let turn = reduce([{ type: "tool_call", call_id: "a", tool: "search", args: {} }]);
    expect(turnHasRunningTool(turn)).toBe(true);
    turn = failRunningTools(turn, "Stopped");
    expect(turnHasRunningTool(turn)).toBe(false);
  });

  it("appends an artifact item", () => {
    const turn = reduce([
      { type: "thinking", text: "Building…" },
      {
        type: "artifact",
        artifact_id: "a1",
        title: "Landing",
        kind: "html",
        content: "<h1>Hi</h1>",
      },
      { type: "token", text: "Done." },
    ]);
    const arts = turn.items.filter((i) => i.kind === "artifact");
    expect(arts).toHaveLength(1);
    if (arts[0].kind === "artifact") {
      expect(arts[0].artifact.kind).toBe("html");
      expect(arts[0].artifact.title).toBe("Landing");
    }
  });

  it("restores stored artifact items from assistant tool calls", () => {
    const items = itemsFromStoredToolCalls([
      {
        type: "artifact",
        artifact_id: "call_1",
        title: "Landing",
        kind: "html",
        content: "<!doctype html><h1>Hi</h1>",
        language: "",
      },
      { type: "function_call", name: "web_search" },
      null,
    ]);

    expect(items).toHaveLength(1);
    expect(items[0]).toMatchObject({
      kind: "artifact",
      id: "stored-artifact-call_1",
      artifact: {
        artifact_id: "call_1",
        title: "Landing",
        kind: "html",
        content: "<!doctype html><h1>Hi</h1>",
      },
    });
  });

  it("restores stored action items from assistant tool calls", () => {
    const items = itemsFromStoredToolCalls([
      {
        type: "action_proposed",
        action_id: "act1",
        kind: "send",
        tool: "send_message_telegram",
        preview: "Send Telegram message to your linked chat: late",
        expires_at: "2026-06-05T12:40:00+00:00",
        recipient: "you",
      },
    ]);

    expect(items).toHaveLength(1);
    expect(items[0]).toMatchObject({
      kind: "action",
      id: "stored-action-act1",
      proposal: {
        action_id: "act1",
        kind: "send",
        tool: "send_message_telegram",
        preview: "Send Telegram message to your linked chat: late",
        expires_at: "2026-06-05T12:40:00+00:00",
        recipient: "you",
      },
      resolution: null,
    });
  });

  it("restores stored plan items from assistant tool calls", () => {
    const items = itemsFromStoredToolCalls([
      {
        type: "plan",
        steps: [
          { title: "Search", status: "done" },
          { title: "Summarize", status: "in_progress" },
        ],
      },
    ]);

    expect(items).toHaveLength(1);
    expect(items[0]).toMatchObject({
      kind: "plan",
      id: "stored-plan-0",
      steps: [
        { title: "Search", status: "done" },
        { title: "Summarize", status: "in_progress" },
      ],
    });
  });

  it("restores stored tool action items from assistant tool calls", () => {
    const items = itemsFromStoredToolCalls([
      {
        type: "tools",
        actions: [
          {
            call_id: "mcp_1",
            tool: "search",
            summary: "3 results",
            ok: true,
          },
          {
            call_id: "web_1",
            tool: "web_search",
            summary: null,
            ok: null,
          },
        ],
      },
    ]);

    expect(items).toHaveLength(1);
    expect(items[0]).toMatchObject({
      kind: "tools",
      id: "stored-tools-0",
      actions: [
        { call_id: "mcp_1", tool: "search", summary: "3 results", ok: true },
        { call_id: "web_1", tool: "web_search", summary: null, ok: null },
      ],
    });
  });
});
