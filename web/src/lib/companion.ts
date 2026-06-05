import {
  ApiError,
  apiFetch,
  apiFetchResponse,
  getApiBaseUrl,
  tryRefreshAuthSession,
} from "./http";
import type {
  CompanionConversation,
  CompanionConversationDetail,
  CompanionConversationList,
  CompanionEvent,
  CompanionScope,
} from "./types";

const COMPANION = "/api/companion";
const DEFAULT_STREAM_CAPABILITIES = ["actions_v1", "agent_chat_v2"] as const;

export interface StreamMessageOptions {
  clientCapabilities?: string[];
  clientLocalDate?: string;
  clientTimezone?: string;
  viewingRecordingId?: string | null;
  viewingFolderId?: string | null;
}

export function createChat(scope?: CompanionScope): Promise<CompanionConversation> {
  return apiFetch<CompanionConversation>(`${COMPANION}/chats`, {
    method: "POST",
    body: JSON.stringify(scope ? { scope } : {}),
  });
}

export function listChats(params?: {
  limit?: number;
  before?: string;
}): Promise<CompanionConversationList> {
  const search = new URLSearchParams();
  if (params?.limit) search.set("limit", String(params.limit));
  if (params?.before) search.set("before", params.before);
  const qs = search.toString();
  return apiFetch<CompanionConversationList>(
    `${COMPANION}/chats${qs ? `?${qs}` : ""}`,
  );
}

export function getChat(
  chatId: string,
  params?: { messages_limit?: number; before_message_id?: string },
): Promise<CompanionConversationDetail> {
  const search = new URLSearchParams();
  if (params?.messages_limit) search.set("messages_limit", String(params.messages_limit));
  if (params?.before_message_id) search.set("before_message_id", params.before_message_id);
  const qs = search.toString();
  return apiFetch<CompanionConversationDetail>(
    `${COMPANION}/chats/${chatId}${qs ? `?${qs}` : ""}`,
  );
}

