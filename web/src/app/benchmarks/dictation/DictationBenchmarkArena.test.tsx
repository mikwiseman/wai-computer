import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createDictationBenchmarkBattle, submitDictationBenchmarkVote } from "@/lib/api";
import { DictationBenchmarkArena } from "./DictationBenchmarkArena";

vi.mock("@/lib/api", () => ({
  createDictationBenchmarkBattle: vi.fn(),
  submitDictationBenchmarkVote: vi.fn(),
}));

const mockedCreateBattle = vi.mocked(createDictationBenchmarkBattle);
const mockedSubmitVote = vi.mocked(submitDictationBenchmarkVote);

class FakeMediaRecorder {
  static isTypeSupported = vi.fn(() => true);
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  state: RecordingState = "inactive";

  constructor(public stream: MediaStream, public options?: MediaRecorderOptions) {}

  start() {
    this.state = "recording";
  }

  stop() {
    this.state = "inactive";
    this.ondataavailable?.({ data: new Blob(["audio"], { type: "audio/webm" }) });
    this.onstop?.();
  }
}

const liveCandidates = [
  {
    id: "live-a",
    provider: "elevenlabs",
    model: "scribe_v2_realtime",
    label: "ElevenLabs Scribe v2 Realtime",
    status: "running",
    transcript: null,
    latency_ms: null,
    word_count: 0,
    error: null,
  },
  {
    id: "live-b",
    provider: "soniox",
    model: "stt-rt-v4",
    label: "Soniox v4 Realtime",
    status: "running",
    transcript: null,
    latency_ms: null,
    word_count: 0,
    error: null,
  },
  {
    id: "live-c",
    provider: "deepgram",
    model: "flux-general-multi",
    label: "Deepgram Flux Multilingual",
    status: "running",
    transcript: null,
    latency_ms: null,
    word_count: 0,
    error: null,
  },
];

class FakeAudioContext {
  sampleRate = 48_000;
  destination = {};

  createAnalyser() {
    return {
      fftSize: 1024,
      getByteTimeDomainData: (data: Uint8Array) => data.fill(128),
    };
  }

  createMediaStreamSource() {
    return {
      connect: vi.fn(),
      disconnect: vi.fn(),
    };
  }

  createScriptProcessor() {
    return {
      onaudioprocess: null,
      connect: vi.fn(),
      disconnect: vi.fn(),
    };
  }

  close() {
    return Promise.resolve();
  }
}

const fakeSockets: FakeWebSocket[] = [];

class FakeWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  binaryType: BinaryType = "blob";
  readyState = FakeWebSocket.CONNECTING;
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  sent: Array<string | ArrayBuffer | Blob | ArrayBufferView> = [];

  constructor(public url: string) {
    fakeSockets.push(this);
    window.setTimeout(() => {
      this.readyState = FakeWebSocket.OPEN;
      this.onopen?.(new Event("open"));
      this.emit({
        type: "battle_started",
        battle_id: "live-battle-1",
        language: "multi",
        candidates: liveCandidates,
      });
      this.emit({
        type: "candidate_update",
        battle_id: "live-battle-1",
        is_final: true,
        candidate: {
          ...liveCandidates[0],
          status: "ok",
          transcript: "live hello",
          latency_ms: 220,
          word_count: 2,
        },
      });
    }, 0);
  }

  send(data: string | ArrayBuffer | Blob | ArrayBufferView) {
    this.sent.push(data);
    if (typeof data === "string" && data.includes("finish")) {
      this.emit({ type: "battle_finished", battle_id: "live-battle-1" });
    }
  }

  close() {
    this.readyState = FakeWebSocket.CLOSED;
  }

  private emit(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) } as MessageEvent<string>);
  }
}

function installMediaDevices() {
  const stop = vi.fn();
  const stream = {
    getTracks: () => [{ stop }],
  } as unknown as MediaStream;
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: {
      getUserMedia: vi.fn().mockResolvedValue(stream),
    },
  });
  Object.defineProperty(globalThis, "MediaRecorder", {
    configurable: true,
    value: FakeMediaRecorder,
  });
  Object.defineProperty(window, "AudioContext", {
    configurable: true,
    value: FakeAudioContext,
  });
  Object.defineProperty(window, "WebSocket", {
    configurable: true,
    value: FakeWebSocket,
  });
  Object.defineProperty(globalThis, "WebSocket", {
    configurable: true,
    value: FakeWebSocket,
  });
  return { stop };
}

