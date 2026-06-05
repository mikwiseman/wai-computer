import type { CompanionEvent, CompanionPlanStep } from "./types";

/** A single hosted-read tool invocation in a "Tool actions" card. */
export type CompanionToolAction = {
  call_id: string;
  tool: string;
  summary: string | null; // null = still running
  ok: boolean | null;
};

export type CompanionActionProposal = {
  action_id: string;
  kind: string;
  tool: string;
  preview: string;
  expires_at: string;
  recipient: string | null;
};

export type CompanionActionResolution =
  | { state: "executing" }
  | { state: "resolved"; status: string; detail: string };

export type StreamingCitation = {
  index: number;
  segment_id: string;
  recording_id: string;
  start_ms: number | null;
  end_ms: number | null;
};

export type CompanionTurnItem =
  | { kind: "thinking"; id: string; text: string }
  | { kind: "tools"; id: string; actions: CompanionToolAction[] }
  | { kind: "plan"; id: string; steps: CompanionPlanStep[] }
  | { kind: "text"; id: string; markdown: string }
  | {
      kind: "action";
      id: string;
      proposal: CompanionActionProposal;
      resolution: CompanionActionResolution | null;
    };

export type CompanionTurn = {
  items: CompanionTurnItem[];
  citations: StreamingCitation[];
  counter: number;
};

export function emptyTurn(): CompanionTurn {
  return { items: [], citations: [], counter: 0 };
}

export function turnIsEmpty(turn: CompanionTurn): boolean {
  return turn.items.length === 0 && turn.citations.length === 0;
}

export function turnHasRunningTool(turn: CompanionTurn): boolean {
  return turn.items.some(
    (it) => it.kind === "tools" && it.actions.some((a) => a.summary === null),
  );
}

/**
 * Immutable fold of the Companion SSE event stream into ordered timeline items
 * (openclaw-style cards). Returns a NEW turn each call so React re-renders
 * cleanly. Coalesces consecutive thinking/token deltas, groups consecutive tool
 * calls, replaces the plan card in place, and resolves action proposals.
 */
export function ingestEvent(turn: CompanionTurn, evt: CompanionEvent): CompanionTurn {
  const items = turn.items.slice();
  let counter = turn.counter;
  const nextId = (prefix: string) => `${prefix}-${++counter}`;
  const last = items[items.length - 1];

  switch (evt.type) {
    case "thinking": {
      if (last && last.kind === "thinking") {
        items[items.length - 1] = { ...last, text: last.text + evt.text };
      } else {
        items.push({ kind: "thinking", id: nextId("thinking"), text: evt.text });
      }
      return { ...turn, items, counter };
    }
    case "token": {
      if (last && last.kind === "text") {
        items[items.length - 1] = { ...last, markdown: last.markdown + evt.text };
      } else {
        items.push({ kind: "text", id: nextId("text"), markdown: evt.text });
      }
      return { ...turn, items, counter };
    }
    case "tool_call": {
      const action: CompanionToolAction = {
        call_id: evt.call_id,
        tool: evt.tool,
        summary: null,
        ok: null,
      };
      if (last && last.kind === "tools") {
        items[items.length - 1] = { ...last, actions: [...last.actions, action] };
      } else {
        items.push({ kind: "tools", id: nextId("tools"), actions: [action] });
      }
      return { ...turn, items, counter };
    }
    case "tool_result": {
      for (let i = items.length - 1; i >= 0; i--) {
        const it = items[i];
        if (it.kind === "tools") {
          const idx = it.actions.map((a) => a.call_id).lastIndexOf(evt.call_id);
          if (idx >= 0) {
            const actions = it.actions.slice();
            actions[idx] = { ...actions[idx], summary: evt.summary, ok: evt.ok ?? true };
            items[i] = { ...it, actions };
            break;
          }
        }
      }
      return { ...turn, items, counter };
    }
    case "plan": {
      const i = items.findIndex((it) => it.kind === "plan");
      if (i >= 0) {
        const existing = items[i] as Extract<CompanionTurnItem, { kind: "plan" }>;
        items[i] = { ...existing, steps: evt.steps };
      } else {
        items.push({ kind: "plan", id: nextId("plan"), steps: evt.steps });
      }
      return { ...turn, items, counter };
    }
    case "citation": {
      const exists = turn.citations.some(
        (c) => c.index === evt.index && c.segment_id === evt.segment_id,
      );
      if (exists) return turn;
      return {
        ...turn,
        citations: [
          ...turn.citations,
          {
            index: evt.index,
            segment_id: evt.segment_id,
            recording_id: evt.recording_id,
            start_ms: evt.start_ms,
            end_ms: evt.end_ms,
          },
        ],
      };
    }
    case "action_proposed": {
      items.push({
        kind: "action",
        id: nextId("action"),
        proposal: {
          action_id: evt.action_id,
          kind: evt.kind,
          tool: evt.tool,
          preview: evt.preview,
          expires_at: evt.expires_at,
          recipient: evt.recipient,
        },
        resolution: null,
      });
      return { ...turn, items, counter };
    }
    case "action_result": {
      for (let i = items.length - 1; i >= 0; i--) {
        const it = items[i];
        if (it.kind === "action" && it.proposal.action_id === evt.action_id) {
          items[i] = {
            ...it,
            resolution: { state: "resolved", status: evt.status, detail: evt.detail },
          };
          break;
        }
      }
      return { ...turn, items, counter };
    }
    default:
      // turn_start, memory_updated, narration, desktop_action, done, error
      return turn;
  }
}

/** Set an action card's resolution by id (used when the user approves/rejects). */
export function setActionResolution(
  turn: CompanionTurn,
  actionId: string,
  resolution: CompanionActionResolution,
): CompanionTurn {
  const items = turn.items.slice();
  let changed = false;
  for (let i = items.length - 1; i >= 0; i--) {
    const it = items[i];
    if (it.kind === "action" && it.proposal.action_id === actionId) {
      items[i] = { ...it, resolution };
      changed = true;
      break;
    }
  }
  return changed ? { ...turn, items } : turn;
}

/** Mark every still-running tool as failed (turn cancelled / errored). */
export function failRunningTools(turn: CompanionTurn, summary: string): CompanionTurn {
  const items = turn.items.map((it) => {
    if (it.kind === "tools" && it.actions.some((a) => a.summary === null)) {
      return {
        ...it,
        actions: it.actions.map((a) =>
          a.summary === null ? { ...a, summary, ok: false } : a,
        ),
      };
    }
    return it;
  });
  return { ...turn, items };
}