export function patchChat(
  chatId: string,
  patch: { title?: string; scope?: CompanionScope; pinned?: boolean; archived?: boolean },
): Promise<CompanionConversation> {
  return apiFetch<CompanionConversation>(`${COMPANION}/chats/${chatId}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export async function deleteChat(chatId: string): Promise<void> {
  await apiFetchResponse(`${COMPANION}/chats/${chatId}`, { method: "DELETE" });
}

export type ResolveActionResponse = {
  action_id: string;
  status: string; // executed | rejected | dispatched | failed
  recipient: string | null;
};

/** Approve (once/always) or reject a pending Companion chat action. */
export function resolveAction(
  chatId: string,
  actionId: string,
  decision: "once" | "always" | "reject",
): Promise<ResolveActionResponse> {
  return apiFetch<ResolveActionResponse>(
    `${COMPANION}/chats/${chatId}/actions/${actionId}/resolve`,
    { method: "POST", body: JSON.stringify({ decision }) },
  );
}

async function openStream(
  url: string,
  body: string,
  signal?: AbortSignal,
): Promise<Response> {
  return fetch(url, {
    method: "POST",
    credentials: "include",
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body,
    signal,
  });
}

/**
 * POST a message and consume the SSE stream as an async iterator of typed
 * events. Refreshes the access token once on 401 before failing. Throws
 * `ApiError` if the request itself fails (auth, 404, malformed body).
 * `error` SSE events are yielded inline; consumers must handle them.
 */
export async function* streamMessage(
  chatId: string,
  content: string,
  signal?: AbortSignal,
  optionsOrCapabilities: StreamMessageOptions | string[] = {},
): AsyncGenerator<CompanionEvent, void, unknown> {
  const url = `${getApiBaseUrl()}${COMPANION}/chats/${chatId}/messages`;
  const options = Array.isArray(optionsOrCapabilities)
    ? { clientCapabilities: optionsOrCapabilities }
    : optionsOrCapabilities;
  const payload: Record<string, unknown> = {
    content,
    client_capabilities: options.clientCapabilities ?? [...DEFAULT_STREAM_CAPABILITIES],
  };
  if (options.clientLocalDate) payload.client_local_date = options.clientLocalDate;
  if (options.clientTimezone) payload.client_timezone = options.clientTimezone;
  if (options.viewingRecordingId) payload.viewing_recording_id = options.viewingRecordingId;
  if (options.viewingFolderId) payload.viewing_folder_id = options.viewingFolderId;
  const body = JSON.stringify(payload);

  let response = await openStream(url, body, signal);

  if (response.status === 401) {
    try {
      await response.body?.cancel();
    } catch {
      /* ignore */
    }
    let refreshed = false;
    try {
      refreshed = await tryRefreshAuthSession();
    } catch {
      refreshed = false;
    }
    if (refreshed) {
      response = await openStream(url, body, signal);
    }
  }

  if (!response.ok) {
    let payload: unknown = null;
    try {
      payload = await response.json();
    } catch {
      try {
        const text = await response.text();
        payload = text.length > 0 ? { detail: text } : null;
      } catch {
        payload = null;
      }
    }
    const detail =
      (payload && typeof payload === "object" && "detail" in payload
        ? String((payload as { detail: unknown }).detail)
        : null) ?? `Request failed with status ${response.status}`;
    throw new ApiError(response.status, detail, payload);
  }
  if (!response.body) {
    throw new ApiError(0, "No stream body in response");
  }

  const decoder = new TextDecoder("utf-8");
  const reader = response.body.getReader();
  let buffer = "";

  const abortHandler = () => {
    void reader.cancel().catch(() => {});
  };
  signal?.addEventListener("abort", abortHandler, { once: true });

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let separatorIndex: number;
      while ((separatorIndex = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, separatorIndex);
        buffer = buffer.slice(separatorIndex + 2);
        const event = parseFrame(frame);
        if (event) yield event;
      }
    }
    const trailing = buffer.trim();
    if (trailing.length > 0) {
      const event = parseFrame(trailing);
      if (event) yield event;
    }
  } finally {
    signal?.removeEventListener("abort", abortHandler);
    try {
      reader.releaseLock();
    } catch {
      /* ignore */
    }
  }
}

function parseFrame(frame: string): CompanionEvent | null {
  let eventType: string | null = null;
  const dataLines: string[] = [];
  let sawContentLine = false;
  for (const rawLine of frame.split("\n")) {
    const line = rawLine.replace(/\r$/, "");
    if (line.length === 0) {
      continue;
    }
    if (line.startsWith(":")) {
      // SSE comment / heartbeat — skip.
      continue;
    }
    sawContentLine = true;
    if (line.startsWith("event:")) {
      eventType = stripOptionalLeadingSpace(line.slice("event:".length)).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(stripOptionalLeadingSpace(line.slice("data:".length)));
    } else if (line.startsWith("id:") || line.startsWith("retry:")) {
      continue;
    } else {
      throw new ApiError(0, `Malformed SSE frame line: ${line}`);
    }
  }
  if (!sawContentLine) {
    return null;
  }
  if (!eventType) {
    throw new ApiError(0, "SSE frame missing event: field");
  }
  if (dataLines.length === 0) {
    throw new ApiError(0, `SSE frame for '${eventType}' has no data: line`);
  }
  const dataString = dataLines.join("\n");
  let data: Record<string, unknown>;
  try {
    data = JSON.parse(dataString) as Record<string, unknown>;
  } catch (err) {
    throw new ApiError(
      0,
      `SSE frame for '${eventType}' is not valid JSON: ${(err as Error).message}`,
    );
  }
  return { type: eventType, ...data } as CompanionEvent;
}

function stripOptionalLeadingSpace(value: string): string {
  return value.startsWith(" ") ? value.slice(1) : value;
}
