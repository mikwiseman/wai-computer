import type {
  CompanionArtifact,
  CompanionEvent,
  CompanionPlanStep,
  CompanionWebCitation,
} from "./types";

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
  | { kind: "artifact"; id: string; artifact: CompanionArtifact }
  | { kind: "web_citations"; id: string; citations: CompanionWebCitation[] }
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

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stringField(record: Record<string, unknown>, key: string): string | null {
  const value = record[key];
  return typeof value === "string" ? value : null;
}

function storedActionResolution(
  value: unknown,
): CompanionActionResolution | null {
  if (!isRecord(value)) return null;
  const state = stringField(value, "state");
  if (state === "executing") return { state: "executing" };
  if (state !== "resolved") return null;

  const status = stringField(value, "status");
  const detail = stringField(value, "detail");
  if (!status || detail === null) return null;
  return { state: "resolved", status, detail };
}

function storedPlanSteps(value: unknown): CompanionPlanStep[] | null {
  if (!Array.isArray(value)) return null;
  const steps: CompanionPlanStep[] = [];
  for (const item of value) {
    if (!isRecord(item)) continue;
    const title = stringField(item, "title");
    const status = stringField(item, "status");
    if (!title || !status) continue;
    steps.push({ title, status });
  }
  return steps.length > 0 ? steps : null;
}

function storedToolActions(value: unknown): CompanionToolAction[] | null {
  if (!Array.isArray(value)) return null;
  const actions: CompanionToolAction[] = [];
  for (const item of value) {
    if (!isRecord(item)) continue;
    const callId = stringField(item, "call_id");
    const tool = stringField(item, "tool");
    if (!callId || !tool) continue;

    const rawSummary = item.summary;
    const rawOk = item.ok;
    if (
      rawSummary !== null
      && rawSummary !== undefined
      && typeof rawSummary !== "string"
    ) {
      continue;
    }
    if (rawOk !== null && rawOk !== undefined && typeof rawOk !== "boolean") {
      continue;
    }

    actions.push({
      call_id: callId,
      tool,
      summary: typeof rawSummary === "string" ? rawSummary : null,
      ok: typeof rawOk === "boolean" ? rawOk : null,
    });
  }
  return actions.length > 0 ? actions : null;
}

function numberField(record: Record<string, unknown>, key: string): number | undefined {
  const value = record[key];
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function storedWebCitations(value: unknown): CompanionWebCitation[] | null {
  if (!Array.isArray(value)) return null;
  const citations: CompanionWebCitation[] = [];
  for (const item of value) {
    if (!isRecord(item)) continue;
    const title = stringField(item, "title");
    const url = stringField(item, "url");
    if (!title || !url) continue;
    citations.push({
      title,
      url,
      start_index: numberField(item, "start_index"),
      end_index: numberField(item, "end_index"),
    });
  }
  return citations.length > 0 ? citations : null;
}

export function itemsFromStoredToolCalls(
  toolCalls: unknown[] | null | undefined,
): CompanionTurnItem[] {
  if (!Array.isArray(toolCalls)) return [];

  const items: CompanionTurnItem[] = [];
  for (const item of toolCalls) {
    if (!isRecord(item)) continue;

    if (item.type === "tools") {
      const actions = storedToolActions(item.actions);
      if (!actions) continue;
      items.push({
        kind: "tools",
        id: `stored-tools-${items.length}`,
        actions,
      });
    } else if (item.type === "web_citations") {
      const citations = storedWebCitations(item.citations);
      if (!citations) continue;
      items.push({
        kind: "web_citations",
        id: `stored-web-citations-${items.length}`,
        citations,
      });
    } else if (item.type === "artifact") {
      const artifactId = stringField(item, "artifact_id");
      const title = stringField(item, "title");
      const kind = stringField(item, "kind");
      const content = stringField(item, "content");
      if (!artifactId || !title || !kind || content === null) continue;

      const language = stringField(item, "language") ?? undefined;
      items.push({
        kind: "artifact",
        id: `stored-artifact-${artifactId}`,
        artifact: {
          artifact_id: artifactId,
          title,
          kind,
          content,
          language,
        },
      });
    } else if (item.type === "action_proposed") {
      const actionId = stringField(item, "action_id");
      const kind = stringField(item, "kind");
      const tool = stringField(item, "tool");
      const preview = stringField(item, "preview");
      const expiresAt = stringField(item, "expires_at");
      if (!actionId || !kind || !tool || !preview || !expiresAt) continue;

      items.push({
        kind: "action",
        id: `stored-action-${actionId}`,
        proposal: {
          action_id: actionId,
          kind,
          tool,
          preview,
          expires_at: expiresAt,
          recipient: stringField(item, "recipient"),
        },
        resolution: storedActionResolution(item.resolution),
      });
    } else if (item.type === "plan") {
      const steps = storedPlanSteps(item.steps);
      if (!steps) continue;
      items.push({
        kind: "plan",
        id: `stored-plan-${items.length}`,
        steps,
      });
    }
  }
  return items;
}

export function setStoredActionResolution(
  toolCalls: unknown[] | null | undefined,
  actionId: string,
  resolution: CompanionActionResolution,
): unknown[] | null {
  if (!Array.isArray(toolCalls)) return toolCalls ?? null;
  let changed = false;
  const resolutionPayload =
    resolution.state === "executing"
      ? { state: "executing" }
      : {
          state: "resolved",
          status: resolution.status,
          detail: resolution.detail,
        };

  const next = toolCalls.map((item) => {
    if (
      isRecord(item)
      && item.type === "action_proposed"
      && item.action_id === actionId
    ) {
      changed = true;
      return { ...item, resolution: resolutionPayload };
    }
    return item;
  });
  return changed ? next : toolCalls;
}

/**
 * Immutable fold of the Companion SSE event stream into ordered timeline items
 * (openclaw-style cards). Returns a NEW turn each call so React re-renders
 * cleanly. Coalesces consecutive thinking/token deltas, groups consecutive tool
 * calls, appends web sources, replaces the plan card in place, and resolves
 * action proposals.
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
    case "artifact": {
      items.push({
        kind: "artifact",
        id: nextId("artifact"),
        artifact: {
          artifact_id: evt.artifact_id,
          title: evt.title,
          kind: evt.kind,
          content: evt.content,
          language: evt.language,
        },
      });
      return { ...turn, items, counter };
    }
    case "web_citations": {
      const citations = storedWebCitations(evt.citations);
      if (!citations) return turn;
      items.push({
        kind: "web_citations",
        id: nextId("web-citations"),
        citations,
      });
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
