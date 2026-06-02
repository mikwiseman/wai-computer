import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/http";
import { createDictationBenchmarkBattle, submitDictationBenchmarkVote } from "@/lib/api";
import type { DictationBenchmarkBattleResponse } from "@/lib/types";
import { DictationBenchmarkArena } from "./DictationBenchmarkArena";

vi.mock("@/lib/api", () => ({
  createDictationBenchmarkBattle: vi.fn(),
  submitDictationBenchmarkVote: vi.fn(),
}));

const mockedCreateBattle = vi.mocked(createDictationBenchmarkBattle);
const mockedSubmitVote = vi.mocked(submitDictationBenchmarkVote);

type DataAvailableHandler = (event: { data: Blob }) => void;

let lastRecorder: FakeMediaRecorder | null = null;

class FakeMediaRecorder {
  static isTypeSupported = vi.fn(() => true);
  static throwOnConstruct = false;
  static nextStopBlob: Blob = new Blob(["audio"], { type: "audio/webm" });
  ondataavailable: DataAvailableHandler | null = null;
  onstop: (() => void) | null = null;
  state: RecordingState = "inactive";
  mimeType = "audio/webm";

  constructor(public stream: MediaStream, public options?: MediaRecorderOptions) {
    if (FakeMediaRecorder.throwOnConstruct) {
      throw new DOMException("blocked", "NotAllowedError");
    }
    if (options?.mimeType) {
      this.mimeType = options.mimeType;
    }
    FakeMediaRecorder.remember(this);
  }

  private static remember(recorder: FakeMediaRecorder) {
    lastRecorder = recorder;
  }

  start() {
    this.state = "recording";
  }

  stop() {
    this.state = "inactive";
    this.ondataavailable?.({ data: FakeMediaRecorder.nextStopBlob });
    this.onstop?.();
  }
}

class FakeAudioContext {
  static throwOnConstruct = false;
  destination = {};

  constructor() {
    if (FakeAudioContext.throwOnConstruct) {
      throw new Error("audio context unavailable");
    }
  }

  createAnalyser() {
    return {
      fftSize: 1024,
      getByteTimeDomainData: (data: Uint8Array) => {
        // Non-flat waveform so the bucket math produces varied levels.
        data.forEach((_, index) => {
          data[index] = index % 2 === 0 ? 200 : 60;
        });
      },
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

const trackStop = vi.fn();

function installMediaDevices(getUserMedia?: ReturnType<typeof vi.fn>) {
  vi.stubGlobal("MediaRecorder", FakeMediaRecorder);
  vi.stubGlobal("AudioContext", FakeAudioContext);
  // Drive the audio meter rAF loop exactly once then stop, so startAudioMeter runs.
  let rafCalls = 0;
  vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => {
    rafCalls += 1;
    if (rafCalls <= 1) {
      cb(0);
    }
    return rafCalls;
  });
  vi.stubGlobal("cancelAnimationFrame", vi.fn());
  Object.defineProperty(window.navigator, "mediaDevices", {
    configurable: true,
    value: {
      getUserMedia:
        getUserMedia ??
        vi.fn().mockResolvedValue({
          getTracks: () => [{ stop: trackStop }],
        }),
    },
  });
}

function setMediaDevices(value: unknown) {
  Object.defineProperty(window.navigator, "mediaDevices", {
    configurable: true,
    value,
  });
}

function okBattle(
  overrides: Partial<DictationBenchmarkBattleResponse["candidates"][number]> = {},
): DictationBenchmarkBattleResponse {
  return {
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
        ...overrides,
      },
    ],
  };
}

