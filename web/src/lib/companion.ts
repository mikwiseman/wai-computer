import { ApiError, apiFetchResponse, getApiBaseUrl } from "./http";
import { apiFetch } from "./http";
import type {
  CompanionConversation,
  CompanionConversationDetail,
  CompanionConversationList,
  CompanionEvent,
  CompanionScope,
} from "./types";

const COMPANION = "/api/companion";

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

/**
 * POST a message and consume the SSE stream as an async iterator of typed events.
 * Throws ApiError if the request itself fails (auth, 404). Stream errors are
 * surfaced as `{type: "error"}` events.
 */
export async function* streamMessage(
  chatId: string,
  content: string,
  signal?: AbortSignal,
): AsyncGenerator<CompanionEvent, void, unknown> {
  const url = `${getApiBaseUrl()}${COMPANION}/chats/${chatId}/messages`;
  const response = await fetch(url, {
    method: "POST",
    credentials: "include",
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify({ content }),
    signal,
  });

  if (!response.ok) {
    let payload: unknown = null;
    try {
      payload = await response.json();
    } catch {
      /* ignore */
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

  const decoder = new TextDecoder();
  const reader = response.body.getReader();
  let buffer = "";

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
    // Flush any trailing frame after the stream closes.
    const trailing = buffer.trim();
    if (trailing.length > 0) {
      const event = parseFrame(trailing);
      if (event) yield event;
    }
  } finally {
    reader.releaseLock();
  }
}

function parseFrame(frame: string): CompanionEvent | null {
  let eventType: string | null = null;
  let dataLine: string | null = null;
  for (const rawLine of frame.split("\n")) {
    const line = rawLine.trimEnd();
    if (line.startsWith("event: ")) {
      eventType = line.slice(7).trim();
    } else if (line.startsWith("data: ")) {
      dataLine = line.slice(6);
    }
  }
  if (!eventType || dataLine === null) {
    return null;
  }
  try {
    const data = JSON.parse(dataLine) as Record<string, unknown>;
    return { type: eventType, ...data } as CompanionEvent;
  } catch {
    return null;
  }
}
