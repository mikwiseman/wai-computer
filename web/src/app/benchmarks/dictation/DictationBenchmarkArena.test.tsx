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
  mimeType = "audio/webm";

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

class FakeAudioContext {
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
    };
  }

  close() {
    return Promise.resolve();
  }
}

function installMediaDevices() {
  vi.stubGlobal("MediaRecorder", FakeMediaRecorder);
  vi.stubGlobal("AudioContext", FakeAudioContext);
  Object.defineProperty(window.navigator, "mediaDevices", {
    configurable: true,
    value: {
      getUserMedia: vi.fn().mockResolvedValue({
        getTracks: () => [{ stop: vi.fn() }],
      }),
    },
  });
}

describe("DictationBenchmarkArena", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    mockedCreateBattle.mockReset();
    mockedSubmitVote.mockReset();
  });

  it("renders the locked active STT stack", () => {
    render(<DictationBenchmarkArena />);

    expect(screen.getByText("ElevenLabs")).toBeInTheDocument();
    expect(screen.getByText("Single active file STT model.")).toBeInTheDocument();
  });

  it("records once, uploads audio, and reveals ElevenLabs Scribe v2 after review", async () => {
    installMediaDevices();
    mockedCreateBattle.mockResolvedValue({
      battle_id: "battle-1",
      language: "multi",
      candidates: [
        {
          id: "a",
          provider: "elevenlabs",
          model: "scribe_v2",
          label: "ElevenLabs Scribe v2",
          status: "ok",
          transcript: "hello world",
          latency_ms: 1200,
          word_count: 2,
          error: null,
        },
      ],
    });

    render(<DictationBenchmarkArena />);
    await userEvent.click(screen.getByRole("button", { name: /Start recording/i }));
    await userEvent.click(await screen.findByRole("button", { name: /Stop and transcribe/i }));

    expect(await screen.findByText("hello world")).toBeInTheDocument();
    expect(mockedCreateBattle).toHaveBeenCalledWith({
      audio: expect.any(Blob),
      filename: "dictation-benchmark.webm",
      language: "multi",
    });

    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));

    expect(mockedSubmitVote).toHaveBeenCalledWith({
      battle_id: "battle-1",
      selected_candidate_id: "a",
      selected_provider: "elevenlabs",
      selected_model: "scribe_v2",
      language: "multi",
      candidate_count: 1,
    });
    expect(screen.getByText("elevenlabs / scribe_v2")).toBeInTheDocument();
  });
});
