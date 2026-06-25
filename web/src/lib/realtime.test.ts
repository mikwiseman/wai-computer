import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createTranscriptionSession } from "@/lib/api";
import { downsampleTo16kInt16 } from "@/lib/audio/pcm";
import type { RealtimeSessionResponse } from "@/lib/types";

import {
  RealtimeTranscriber,
  parseRealtimeMessage,
  type RealtimeStartOptions,
} from "./realtime";

vi.mock("@/lib/api", () => ({
  createTranscriptionSession: vi.fn(),
}));

vi.mock("@/lib/audio/pcm", () => ({
  downsampleTo16kInt16: vi.fn(),
}));

const mockedCreateSession = vi.mocked(createTranscriptionSession);
const mockedDownsample = vi.mocked(downsampleTo16kInt16);

// ---------------------------------------------------------------------------
// Controllable browser-API fakes (jsdom ships none of these).
// ---------------------------------------------------------------------------

const WS_CONNECTING = 0;
const WS_OPEN = 1;
const WS_CLOSING = 2;
const WS_CLOSED = 3;

/** A WebSocket stand-in whose handlers and readyState the test drives. */
class FakeWebSocket {
  static CONNECTING = WS_CONNECTING;
  static OPEN = WS_OPEN;
  static CLOSING = WS_CLOSING;
  static CLOSED = WS_CLOSED;
  static instances: FakeWebSocket[] = [];

  url: string;
  binaryType = "";
  readyState = WS_CONNECTING;
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  readonly sent: Array<string | ArrayBuffer> = [];
  closeCalls = 0;
  throwOnSend = false;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  send(data: string | ArrayBuffer): void {
    if (this.throwOnSend) throw new Error("send failed");
    this.sent.push(data);
  }

  close(): void {
    this.closeCalls += 1;
    this.readyState = WS_CLOSED;
  }
}

/** Worklet node whose `port.onmessage` the test fires to simulate PCM chunks. */
class FakeAudioWorkletNode {
  port = { onmessage: null as ((event: MessageEvent) => void) | null };
  disconnectCalls = 0;
  throwOnDisconnect = false;

  disconnect(): void {
    this.disconnectCalls += 1;
    if (this.throwOnDisconnect) throw new Error("already disconnected");
  }
}

class FakeMediaStreamSource {
  connected: unknown = null;
  disconnectCalls = 0;

  connect(node: unknown): void {
    this.connected = node;
  }

  disconnect(): void {
    this.disconnectCalls += 1;
  }
}

class FakeAudioContext {
  static instances: FakeAudioContext[] = [];
  state: "running" | "closed" = "running";
  sampleRate = 48000;
  closeCalls = 0;
  addModuleCalls: string[] = [];
  readonly createdSources: FakeMediaStreamSource[] = [];
  audioWorklet = {
    addModule: vi.fn(async (url: string) => {
      this.addModuleCalls.push(url);
    }),
  };

  constructor() {
    FakeAudioContext.instances.push(this);
  }

  createMediaStreamSource(): FakeMediaStreamSource {
    const source = new FakeMediaStreamSource();
    this.createdSources.push(source);
    return source;
  }

  async close(): Promise<void> {
    this.closeCalls += 1;
    this.state = "closed";
  }
}

/** Records track.stop() so we can assert mic teardown. */
function fakeStream(): { mediaStream: MediaStream; stops: number[] } {
  const stops: number[] = [];
  const track = {
    stop: () => {
      stops.push(1);
    },
  };
  const mediaStream = {
    getTracks: () => [track],
  } as unknown as MediaStream;
  return { mediaStream, stops };
}

function sessionResponse(over: Partial<RealtimeSessionResponse> = {}): RealtimeSessionResponse {
  return {
    provider: "deepgram",
    token: "tok 123",
    expires_in_seconds: 60,
    sample_rate: 16000,
    audio_format: "linear16",
    language: "multi",
    channels: 1,
    model: "nova-3",
    keep_alive_interval_seconds: 8,
    commit_strategy: null,
    no_verbatim: false,
    websocket_url: "wss://wai.computer/api/transcription/stream",
    auth_scheme: "query",
    ...over,
  };
}

let lastAudioWorkletNode: FakeAudioWorkletNode | null = null;

beforeEach(() => {
  vi.useFakeTimers();
  FakeWebSocket.instances = [];
  FakeAudioContext.instances = [];
  lastAudioWorkletNode = null;
  mockedCreateSession.mockReset();
  mockedDownsample.mockReset();
  mockedDownsample.mockImplementation(() => new Int16Array([1, 2, 3]));

  vi.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket);
  vi.stubGlobal("AudioContext", FakeAudioContext as unknown as typeof AudioContext);
  vi.stubGlobal("AudioWorkletNode", function AudioWorkletNodeShim() {
    const node = new FakeAudioWorkletNode();
    lastAudioWorkletNode = node;
    return node;
  } as unknown as typeof AudioWorkletNode);
});

