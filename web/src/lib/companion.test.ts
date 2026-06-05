import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

import {
  createChat,
  deleteChat,
  getChat,
  listChats,
  patchChat,
  streamMessage,
} from "./companion";
import { tryRefreshAuthSession } from "./http";

// Keep every real ./http export (ApiError, apiFetch, getApiBaseUrl, …) so the
// existing CRUD + parser tests keep exercising production code paths. Only
// tryRefreshAuthSession is replaced with a spy so the 401-refresh branch can be
// driven deterministically without hitting the network.
vi.mock("./http", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./http")>();
  return { ...actual, tryRefreshAuthSession: vi.fn(actual.tryRefreshAuthSession) };
});

const mockedRefresh = vi.mocked(tryRefreshAuthSession);

const originalFetch = global.fetch;

beforeEach(() => {
  global.fetch = vi.fn();
  // Default: no refresh happens unless a test opts in. Real tryRefreshAuthSession
  // would call fetch("/api/auth/refresh"); the explicit default keeps the 401
  // path inert for the streams that never expect a retry.
  mockedRefresh.mockReset();
  mockedRefresh.mockResolvedValue(false);
});

afterEach(() => {
  global.fetch = originalFetch;
});

function sseStream(frames: string[]): ReadableStream<Uint8Array> {
  return new ReadableStream<Uint8Array>({
    start(controller) {
      const encoder = new TextEncoder();
      for (const f of frames) controller.enqueue(encoder.encode(f));
      controller.close();
    },
  });
}

function sseResponse(frames: string[]): Response {
  return new Response(sseStream(frames), {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}

async function collectTypes(
  gen: AsyncGenerator<{ type: string }, void, unknown>,
): Promise<string[]> {
  const types: string[] = [];
  for await (const evt of gen) types.push(evt.type);
  return types;
}

function fakeJsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("companion CRUD wrappers", () => {
  it("createChat POSTs to /api/companion/chats with scope when provided", async () => {
    const chat = {
      id: "c1",
      title: null,
      scope: { recording_ids: ["r1"] },
      pinned_at: null,
      last_message_at: null,
      archived_at: null,
      created_at: "2026-05-18T00:00:00Z",
      updated_at: "2026-05-18T00:00:00Z",
    };
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(fakeJsonResponse(chat));

    const result = await createChat({ recording_ids: ["r1"] });

    expect(result).toEqual(chat);
    const [url, init] = (global.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe("/api/companion/chats");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ scope: { recording_ids: ["r1"] } });
  });

  it("listChats sends limit + before as query params", async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(fakeJsonResponse({ chats: [] }));

    await listChats({ limit: 10, before: "cursor-id" });

    const [url] = (global.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe("/api/companion/chats?limit=10&before=cursor-id");
  });

  it("getChat reads cursor params and returns detail", async () => {
    const detail = {
      id: "c1",
      title: null,
      scope: null,
      pinned_at: null,
      last_message_at: null,
      archived_at: null,
      created_at: "2026-05-18T00:00:00Z",
      updated_at: "2026-05-18T00:00:00Z",
      messages: [],
    };
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(fakeJsonResponse(detail));

    const result = await getChat("c1", { messages_limit: 5 });

    const [url] = (global.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe("/api/companion/chats/c1?messages_limit=5");
    expect(result.messages).toEqual([]);
  });

  it("patchChat PATCHes the provided fields", async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(fakeJsonResponse({
      id: "c1",
      title: "Renamed",
      scope: null,
      pinned_at: null,
      last_message_at: null,
      archived_at: null,
      created_at: "2026-05-18T00:00:00Z",
      updated_at: "2026-05-18T00:00:00Z",
    }));

    await patchChat("c1", { title: "Renamed", pinned: true });

    const [, init] = (global.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(init.method).toBe("PATCH");
    expect(JSON.parse(init.body as string)).toEqual({ title: "Renamed", pinned: true });
  });

  it("deleteChat sends DELETE", async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(new Response(null, { status: 204 }));

    await deleteChat("c1");

    const [url, init] = (global.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe("/api/companion/chats/c1");
    expect(init.method).toBe("DELETE");
  });
});

describe("streamMessage SSE parser", () => {
  it("parses interleaved events and yields each one in order", async () => {
    const frames = [
      "event: turn_start\ndata: {\"message_id\":\"m1\",\"conversation_id\":\"c1\"}\n\n",
      "event: tool_call\ndata: {\"call_id\":\"t1\",\"tool\":\"search_transcripts\",\"args\":{\"query\":\"x\"}}\n\n",
      "event: tool_result\ndata: {\"call_id\":\"t1\",\"summary\":\"3 segments\"}\n\n",
      "event: token\ndata: {\"text\":\"Hello \"}\n\n",
      "event: token\ndata: {\"text\":\"world.\"}\n\n",
      "event: citation\ndata: {\"index\":1,\"segment_id\":\"s1\",\"recording_id\":\"r1\",\"start_ms\":1000,\"end_ms\":2000,\"span_start\":0,\"span_end\":5}\n\n",
      "event: done\ndata: {\"message_id\":\"a1\",\"input_tokens\":10,\"output_tokens\":20,\"cached_tokens\":0,\"model\":\"gpt-5.5\",\"latency_ms\":1234}\n\n",
    ];
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        const encoder = new TextEncoder();
        for (const f of frames) controller.enqueue(encoder.encode(f));
        controller.close();
      },
    });
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response(body, {
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
      }),
    );

    const types: string[] = [];
    for await (const evt of streamMessage("c1", "hello")) {
      types.push(evt.type);
    }
    expect(types).toEqual([
      "turn_start",
      "tool_call",
      "tool_result",
      "token",
      "token",
      "citation",
      "done",
    ]);
    const [, init] = (global.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(JSON.parse(init.body as string)).toEqual({
      content: "hello",
      client_capabilities: ["actions_v1", "agent_chat_v2"],
    });
  });

  it("sends per-turn local session context to the agent endpoint", async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      sseResponse(["event: done\ndata: {\"message_id\":\"a1\"}\n\n"]),
    );

    const types = await collectTypes(
      streamMessage("c1", "what did I promise yesterday?", undefined, {
        clientLocalDate: "2026-06-05",
        clientTimezone: "Europe/Moscow",
        viewingRecordingId: "recording-1",
        viewingFolderId: "folder-1",
      }),
    );

    expect(types).toEqual(["done"]);
    const [, init] = (global.fetch as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(JSON.parse(init.body as string)).toEqual({
      content: "what did I promise yesterday?",
      client_capabilities: ["actions_v1", "agent_chat_v2"],
      client_local_date: "2026-06-05",
      client_timezone: "Europe/Moscow",
      viewing_recording_id: "recording-1",
      viewing_folder_id: "folder-1",
    });
  });

  it("throws ApiError on non-2xx responses", async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      new Response(JSON.stringify({ detail: "Conversation not found" }), {
        status: 404,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(async () => {
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      for await (const _event of streamMessage("missing", "hi")) {
        // unreachable
      }
    }).rejects.toMatchObject({ status: 404 });
  });
});

