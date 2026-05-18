import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

import {
  createChat,
  deleteChat,
  getChat,
  listChats,
  patchChat,
  streamMessage,
} from "./companion";

const originalFetch = global.fetch;

beforeEach(() => {
  global.fetch = vi.fn();
});

afterEach(() => {
  global.fetch = originalFetch;
});

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