afterEach(() => {
  vi.runOnlyPendingTimers();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

/** Drive a transcriber from idle to "recording" with the OPEN socket wired. */
async function startRecording(
  transcriber: RealtimeTranscriber,
  stream: MediaStream,
  options?: RealtimeStartOptions,
): Promise<FakeWebSocket> {
  const startPromise = transcriber.start(stream, options);
  // openSocket awaits ws.onopen; fire it on the freshly-constructed socket.
  await vi.waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
  const ws = FakeWebSocket.instances[0];
  ws.readyState = WS_OPEN;
  ws.onopen?.();
  await startPromise;
  return ws;
}

// ---------------------------------------------------------------------------
// Pure parser (kept from the original suite).
// ---------------------------------------------------------------------------

describe("parseRealtimeMessage", () => {
  it("parses a final result with a diarization speaker", () => {
    const raw = JSON.stringify({
      is_final: true,
      channel: { alternatives: [{ transcript: "Hello there", words: [{ speaker: 0 }] }] },
    });
    expect(parseRealtimeMessage(raw)).toEqual({
      transcript: "Hello there",
      isFinal: true,
      speaker: 0,
      startMs: null,
      endMs: null,
    });
  });

  it("parses an interim result (no speaker)", () => {
    const raw = JSON.stringify({
      is_final: false,
      channel: { alternatives: [{ transcript: "partial" }] },
    });
    expect(parseRealtimeMessage(raw)).toEqual({
      transcript: "partial",
      isFinal: false,
      speaker: null,
      startMs: null,
      endMs: null,
    });
  });

  it("parses provider timing from root start and duration", () => {
    const raw = JSON.stringify({
      is_final: true,
      start: 1.25,
      duration: 2.5,
      channel: { alternatives: [{ transcript: "timed result" }] },
    });
    expect(parseRealtimeMessage(raw)).toMatchObject({
      transcript: "timed result",
      startMs: 1250,
      endMs: 3750,
    });
  });

  it("falls back to word timing when root timing is absent", () => {
    const raw = JSON.stringify({
      is_final: true,
      channel: {
        alternatives: [
          {
            transcript: "word timed",
            words: [
              { word: "word", start: 0.4, end: 0.8 },
              { word: "timed", start: 0.9, end: 1.2 },
            ],
          },
        ],
      },
    });
    expect(parseRealtimeMessage(raw)).toMatchObject({
      transcript: "word timed",
      startMs: 400,
      endMs: 1200,
    });
  });

  it("returns null for an empty/whitespace transcript", () => {
    const raw = JSON.stringify({
      is_final: true,
      channel: { alternatives: [{ transcript: "   " }] },
    });
    expect(parseRealtimeMessage(raw)).toBeNull();
  });

  it("ignores non-transcript frames (Metadata, KeepAlive) and bad JSON", () => {
    expect(parseRealtimeMessage(JSON.stringify({ type: "Metadata" }))).toBeNull();
    expect(parseRealtimeMessage(JSON.stringify({ type: "KeepAlive" }))).toBeNull();
    expect(parseRealtimeMessage("not json")).toBeNull();
  });

  it("returns null when the payload is a primitive or null", () => {
    expect(parseRealtimeMessage("42")).toBeNull();
    expect(parseRealtimeMessage("null")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// RealtimeTranscriber lifecycle.
// ---------------------------------------------------------------------------

describe("RealtimeTranscriber.start", () => {
  it("transitions connecting -> recording and wires the audio graph", async () => {
    const states: string[] = [];
    const transcriber = new RealtimeTranscriber({
      language: "en",
      purpose: "dictation",
      onState: (s) => states.push(s),
    });
    mockedCreateSession.mockResolvedValue(sessionResponse());
    const a = fakeStream();
    const b = fakeStream();

    const ws = await startRecording(transcriber, [a.mediaStream, b.mediaStream] as never);

    expect(states).toEqual(["connecting", "recording"]);
    expect(transcriber.getState()).toBe("recording");
    expect(mockedCreateSession).toHaveBeenCalledWith({ language: "en", purpose: "dictation" });

    // Token is URL-encoded and appended with the right separator.
    expect(ws.url).toBe(
      "wss://wai.computer/api/transcription/stream?token=tok%20123",
    );
    expect(ws.binaryType).toBe("arraybuffer");

    // Worklet loaded + both streams connected.
    const ctx = FakeAudioContext.instances[0];
    expect(ctx.addModuleCalls).toEqual(["/realtime-pcm-worklet.js"]);
    expect(ctx.createdSources).toHaveLength(2);
    expect(ctx.createdSources.every((s) => s.connected === lastAudioWorkletNode)).toBe(true);
  });

  it("is a no-op when already past idle", async () => {
    const transcriber = new RealtimeTranscriber();
    mockedCreateSession.mockResolvedValue(sessionResponse());
    await startRecording(transcriber, fakeStream().mediaStream);

    mockedCreateSession.mockClear();
    await transcriber.start(fakeStream().mediaStream);

    expect(mockedCreateSession).not.toHaveBeenCalled();
    expect(transcriber.getState()).toBe("recording");
  });

  it("defaults purpose to recording when not supplied", async () => {
    const transcriber = new RealtimeTranscriber();
    mockedCreateSession.mockResolvedValue(sessionResponse());
    await startRecording(transcriber, fakeStream().mediaStream);

    expect(mockedCreateSession).toHaveBeenCalledWith({ language: undefined, purpose: "recording" });
  });

  it("fails with the error message when session creation rejects", async () => {
    const errors: string[] = [];
    const states: string[] = [];
    const transcriber = new RealtimeTranscriber({
      onError: (m) => errors.push(m),
      onState: (s) => states.push(s),
    });
    mockedCreateSession.mockRejectedValue(new Error("quota exceeded"));

    await transcriber.start(fakeStream().mediaStream);

    expect(errors).toEqual(["quota exceeded"]);
    expect(states).toEqual(["connecting", "error"]);
    expect(transcriber.getState()).toBe("error");
    // No socket should have been opened.
    expect(FakeWebSocket.instances).toHaveLength(0);
  });

  it("uses a generic message when the rejection is not an Error", async () => {
    const errors: string[] = [];
    const transcriber = new RealtimeTranscriber({ onError: (m) => errors.push(m) });
    mockedCreateSession.mockRejectedValue("nope");

    await transcriber.start(fakeStream().mediaStream);

    expect(errors).toEqual(["Realtime transcription error"]);
  });

  it("fails and tears down when the socket errors before opening", async () => {
    const errors: string[] = [];
    const transcriber = new RealtimeTranscriber({ onError: (m) => errors.push(m) });
    mockedCreateSession.mockResolvedValue(sessionResponse());
    const stream = fakeStream();

    const startPromise = transcriber.start(stream.mediaStream);
    await vi.waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
    const ws = FakeWebSocket.instances[0];
    ws.onerror?.();
    await startPromise;

    expect(transcriber.getState()).toBe("error");
    expect(errors).toEqual(["Realtime transcription connection failed"]);
    // Socket was closed during cleanup; mic tracks stopped.
    expect(ws.closeCalls).toBe(1);
    expect(stream.stops).toEqual([1]);
  });
});

describe("RealtimeTranscriber socket URL building", () => {
  it("appends token with & when the websocket_url already has a query string", async () => {
    const transcriber = new RealtimeTranscriber();
    mockedCreateSession.mockResolvedValue(
      sessionResponse({ websocket_url: "wss://host/stream?x=1" }),
    );
    const ws = await startRecording(transcriber, fakeStream().mediaStream);
    expect(ws.url).toBe("wss://host/stream?x=1&token=tok%20123");
  });

  it("passes realtime dictionary hints when creating the session", async () => {
    const transcriber = new RealtimeTranscriber({
      language: "ru",
      purpose: "dictation",
      keyterms: ["WaiComputer"],
      replacements: [{ find: "wai computer", replace: "WaiComputer" }],
    });
    mockedCreateSession.mockResolvedValue(sessionResponse());

    await startRecording(transcriber, fakeStream().mediaStream);

    expect(mockedCreateSession).toHaveBeenCalledWith({
      language: "ru",
      purpose: "dictation",
      keyterms: ["WaiComputer"],
      replacements: [{ find: "wai computer", replace: "WaiComputer" }],
    });
  });

  it("uses a matching prefetched session without minting during start", async () => {
    const request = {
      language: "ru",
      purpose: "dictation" as const,
      keyterms: ["WaiComputer"],
      replacements: [{ find: "wai computer", replace: "WaiComputer" }],
    };
    const transcriber = new RealtimeTranscriber(request);
    const ws = await startRecording(transcriber, fakeStream().mediaStream, {
      prefetchedSession: {
        request,
        session: sessionResponse({
          token: "warm token",
          websocket_url: "wss://wai.computer/api/transcription/stream",
        }),
      },
    });

    expect(mockedCreateSession).not.toHaveBeenCalled();
    expect(ws.url).toBe("wss://wai.computer/api/transcription/stream?token=warm%20token");
  });

  it("mints a fresh session instead of using stale prefetched hints", async () => {
    const transcriber = new RealtimeTranscriber({
      purpose: "dictation",
      keyterms: ["Current"],
    });
    mockedCreateSession.mockResolvedValue(sessionResponse({ token: "fresh token" }));

    const ws = await startRecording(transcriber, fakeStream().mediaStream, {
      prefetchedSession: {
        request: {
          purpose: "dictation",
          keyterms: ["Stale"],
        },
        session: sessionResponse({ token: "stale token" }),
      },
    });

    expect(mockedCreateSession).toHaveBeenCalledWith({
      language: undefined,
      purpose: "dictation",
      keyterms: ["Current"],
      replacements: undefined,
    });
    expect(ws.url).toBe("wss://wai.computer/api/transcription/stream?token=fresh%20token");
  });

  it("falls back to window.location (wss for https) when websocket_url is null", async () => {
    Object.defineProperty(window, "location", {
      value: { protocol: "https:", host: "wai.computer" },
      writable: true,
    });
    const transcriber = new RealtimeTranscriber();
    mockedCreateSession.mockResolvedValue(sessionResponse({ websocket_url: null }));
    const ws = await startRecording(transcriber, fakeStream().mediaStream);
    expect(ws.url).toBe("wss://wai.computer/api/transcription/stream?token=tok%20123");
  });

  it("falls back to ws for http", async () => {
    Object.defineProperty(window, "location", {
      value: { protocol: "http:", host: "localhost:3000" },
      writable: true,
    });
    const transcriber = new RealtimeTranscriber();
    mockedCreateSession.mockResolvedValue(sessionResponse({ websocket_url: null }));
    const ws = await startRecording(transcriber, fakeStream().mediaStream);
    expect(ws.url).toBe("ws://localhost:3000/api/transcription/stream?token=tok%20123");
  });
});

describe("RealtimeTranscriber keep-alive", () => {
  it("sends a KeepAlive frame on the configured interval while OPEN", async () => {
    const transcriber = new RealtimeTranscriber();
    mockedCreateSession.mockResolvedValue(sessionResponse({ keep_alive_interval_seconds: 5 }));
    const ws = await startRecording(transcriber, fakeStream().mediaStream);

    vi.advanceTimersByTime(5000);
    expect(ws.sent).toContainEqual(JSON.stringify({ type: "KeepAlive" }));

    // When the socket is no longer OPEN, the interval stops sending.
    ws.readyState = WS_CLOSED;
    const before = ws.sent.length;
    vi.advanceTimersByTime(10000);
    expect(ws.sent.length).toBe(before);
  });

  it("defaults the keep-alive interval to the provider-safe 4s when null", async () => {
    const transcriber = new RealtimeTranscriber();
    mockedCreateSession.mockResolvedValue(sessionResponse({ keep_alive_interval_seconds: null }));
    const ws = await startRecording(transcriber, fakeStream().mediaStream);

    vi.advanceTimersByTime(3999);
    expect(ws.sent).not.toContainEqual(JSON.stringify({ type: "KeepAlive" }));
    vi.advanceTimersByTime(1);
    expect(ws.sent).toContainEqual(JSON.stringify({ type: "KeepAlive" }));
  });
});

describe("RealtimeTranscriber audio streaming", () => {
  it("buffers startup PCM while the socket is CONNECTING and flushes it first", async () => {
    const transcriber = new RealtimeTranscriber();
    mockedCreateSession.mockResolvedValue(sessionResponse());
    const startPromise = transcriber.start(fakeStream().mediaStream);

    await vi.waitFor(() => expect(lastAudioWorkletNode).not.toBeNull());
    const startupFloat = new Float32Array([0.1, 0.2]);
    const startupInt16 = new Int16Array([7, 8]);
    mockedDownsample.mockReturnValueOnce(startupInt16);
    lastAudioWorkletNode?.port.onmessage?.({ data: startupFloat } as MessageEvent);

    await vi.waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
    const ws = FakeWebSocket.instances[0];
    expect(ws.readyState).toBe(WS_CONNECTING);
    expect(ws.sent).toEqual([]);

    ws.readyState = WS_OPEN;
    ws.onopen?.();
    await startPromise;

    expect(mockedDownsample).toHaveBeenCalledWith(startupFloat, 48000);
    expect(ws.sent[0]).toBe(startupInt16.buffer);

    const liveFloat = new Float32Array([0.3, 0.4]);
    const liveInt16 = new Int16Array([9, 10]);
    mockedDownsample.mockReturnValueOnce(liveInt16);
    lastAudioWorkletNode?.port.onmessage?.({ data: liveFloat } as MessageEvent);

    expect(ws.sent[1]).toBe(liveInt16.buffer);
  });

  it("downsamples worklet PCM and sends the Int16 buffer over an OPEN socket", async () => {
    const transcriber = new RealtimeTranscriber();
    mockedCreateSession.mockResolvedValue(sessionResponse());
    const ws = await startRecording(transcriber, fakeStream().mediaStream);

    const float = new Float32Array([0.1, 0.2]);
    const int16 = new Int16Array([7, 8]);
    mockedDownsample.mockReturnValue(int16);

    lastAudioWorkletNode?.port.onmessage?.({ data: float } as MessageEvent);

    expect(mockedDownsample).toHaveBeenCalledWith(float, 48000);
    expect(ws.sent).toContainEqual(int16.buffer);
  });

  it("fails and tears down when live PCM cannot be sent", async () => {
    const errors: string[] = [];
    const states: string[] = [];
    const transcriber = new RealtimeTranscriber({
      onError: (message) => errors.push(message),
      onState: (state) => states.push(state),
    });
    mockedCreateSession.mockResolvedValue(sessionResponse());
    const stream = fakeStream();
    const ws = await startRecording(transcriber, stream.mediaStream);

    ws.throwOnSend = true;
    mockedDownsample.mockReturnValue(new Int16Array([11, 12]));
    lastAudioWorkletNode?.port.onmessage?.({ data: new Float32Array([0.5]) } as MessageEvent);

    expect(errors).toEqual(["send failed"]);
    expect(states.at(-1)).toBe("error");
    expect(transcriber.getState()).toBe("error");
    expect(stream.stops).toEqual([1]);
    expect(ws.closeCalls).toBe(1);
  });

  it("fails startup when buffered PCM cannot be flushed to the opened socket", async () => {
    const errors: string[] = [];
    const transcriber = new RealtimeTranscriber({ onError: (message) => errors.push(message) });
    mockedCreateSession.mockResolvedValue(sessionResponse());
    const stream = fakeStream();
    const startPromise = transcriber.start(stream.mediaStream);

    await vi.waitFor(() => expect(lastAudioWorkletNode).not.toBeNull());
    mockedDownsample.mockReturnValueOnce(new Int16Array([21, 22]));
    lastAudioWorkletNode?.port.onmessage?.({ data: new Float32Array([0.2]) } as MessageEvent);
    await vi.waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));

    const ws = FakeWebSocket.instances[0];
    ws.throwOnSend = true;
    ws.readyState = WS_OPEN;
    ws.onopen?.();
    await startPromise;

    expect(errors).toEqual(["send failed"]);
    expect(transcriber.getState()).toBe("error");
    expect(stream.stops).toEqual([1]);
  });

  it("drops worklet PCM when the socket is not OPEN", async () => {
    const transcriber = new RealtimeTranscriber();
    mockedCreateSession.mockResolvedValue(sessionResponse());
    const ws = await startRecording(transcriber, fakeStream().mediaStream);

    ws.readyState = WS_CLOSED;
    const before = ws.sent.length;
    mockedDownsample.mockReturnValue(new Int16Array([9]));
    lastAudioWorkletNode?.port.onmessage?.({ data: new Float32Array([0.5]) } as MessageEvent);

    expect(ws.sent.length).toBe(before);
  });
});

describe("RealtimeTranscriber keep-alive failures", () => {
  it("fails and tears down when a KeepAlive frame cannot be sent", async () => {
    const errors: string[] = [];
    const states: string[] = [];
    const transcriber = new RealtimeTranscriber({
      onError: (message) => errors.push(message),
      onState: (state) => states.push(state),
    });
    mockedCreateSession.mockResolvedValue(sessionResponse({ keep_alive_interval_seconds: 5 }));
    const stream = fakeStream();
    const ws = await startRecording(transcriber, stream.mediaStream);

    ws.throwOnSend = true;
    vi.advanceTimersByTime(5000);

    expect(errors).toEqual(["send failed"]);
    expect(states.at(-1)).toBe("error");
    expect(transcriber.getState()).toBe("error");
    expect(stream.stops).toEqual([1]);
    expect(ws.closeCalls).toBe(1);
  });
});

describe("RealtimeTranscriber.onMessage", () => {
  it("accumulates final segments with speaker labels and clears interim", async () => {
    const updates: Array<{ committed: string; interim: string }> = [];
    const transcriber = new RealtimeTranscriber({ onUpdate: (u) => updates.push(u) });
    mockedCreateSession.mockResolvedValue(sessionResponse());
    const ws = await startRecording(transcriber, fakeStream().mediaStream);

    // Interim first, then two finals — committed text joins with a space.
    ws.onmessage?.({
      data: JSON.stringify({ is_final: false, channel: { alternatives: [{ transcript: "hel" }] } }),
    } as MessageEvent);
    ws.onmessage?.({
      data: JSON.stringify({
        is_final: true,
        channel: { alternatives: [{ transcript: "hello", words: [{ speaker: 0 }] }] },
      }),
    } as MessageEvent);
    ws.onmessage?.({
      data: JSON.stringify({
        is_final: true,
        channel: { alternatives: [{ transcript: "world", words: [{ speaker: 2 }] }] },
      }),
    } as MessageEvent);

    expect(updates.at(-1)).toEqual({ committed: "hello world", interim: "" });

    const segments = transcriber.getSegments();
    expect(segments).toHaveLength(2);
    expect(segments[0]).toMatchObject({ text: "hello", speaker: "Speaker 1" });
    expect(segments[1]).toMatchObject({ text: "world", speaker: "Speaker 3" });
    // start/end timestamps chain: second segment starts where the first ended.
    expect(segments[1].start_ms).toBe(segments[0].end_ms);
  });

  it("stores null speaker when diarization is absent", async () => {
    const transcriber = new RealtimeTranscriber();
    mockedCreateSession.mockResolvedValue(sessionResponse());
    const ws = await startRecording(transcriber, fakeStream().mediaStream);

    ws.onmessage?.({
      data: JSON.stringify({ is_final: true, channel: { alternatives: [{ transcript: "solo" }] } }),
    } as MessageEvent);

    expect(transcriber.getSegments()[0]).toMatchObject({ text: "solo", speaker: null });
  });

  it("replaces an earlier final when the provider sends an extended final for the same range", async () => {
    const updates: Array<{ committed: string; interim: string }> = [];
    const transcriber = new RealtimeTranscriber({ onUpdate: (u) => updates.push(u) });
    mockedCreateSession.mockResolvedValue(sessionResponse());
    const ws = await startRecording(transcriber, fakeStream().mediaStream);

    ws.onmessage?.({
      data: JSON.stringify({
        is_final: true,
        start: 0,
        duration: 1.0,
        channel: { alternatives: [{ transcript: "hello world", words: [{ speaker: 0 }] }] },
      }),
    } as MessageEvent);
    ws.onmessage?.({
      data: JSON.stringify({
        is_final: true,
        start: 0,
        duration: 1.8,
        channel: { alternatives: [{ transcript: "hello world today", words: [{ speaker: 0 }] }] },
      }),
    } as MessageEvent);

    expect(updates.at(-1)).toEqual({ committed: "hello world today", interim: "" });
    expect(transcriber.getSegments()).toEqual([
      {
        text: "hello world today",
        speaker: "Speaker 1",
        start_ms: 0,
        end_ms: 1800,
      },
    ]);
  });

  it("drops an exact duplicate final for the same provider range", async () => {
    const updates: Array<{ committed: string; interim: string }> = [];
    const transcriber = new RealtimeTranscriber({ onUpdate: (u) => updates.push(u) });
    mockedCreateSession.mockResolvedValue(sessionResponse());
    const ws = await startRecording(transcriber, fakeStream().mediaStream);

    const frame = {
      is_final: true,
      start: 0.2,
      duration: 0.9,
      channel: { alternatives: [{ transcript: "repeat me", words: [{ speaker: 0 }] }] },
    };
    ws.onmessage?.({ data: JSON.stringify(frame) } as MessageEvent);
    ws.onmessage?.({ data: JSON.stringify(frame) } as MessageEvent);

    expect(updates.at(-1)).toEqual({ committed: "repeat me", interim: "" });
    expect(transcriber.getSegments()).toHaveLength(1);
    expect(transcriber.getSegments()[0]).toMatchObject({
      text: "repeat me",
      start_ms: 200,
      end_ms: 1100,
    });
  });

  it("updates interim text without committing for non-final frames", async () => {
    const updates: Array<{ committed: string; interim: string }> = [];
    const transcriber = new RealtimeTranscriber({ onUpdate: (u) => updates.push(u) });
    mockedCreateSession.mockResolvedValue(sessionResponse());
    const ws = await startRecording(transcriber, fakeStream().mediaStream);

    ws.onmessage?.({
      data: JSON.stringify({ is_final: false, channel: { alternatives: [{ transcript: "typing" }] } }),
    } as MessageEvent);

    expect(updates.at(-1)).toEqual({ committed: "", interim: "typing" });
    expect(transcriber.getSegments()).toHaveLength(0);
  });

  it("ignores binary frames and unparseable strings", async () => {
    const updates: unknown[] = [];
    const transcriber = new RealtimeTranscriber({ onUpdate: (u) => updates.push(u) });
    mockedCreateSession.mockResolvedValue(sessionResponse());
    const ws = await startRecording(transcriber, fakeStream().mediaStream);

    ws.onmessage?.({ data: new ArrayBuffer(4) } as MessageEvent);
    ws.onmessage?.({ data: "not json" } as MessageEvent);

    expect(updates).toHaveLength(0);
    expect(transcriber.getSegments()).toHaveLength(0);
  });
});

describe("RealtimeTranscriber.stop", () => {
  it("sends CloseStream, tears down, and returns the collected segments", async () => {
    const states: string[] = [];
    const transcriber = new RealtimeTranscriber({ onState: (s) => states.push(s) });
    mockedCreateSession.mockResolvedValue(sessionResponse());
    const stream = fakeStream();
    const ws = await startRecording(transcriber, stream.mediaStream);
    const ctx = FakeAudioContext.instances[0];

    ws.onmessage?.({
      data: JSON.stringify({ is_final: true, channel: { alternatives: [{ transcript: "done" }] } }),
    } as MessageEvent);

    const stopPromise = transcriber.stop();
    expect(ws.sent).toContainEqual(JSON.stringify({ type: "Finalize" }));
    await vi.advanceTimersByTimeAsync(2500);
    expect(ws.sent).toContainEqual(JSON.stringify({ type: "CloseStream" }));
    ws.readyState = WS_CLOSED;
    ws.onclose?.();
    const segments = await stopPromise;

    expect(states).toEqual(["connecting", "recording", "stopping", "idle"]);
    expect(transcriber.getState()).toBe("idle");
    expect(segments).toHaveLength(1);
    // cleanup() side effects.
    expect(ws.closeCalls).toBe(0);
    expect(ctx.closeCalls).toBe(1);
    expect(stream.stops).toEqual([1]);
  });

  it("waits for final frames after CloseStream before tearing down the socket", async () => {
    const transcriber = new RealtimeTranscriber();
    mockedCreateSession.mockResolvedValue(sessionResponse());
    const stream = fakeStream();
    const ws = await startRecording(transcriber, stream.mediaStream);

    const stopPromise = transcriber.stop();
    const settled = vi.fn();
    stopPromise.then(settled, settled);
    await Promise.resolve();

    expect(ws.sent).toContainEqual(JSON.stringify({ type: "Finalize" }));
    expect(ws.closeCalls).toBe(0);
    expect(settled).not.toHaveBeenCalled();
    expect(stream.stops).toEqual([1]);

    ws.onmessage?.({
      data: JSON.stringify({
        is_final: true,
        from_finalize: true,
        channel: { alternatives: [{ transcript: "late final" }] },
      }),
    } as MessageEvent);
    await vi.advanceTimersByTimeAsync(650);
    expect(ws.sent).toContainEqual(JSON.stringify({ type: "CloseStream" }));
    ws.readyState = WS_CLOSED;
    ws.onclose?.();

    await expect(stopPromise).resolves.toMatchObject([{ text: "late final" }]);
    expect(transcriber.getState()).toBe("idle");
  });

  it("returns late final frames after a quiet drain even when the provider socket stays open", async () => {
    const transcriber = new RealtimeTranscriber();
    mockedCreateSession.mockResolvedValue(sessionResponse());
    const stream = fakeStream();
    const ws = await startRecording(transcriber, stream.mediaStream);

    const stopPromise = transcriber.stop();
    await vi.advanceTimersByTimeAsync(2500);
    expect(ws.sent).toContainEqual(JSON.stringify({ type: "CloseStream" }));
    let settled: "resolved" | "rejected" | undefined;
    stopPromise.then(
      () => {
        settled = "resolved";
      },
      () => {
        settled = "rejected";
      },
    );

    ws.onmessage?.({
      data: JSON.stringify({
        is_final: true,
        channel: { alternatives: [{ transcript: "late quiet final" }] },
      }),
    } as MessageEvent);
    await vi.advanceTimersByTimeAsync(1000);

    expect(settled).toBe("resolved");
    await expect(stopPromise).resolves.toMatchObject([{ text: "late quiet final" }]);
    expect(ws.closeCalls).toBe(1);
    expect(transcriber.getState()).toBe("idle");
  });

  it("returns existing segments without re-stopping when idle", async () => {
    const states: string[] = [];
    const transcriber = new RealtimeTranscriber({ onState: (s) => states.push(s) });

    const segments = await transcriber.stop();

    expect(segments).toEqual([]);
    expect(states).toEqual([]);
    expect(FakeWebSocket.instances).toHaveLength(0);
  });

  it("cancels a CONNECTING socket and lets start settle", async () => {
    const transcriber = new RealtimeTranscriber();
    mockedCreateSession.mockResolvedValue(sessionResponse());
    const stream = fakeStream();
    const startPromise = transcriber.start(stream.mediaStream);

    await vi.waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
    const ws = FakeWebSocket.instances[0];
    const stopPromise = transcriber.stop();

    await expect(stopPromise).resolves.toEqual([]);
    expect(ws.closeCalls).toBe(1);
    expect(stream.stops).toEqual([1]);

    let startSettled = false;
    startPromise.finally(() => {
      startSettled = true;
    });
    ws.onclose?.();

    await vi.waitFor(() => expect(startSettled).toBe(true));
    await expect(startPromise).resolves.toBeUndefined();
    expect(transcriber.getState()).toBe("idle");
  });

  it("rejects when CloseStream cannot be sent", async () => {
    const errors: string[] = [];
    const transcriber = new RealtimeTranscriber({ onError: (message) => errors.push(message) });
    mockedCreateSession.mockResolvedValue(sessionResponse());
    const ws = await startRecording(transcriber, fakeStream().mediaStream);
    ws.throwOnSend = true;

    await expect(transcriber.stop()).rejects.toThrow("send failed");
    expect(transcriber.getState()).toBe("error");
    expect(errors).toEqual([]);
  });

  it("closes locally when the provider close drain has no transcript activity", async () => {
    const transcriber = new RealtimeTranscriber();
    mockedCreateSession.mockResolvedValue(sessionResponse());
    const ws = await startRecording(transcriber, fakeStream().mediaStream);

    const stopPromise = transcriber.stop();
    await vi.advanceTimersByTimeAsync(2500);
    expect(ws.sent).toContainEqual(JSON.stringify({ type: "CloseStream" }));
    await vi.advanceTimersByTimeAsync(2500);

    await expect(stopPromise).resolves.toEqual([]);
    expect(ws.closeCalls).toBe(1);
    expect(transcriber.getState()).toBe("idle");
  });
});

describe("RealtimeTranscriber unexpected close", () => {
  it("surfaces a dropped connection while recording and moves to error", async () => {
    const errors: string[] = [];
    const states: string[] = [];
    const transcriber = new RealtimeTranscriber({
      onError: (m) => errors.push(m),
      onState: (s) => states.push(s),
    });
    mockedCreateSession.mockResolvedValue(sessionResponse());
    const stream = fakeStream();
    const ws = await startRecording(transcriber, stream.mediaStream);

    ws.onclose?.();

    expect(errors).toEqual(["Realtime connection lost"]);
    expect(states.at(-1)).toBe("error");
    expect(transcriber.getState()).toBe("error");
    expect(stream.stops).toEqual([1]);
  });

  it("ignores close events when not actively recording", async () => {
    const errors: string[] = [];
    const transcriber = new RealtimeTranscriber({ onError: (m) => errors.push(m) });
    mockedCreateSession.mockResolvedValue(sessionResponse());
    const ws = await startRecording(transcriber, fakeStream().mediaStream);

    const stopPromise = transcriber.stop();
    ws.readyState = WS_CLOSED;
    ws.onclose?.();
    await stopPromise; // -> idle, also closes the socket
    errors.length = 0;
    ws.onclose?.();

    expect(errors).toEqual([]);
  });
});

describe("RealtimeTranscriber.cleanup resilience", () => {
  it("swallows disconnect errors from the worklet node and sources", async () => {
    const transcriber = new RealtimeTranscriber();
    mockedCreateSession.mockResolvedValue(sessionResponse());
    const ws = await startRecording(transcriber, fakeStream().mediaStream);

    // Force the node disconnect to throw; cleanup must not propagate it.
    if (lastAudioWorkletNode) lastAudioWorkletNode.throwOnDisconnect = true;

    const stopPromise = transcriber.stop();
    ws.readyState = WS_CLOSED;
    ws.onclose?.();

    await expect(stopPromise).resolves.toBeDefined();
    expect(transcriber.getState()).toBe("idle");
  });
});