describe("streamMessage 401 refresh-and-retry", () => {
  it("cancels the body, refreshes once, then replays the original POST", async () => {
    const cancel = vi.fn().mockResolvedValue(undefined);
    const unauthorized = {
      status: 401,
      ok: false,
      body: { cancel },
    } as unknown as Response;
    mockedRefresh.mockResolvedValueOnce(true);
    (global.fetch as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce(unauthorized)
      .mockResolvedValueOnce(sseResponse(["event: done\ndata: {\"message_id\":\"a1\"}\n\n"]));

    const types = await collectTypes(streamMessage("c1", "hi"));

    expect(types).toEqual(["done"]);
    expect(cancel).toHaveBeenCalledTimes(1);
    expect(mockedRefresh).toHaveBeenCalledTimes(1);
    expect((global.fetch as ReturnType<typeof vi.fn>).mock.calls).toHaveLength(2);
    // Both attempts target the same messages endpoint with identical body.
    const [, secondInit] = (global.fetch as ReturnType<typeof vi.fn>).mock.calls[1];
    expect(JSON.parse(secondInit.body as string)).toEqual({
      content: "hi",
      client_capabilities: ["actions_v1", "agent_chat_v2"],
    });
  });

  it("swallows a body.cancel() rejection and still retries after refresh", async () => {
    const unauthorized = {
      status: 401,
      ok: false,
      body: { cancel: vi.fn().mockRejectedValue(new Error("already locked")) },
    } as unknown as Response;
    mockedRefresh.mockResolvedValueOnce(true);
    (global.fetch as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce(unauthorized)
      .mockResolvedValueOnce(sseResponse(["event: token\ndata: {\"text\":\"ok\"}\n\n"]));

    const types = await collectTypes(streamMessage("c1", "hi"));

    expect(types).toEqual(["token"]);
    expect((global.fetch as ReturnType<typeof vi.fn>).mock.calls).toHaveLength(2);
  });

  it("treats a thrown tryRefreshAuthSession as a failed refresh and surfaces the 401", async () => {
    const unauthorized = {
      status: 401,
      ok: false,
      body: { cancel: vi.fn().mockResolvedValue(undefined) },
      json: vi.fn().mockResolvedValue({ detail: "Session expired" }),
    } as unknown as Response;
    mockedRefresh.mockRejectedValueOnce(new Error("refresh endpoint down"));
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(unauthorized);

    await expect(collectTypes(streamMessage("c1", "hi"))).rejects.toMatchObject({
      status: 401,
      message: "Session expired",
    });
    // No retry — refresh threw, so the second openStream is never attempted.
    expect((global.fetch as ReturnType<typeof vi.fn>).mock.calls).toHaveLength(1);
  });

  it("does not retry when refresh returns false and re-reads the 401 body for detail", async () => {
    const unauthorized = {
      status: 401,
      ok: false,
      body: { cancel: vi.fn().mockResolvedValue(undefined) },
      json: vi.fn().mockResolvedValue({ detail: "Not authenticated" }),
    } as unknown as Response;
    mockedRefresh.mockResolvedValueOnce(false);
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(unauthorized);

    await expect(collectTypes(streamMessage("c1", "hi"))).rejects.toMatchObject({
      status: 401,
      message: "Not authenticated",
    });
    expect((global.fetch as ReturnType<typeof vi.fn>).mock.calls).toHaveLength(1);
  });
});

describe("streamMessage error-body parsing", () => {
  it("falls back to response.text() when the error body is not JSON", async () => {
    const errorResponse = {
      status: 500,
      ok: false,
      body: {},
      json: vi.fn().mockRejectedValue(new SyntaxError("Unexpected token")),
      text: vi.fn().mockResolvedValue("upstream exploded"),
    } as unknown as Response;
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(errorResponse);

    await expect(collectTypes(streamMessage("c1", "hi"))).rejects.toMatchObject({
      status: 500,
      message: "upstream exploded",
    });
  });

  it("uses the status fallback message when JSON and text both yield nothing", async () => {
    const errorResponse = {
      status: 503,
      ok: false,
      body: {},
      json: vi.fn().mockRejectedValue(new SyntaxError("bad json")),
      text: vi.fn().mockResolvedValue(""),
    } as unknown as Response;
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(errorResponse);

    await expect(collectTypes(streamMessage("c1", "hi"))).rejects.toMatchObject({
      status: 503,
      message: "Request failed with status 503",
    });
  });

  it("uses the status fallback message when even response.text() throws", async () => {
    const errorResponse = {
      status: 502,
      ok: false,
      body: {},
      json: vi.fn().mockRejectedValue(new SyntaxError("bad json")),
      text: vi.fn().mockRejectedValue(new Error("stream consumed")),
    } as unknown as Response;
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(errorResponse);

    await expect(collectTypes(streamMessage("c1", "hi"))).rejects.toMatchObject({
      status: 502,
      message: "Request failed with status 502",
    });
  });

  it("throws when an ok response carries no stream body", async () => {
    const noBody = {
      status: 200,
      ok: true,
      body: null,
    } as unknown as Response;
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(noBody);

    await expect(collectTypes(streamMessage("c1", "hi"))).rejects.toMatchObject({
      status: 0,
      message: "No stream body in response",
    });
  });
});

describe("streamMessage abort handling", () => {
  it("cancels the reader and stops iterating when the signal aborts mid-stream", async () => {
    const controller = new AbortController();
    let readCount = 0;
    let cancelReject: ((reason?: unknown) => void) | undefined;
    const reader = {
      read: vi.fn().mockImplementation(() => {
        readCount += 1;
        if (readCount === 1) {
          const encoder = new TextEncoder();
          return Promise.resolve({
            value: encoder.encode("event: token\ndata: {\"text\":\"a\"}\n\n"),
            done: false,
          });
        }
        // After the first frame the consumer aborts; this read never resolves
        // until cancel() rejects it, mirroring a real ReadableStream reader.
        return new Promise((_resolve, reject) => {
          cancelReject = reject;
        });
      }),
      cancel: vi.fn().mockImplementation(() => {
        cancelReject?.(new DOMException("aborted", "AbortError"));
        return Promise.resolve();
      }),
      releaseLock: vi.fn(),
    };
    const response = {
      status: 200,
      ok: true,
      body: { getReader: () => reader },
    } as unknown as Response;
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(response);

    const gen = streamMessage("c1", "hi", controller.signal);
    const first = await gen.next();
    expect(first.value).toMatchObject({ type: "token", text: "a" });

    // Kick off the next pull so read() #2 is pending, THEN abort. The abort
    // handler cancels the reader, which rejects the in-flight read and unwinds
    // the generator through its finally block.
    const pending = gen.next();
    await Promise.resolve();
    controller.abort();
    await pending.catch(() => undefined);

    expect(reader.cancel).toHaveBeenCalled();
    expect(reader.releaseLock).toHaveBeenCalled();
  });

  it("removes the abort listener and releases the lock after a clean finish", async () => {
    const controller = new AbortController();
    const removeSpy = vi.spyOn(controller.signal, "removeEventListener");
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      sseResponse(["event: done\ndata: {\"message_id\":\"a1\"}\n\n"]),
    );

    const types = await collectTypes(streamMessage("c1", "hi", controller.signal));

    expect(types).toEqual(["done"]);
    expect(removeSpy).toHaveBeenCalledWith("abort", expect.any(Function));
  });
});

describe("streamMessage SSE frame edge cases", () => {
  it("skips heartbeat comments and id/retry lines, returning only the typed event", async () => {
    // A heartbeat comment plus id/retry metadata wrap a single real token event.
    const frame =
      ": keepalive\nid: 42\nretry: 3000\nevent: token\ndata: {\"text\":\"hi\"}\n\n";
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(sseResponse([frame]));

    const events: Array<{ type: string; text?: string }> = [];
    for await (const evt of streamMessage("c1", "hi")) {
      events.push(evt as { type: string; text?: string });
    }
    expect(events).toEqual([{ type: "token", text: "hi" }]);
  });

  it("strips CR endings and skips a blank line inside a CRLF trailing frame", async () => {
    // No "\n\n" anywhere (CRLF uses "\r\n\r\n"), so the whole frame reaches the
    // trailing-buffer flush. The middle "\r\n\r\n" leaves an empty line after the
    // "\r$" strip, which parseFrame must skip rather than reject.
    const frame =
      "event: token\r\n\r\ndata: {\"text\":\"crlf\"}\r\n";
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(sseResponse([frame]));

    const events: Array<{ type: string; text?: string }> = [];
    for await (const evt of streamMessage("c1", "hi")) {
      events.push(evt as { type: string; text?: string });
    }
    expect(events).toEqual([{ type: "token", text: "crlf" }]);
  });

  it("ignores pure-comment frames that contain no real content lines", async () => {
    // A heartbeat-only frame yields null (sawContentLine === false), then a real one follows.
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      sseResponse([
        ": ping\n\n",
        "event: token\ndata: {\"text\":\"after-ping\"}\n\n",
      ]),
    );

    const events: Array<{ type: string; text?: string }> = [];
    for await (const evt of streamMessage("c1", "hi")) {
      events.push(evt as { type: string; text?: string });
    }
    expect(events).toEqual([{ type: "token", text: "after-ping" }]);
  });

  it("joins multi-line data: fields into one JSON document", async () => {
    // SSE allows data to span several lines; they rejoin with \n before JSON.parse.
    const frame =
      'event: tool_result\ndata: {"call_id":"t1",\ndata: "summary":"two\\nlines"}\n\n';
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(sseResponse([frame]));

    const events: Array<Record<string, unknown>> = [];
    for await (const evt of streamMessage("c1", "hi")) {
      events.push(evt as Record<string, unknown>);
    }
    expect(events).toEqual([
      { type: "tool_result", call_id: "t1", summary: "two\nlines" },
    ]);
  });

  it("parses a trailing frame that has no terminating blank line", async () => {
    // The final chunk lacks "\n\n"; streamMessage flushes the trimmed buffer.
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      sseResponse([
        "event: token\ndata: {\"text\":\"one\"}\n\n",
        "event: done\ndata: {\"message_id\":\"a1\"}",
      ]),
    );

    const types = await collectTypes(streamMessage("c1", "hi"));
    expect(types).toEqual(["token", "done"]);
  });

  it("rejects a frame line that is neither event/data/id/retry/comment", async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      sseResponse(["event: token\nweirdfield: nope\ndata: {}\n\n"]),
    );

    await expect(collectTypes(streamMessage("c1", "hi"))).rejects.toMatchObject({
      status: 0,
      message: "Malformed SSE frame line: weirdfield: nope",
    });
  });

  it("rejects a content frame missing the event: field", async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      sseResponse(["data: {\"text\":\"orphan\"}\n\n"]),
    );

    await expect(collectTypes(streamMessage("c1", "hi"))).rejects.toMatchObject({
      status: 0,
      message: "SSE frame missing event: field",
    });
  });

  it("rejects an event frame missing any data: line", async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      sseResponse(["event: token\n\n"]),
    );

    await expect(collectTypes(streamMessage("c1", "hi"))).rejects.toMatchObject({
      status: 0,
      message: "SSE frame for 'token' has no data: line",
    });
  });

  it("rejects a frame whose data: payload is not valid JSON", async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce(
      sseResponse(["event: token\ndata: {not json}\n\n"]),
    );

    await expect(collectTypes(streamMessage("c1", "hi"))).rejects.toMatchObject({
      status: 0,
      message: expect.stringContaining("SSE frame for 'token' is not valid JSON:"),
    });
  });
});
