import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createDictationBenchmarkBattle } from "@/lib/api";
import { DictationBenchmarkArena } from "./DictationBenchmarkArena";

vi.mock("@/lib/api", () => ({
  createDictationBenchmarkBattle: vi.fn(),
}));

const mockedCreateBattle = vi.mocked(createDictationBenchmarkBattle);

class FakeMediaRecorder {
  static isTypeSupported = vi.fn(() => true);
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;

  constructor(public stream: MediaStream, public options?: MediaRecorderOptions) {}

  start() {}

  stop() {
    this.ondataavailable?.({ data: new Blob(["audio"], { type: "audio/webm" }) });
    this.onstop?.();
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
  return { stop };
}

describe("DictationBenchmarkArena", () => {
  beforeEach(() => {
    mockedCreateBattle.mockReset();
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
    await userEvent.click(screen.getByRole("button", { name: /Stop and compare/i }));

    expect(await screen.findByText("hello world")).toBeInTheDocument();
    expect(mockedCreateBattle).toHaveBeenCalledWith({
      audio: expect.any(Blob),
      filename: "dictation-benchmark.webm",
      language: "multi",
    });
    expect(screen.getAllByText("Model hidden")).toHaveLength(2);

    await userEvent.click(screen.getAllByRole("button", { name: "Pick winner" })[0]);

    expect(screen.getByText("Soniox v4 Async")).toBeInTheDocument();
    expect(screen.getByText("soniox / stt-async-v4")).toBeInTheDocument();
  });
});