describe("DictationBenchmarkArena", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    mockedCreateBattle.mockReset();
    mockedSubmitVote.mockReset();
    trackStop.mockReset();
    lastRecorder = null;
    FakeMediaRecorder.throwOnConstruct = false;
    FakeMediaRecorder.isTypeSupported = vi.fn(() => true);
    FakeMediaRecorder.nextStopBlob = new Blob(["audio"], { type: "audio/webm" });
    FakeAudioContext.throwOnConstruct = false;
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders the locked active STT stack", () => {
    render(<DictationBenchmarkArena />);

    expect(screen.getByText("ElevenLabs")).toBeInTheDocument();
    expect(screen.getByText("Single active file STT model.")).toBeInTheDocument();
  });

  it("records once, uploads audio, and reveals ElevenLabs Scribe v2 after review", async () => {
    installMediaDevices();
    mockedCreateBattle.mockResolvedValue(okBattle());

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

  it("changes the request language when a language option is picked", async () => {
    installMediaDevices();
    mockedCreateBattle.mockResolvedValue({ ...okBattle(), language: "ru" });

    render(<DictationBenchmarkArena />);
    // Covers the language button onClick handler (setLanguage).
    await userEvent.click(screen.getByRole("button", { name: "Russian" }));

    await userEvent.click(screen.getByRole("button", { name: /Start recording/i }));
    await userEvent.click(await screen.findByRole("button", { name: /Stop and transcribe/i }));

    await screen.findByText("hello world");
    expect(mockedCreateBattle).toHaveBeenCalledWith({
      audio: expect.any(Blob),
      filename: "dictation-benchmark.webm",
      language: "ru",
    });
  });

  it("shows the sign-in notice with a link when the battle request returns 401", async () => {
    installMediaDevices();
    mockedCreateBattle.mockRejectedValue(new ApiError(401, "unauthorized"));

    render(<DictationBenchmarkArena signInHref="/account/login" />);
    await userEvent.click(screen.getByRole("button", { name: /Start recording/i }));
    await userEvent.click(await screen.findByRole("button", { name: /Stop and transcribe/i }));

    expect(
      await screen.findByText("Sign in to run a private transcription check."),
    ).toBeInTheDocument();
    const signInLink = screen.getByRole("link", { name: "Sign in" });
    expect(signInLink).toHaveAttribute("href", "/account/login");
  });

  it("surfaces a generic Error message from a failed battle request", async () => {
    installMediaDevices();
    mockedCreateBattle.mockRejectedValue(new Error("server exploded"));

    render(<DictationBenchmarkArena />);
    await userEvent.click(screen.getByRole("button", { name: /Start recording/i }));
    await userEvent.click(await screen.findByRole("button", { name: /Stop and transcribe/i }));

    expect(await screen.findByText("server exploded")).toBeInTheDocument();
    // Not the sign-in message, so no sign-in link should render.
    expect(screen.queryByRole("link", { name: "Sign in" })).not.toBeInTheDocument();
  });

  it("falls back to the requestFailed copy for non-Error rejections", async () => {
    installMediaDevices();
    mockedCreateBattle.mockRejectedValue("boom");

    render(<DictationBenchmarkArena />);
    await userEvent.click(screen.getByRole("button", { name: /Start recording/i }));
    await userEvent.click(await screen.findByRole("button", { name: /Stop and transcribe/i }));

    expect(await screen.findByText("Transcription request failed.")).toBeInTheDocument();
  });

  it("reports an empty recording when no audio is captured", async () => {
    installMediaDevices();
    FakeMediaRecorder.nextStopBlob = new Blob([], { type: "audio/webm" });

    render(<DictationBenchmarkArena />);
    await userEvent.click(screen.getByRole("button", { name: /Start recording/i }));
    await userEvent.click(await screen.findByRole("button", { name: /Stop and transcribe/i }));

    expect(
      await screen.findByText(
        "No audio was captured. Start a new round and speak for at least a second.",
      ),
    ).toBeInTheDocument();
    // Upload must be skipped for an empty blob.
    expect(mockedCreateBattle).not.toHaveBeenCalled();
  });

  it("uses an m4a filename when the recorder produces mp4 audio", async () => {
    installMediaDevices();
    FakeMediaRecorder.nextStopBlob = new Blob(["audio"], { type: "audio/mp4" });
    mockedCreateBattle.mockResolvedValue(okBattle());

    render(<DictationBenchmarkArena />);
    await userEvent.click(screen.getByRole("button", { name: /Start recording/i }));
    // Force the recorder mimeType to mp4 so onstop picks the m4a extension.
    if (lastRecorder) {
      lastRecorder.mimeType = "audio/mp4";
    }
    await userEvent.click(await screen.findByRole("button", { name: /Stop and transcribe/i }));

    await screen.findByText("hello world");
    expect(mockedCreateBattle).toHaveBeenCalledWith(
      expect.objectContaining({ filename: "dictation-benchmark.m4a" }),
    );
  });

  it("errors with micUnavailable when getUserMedia is missing", async () => {
    setMediaDevices(undefined);

    render(<DictationBenchmarkArena />);
    await userEvent.click(screen.getByRole("button", { name: /Start recording/i }));

    expect(
      await screen.findByText("Microphone recording is not available in this browser."),
    ).toBeInTheDocument();
    expect(mockedCreateBattle).not.toHaveBeenCalled();
  });

  it("shows the permission-denied copy when getUserMedia is blocked", async () => {
    installMediaDevices(
      vi.fn().mockRejectedValue(new DOMException("denied", "NotAllowedError")),
    );

    render(<DictationBenchmarkArena />);
    await userEvent.click(screen.getByRole("button", { name: /Start recording/i }));

    expect(
      await screen.findByText(
        "Microphone access was blocked. Allow microphone access in the browser, then start a new round.",
      ),
    ).toBeInTheDocument();
  });

  it("shows micUnavailable copy when getUserMedia fails for a non-permission reason", async () => {
    installMediaDevices(vi.fn().mockRejectedValue(new Error("hardware on fire")));

    render(<DictationBenchmarkArena />);
    await userEvent.click(screen.getByRole("button", { name: /Start recording/i }));

    expect(
      await screen.findByText("Microphone recording is not available in this browser."),
    ).toBeInTheDocument();
  });

  it("falls back to a plain MediaRecorder when no mime type is supported", async () => {
    installMediaDevices();
    FakeMediaRecorder.isTypeSupported = vi.fn(() => false);
    mockedCreateBattle.mockResolvedValue(okBattle());

    render(<DictationBenchmarkArena />);
    await userEvent.click(screen.getByRole("button", { name: /Start recording/i }));
    await userEvent.click(await screen.findByRole("button", { name: /Stop and transcribe/i }));

    await screen.findByText("hello world");
    // Constructed without options (no mimeType passed).
    expect(lastRecorder?.options).toBeUndefined();
  });

  it("ticks the elapsed timer while recording", async () => {
    vi.useFakeTimers();
    try {
      installMediaDevices();

      render(<DictationBenchmarkArena />);
      const startButton = screen.getByRole("button", { name: /Start recording/i });
      // React state updates from the async click must be wrapped in act via the timers.
      startButton.click();

      // Let microtasks (getUserMedia promise) resolve, then advance the interval.
      await vi.runOnlyPendingTimersAsync();
      vi.setSystemTime(Date.now() + 65_000);
      await vi.advanceTimersByTimeAsync(300);

      expect(screen.getByText("1:05")).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("re-records via the New round button after a completed battle", async () => {
    installMediaDevices();
    mockedCreateBattle.mockResolvedValue(okBattle());

    render(<DictationBenchmarkArena />);
    await userEvent.click(screen.getByRole("button", { name: /Start recording/i }));
    await userEvent.click(await screen.findByRole("button", { name: /Stop and transcribe/i }));
    await screen.findByText("hello world");

    // After a battle the primary button switches to "New round".
    const newRoundButton = await screen.findByRole("button", { name: "New round" });
    expect(newRoundButton).toBeInTheDocument();
    expect(lastRecorder?.state).toBe("inactive");

    // Starting a new round clears the prior result and runs the flow again.
    await userEvent.click(newRoundButton);
    await userEvent.click(await screen.findByRole("button", { name: /Stop and transcribe/i }));
    await screen.findByText("hello world");
    expect(mockedCreateBattle).toHaveBeenCalledTimes(2);
  });

  it("renders a candidate error and disables its vote button", async () => {
    installMediaDevices();
    mockedCreateBattle.mockResolvedValue(
      okBattle({
        status: "error",
        transcript: null,
        latency_ms: null,
        word_count: null,
        error: "transcription timed out",
      }),
    );

    render(<DictationBenchmarkArena />);
    await userEvent.click(screen.getByRole("button", { name: /Start recording/i }));
    await userEvent.click(await screen.findByRole("button", { name: /Stop and transcribe/i }));

    expect(await screen.findByText("transcription timed out")).toBeInTheDocument();
    // latency_ms / word_count null fall back to "-".
    expect(screen.getByText(/- ms · - words/)).toBeInTheDocument();
    const voteButton = screen.getByRole("button", { name: "Confirm" });
    expect(voteButton).toBeDisabled();

    // Clicking a disabled/non-ok candidate must not submit a vote (pickWinner early return).
    await userEvent.click(voteButton);
    expect(mockedSubmitVote).not.toHaveBeenCalled();
  });

  it("surfaces a vote failure message when the vote request rejects with a non-Error", async () => {
    installMediaDevices();
    mockedCreateBattle.mockResolvedValue(okBattle());
    mockedSubmitVote.mockRejectedValue("vote blew up");

    render(<DictationBenchmarkArena />);
    await userEvent.click(screen.getByRole("button", { name: /Start recording/i }));
    await userEvent.click(await screen.findByRole("button", { name: /Stop and transcribe/i }));
    await screen.findByText("hello world");

    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));

    expect(await screen.findByText("Confirmation was not saved.")).toBeInTheDocument();
  });

  it("surfaces a vote failure Error message verbatim", async () => {
    installMediaDevices();
    mockedCreateBattle.mockResolvedValue(okBattle());
    mockedSubmitVote.mockRejectedValue(new Error("vote rejected by server"));

    render(<DictationBenchmarkArena />);
    await userEvent.click(screen.getByRole("button", { name: /Start recording/i }));
    await userEvent.click(await screen.findByRole("button", { name: /Stop and transcribe/i }));
    await screen.findByText("hello world");

    await userEvent.click(screen.getByRole("button", { name: "Confirm" }));

    expect(await screen.findByText("vote rejected by server")).toBeInTheDocument();
  });

  it("falls back to idle wave levels when AudioContext is unavailable", async () => {
    installMediaDevices();
    // Remove both AudioContext and webkitAudioContext so startAudioMeter bails early.
    vi.stubGlobal("AudioContext", undefined);
    Object.defineProperty(window, "webkitAudioContext", {
      configurable: true,
      value: undefined,
    });
    mockedCreateBattle.mockResolvedValue(okBattle());

    render(<DictationBenchmarkArena />);
    await userEvent.click(screen.getByRole("button", { name: /Start recording/i }));
    // Recording still proceeds without the meter.
    await userEvent.click(await screen.findByRole("button", { name: /Stop and transcribe/i }));
    await screen.findByText("hello world");
  });

  it("recovers when AudioContext construction throws", async () => {
    installMediaDevices();
    FakeAudioContext.throwOnConstruct = true;
    mockedCreateBattle.mockResolvedValue(okBattle());

    render(<DictationBenchmarkArena />);
    await userEvent.click(screen.getByRole("button", { name: /Start recording/i }));
    await userEvent.click(await screen.findByRole("button", { name: /Stop and transcribe/i }));
    // The catch in startAudioMeter resets wave levels and recording continues.
    await screen.findByText("hello world");
  });

  it("uses webkitAudioContext when the standard AudioContext is absent", async () => {
    installMediaDevices();
    vi.stubGlobal("AudioContext", undefined);
    vi.stubGlobal("webkitAudioContext", FakeAudioContext);
    mockedCreateBattle.mockResolvedValue(okBattle());

    render(<DictationBenchmarkArena />);
    await userEvent.click(screen.getByRole("button", { name: /Start recording/i }));
    await userEvent.click(await screen.findByRole("button", { name: /Stop and transcribe/i }));
    await screen.findByText("hello world");
  });

  it("tears down the audio stream on unmount", async () => {
    installMediaDevices();

    const { unmount } = render(<DictationBenchmarkArena />);
    await userEvent.click(screen.getByRole("button", { name: /Start recording/i }));
    // Wait for the recording state so a live stream exists to be torn down.
    await screen.findByRole("button", { name: /Stop and transcribe/i });

    trackStop.mockClear();
    unmount();
    // Cleanup effect stops the live MediaStream tracks.
    await waitFor(() => expect(trackStop).toHaveBeenCalled());
  });
});