describe("DictationBenchmarkArena", () => {
  beforeEach(() => {
    mockedCreateBattle.mockReset();
    mockedSubmitVote.mockReset();
    mockedSubmitVote.mockResolvedValue({ vote_id: "vote-1" });
    fakeSockets.length = 0;
    vi.spyOn(window, "requestAnimationFrame").mockReturnValue(1);
    vi.spyOn(window, "cancelAnimationFrame").mockImplementation(() => undefined);
  });

  it("shows an unavailable message when microphone APIs are missing", async () => {
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: undefined,
    });

    render(<DictationBenchmarkArena />);
    await userEvent.click(screen.getByRole("button", { name: /Start dictation battle/i }));

    expect(screen.getByText(/Microphone recording is not available/i)).toBeInTheDocument();
  });

  it("shows a clear message when microphone permission is blocked", async () => {
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        getUserMedia: vi.fn().mockRejectedValue(new DOMException("Permission denied", "NotAllowedError")),
      },
    });

    render(<DictationBenchmarkArena />);
    await userEvent.click(screen.getByRole("button", { name: /Start dictation battle/i }));

    expect(screen.getByText(/Microphone access was blocked/i)).toBeInTheDocument();
  });

  it("shows a live battle state while providers are transcribing", async () => {
    installMediaDevices();
    let resolveBattle: (value: Awaited<ReturnType<typeof createDictationBenchmarkBattle>>) => void;
    mockedCreateBattle.mockReturnValue(
      new Promise((resolve) => {
        resolveBattle = resolve;
      }),
    );

    render(<DictationBenchmarkArena />);
    await userEvent.click(screen.getByRole("button", { name: /Start dictation battle/i }));
    expect(await screen.findByText("live hello")).toBeInTheDocument();
    await userEvent.click(await screen.findByRole("button", { name: /Stop and compare/i }));

    expect(await screen.findByText(/Same audio is now racing through the models/i)).toBeInTheDocument();
    expect(screen.getAllByText(/Listening for live transcript/i)).toHaveLength(2);

    resolveBattle!({
      battle_id: "battle-1",
      language: "multi",
      candidates: [
        {
          id: "a",
          provider: "soniox",
          model: "stt-async-v4",
          label: "Soniox v4 Async",
          status: "ok",
          transcript: "hello world",
          latency_ms: 1200,
          word_count: 2,
          error: null,
        },
      ],
    });

    expect(await screen.findByText("hello world")).toBeInTheDocument();
  });

  it("records once, uploads the audio, and reveals model labels after a vote", async () => {
    installMediaDevices();
    mockedCreateBattle.mockResolvedValue({
      battle_id: "battle-1",
      language: "multi",
      candidates: [
        {
          id: "a",
          provider: "soniox",
          model: "stt-async-v4",
          label: "Soniox v4 Async",
          status: "ok",
          transcript: "hello world",
          latency_ms: 1200,
          word_count: 2,
          error: null,
        },
        {
          id: "b",
          provider: "elevenlabs",
          model: "scribe_v2",
          label: "ElevenLabs Scribe v2",
          status: "ok",
          transcript: "hello word",
          latency_ms: 1500,
          word_count: 2,
          error: null,
        },
      ],
    });

    render(<DictationBenchmarkArena />);
    await userEvent.click(screen.getByRole("button", { name: /Start dictation battle/i }));
    await userEvent.click(await screen.findByRole("button", { name: /Stop and compare/i }));

    expect(await screen.findByText("hello world")).toBeInTheDocument();
    expect(mockedCreateBattle).toHaveBeenCalledWith({
      audio: expect.any(Blob),
      filename: "dictation-benchmark.webm",
      language: "multi",
    });
    expect(screen.getAllByText("Model hidden").length).toBeGreaterThanOrEqual(2);

    await userEvent.click(screen.getAllByRole("button", { name: "Pick winner" })[0]);

    expect(mockedSubmitVote).toHaveBeenCalledWith({
      battle_id: "battle-1",
      selected_candidate_id: "a",
      selected_provider: "soniox",
      selected_model: "stt-async-v4",
      language: "multi",
      candidate_count: 2,
    });
    expect(screen.getAllByText("Soniox v4 Async").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("soniox / stt-async-v4")).toBeInTheDocument();
  });
});
