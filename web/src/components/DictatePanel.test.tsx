import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { DictatePanel, applyDictionary } from "./DictatePanel";
import {
  cleanupDictation,
  createDictationEntry,
  listDictionaryWords,
} from "@/lib/api";
import { RealtimeTranscriber, type RealtimeState } from "@/lib/realtime";
import type { DictationDictionaryWord, TranscriptSegmentInput } from "@/lib/types";

vi.mock("@/lib/api", () => ({
  cleanupDictation: vi.fn(),
  createDictationEntry: vi.fn(),
  listDictionaryWords: vi.fn(),
}));

vi.mock("@/lib/realtime", () => {
  // Controllable test double for the realtime transcriber. The component
  // constructs it, wires up onState/onUpdate/onError, then drives start/stop.
  class FakeTranscriber {
    static last: FakeTranscriber | null = null;
    // When set, start() reports "recording" synchronously so the component's
    // post-start `getState() === "recording"` check opens the real interval.
    static startSetsRecording = false;
    opts: {
      onState?: (s: RealtimeState) => void;
      onUpdate?: (u: { committed: string; interim: string }) => void;
      onError?: (m: string) => void;
    };
    state: RealtimeState = "idle";
    stopResult: TranscriptSegmentInput[] = [];
    started = false;

    constructor(opts: FakeTranscriber["opts"]) {
      this.opts = opts;
      FakeTranscriber.last = this;
    }

    async start() {
      this.started = true;
      if (FakeTranscriber.startSetsRecording) {
        this.state = "recording";
        this.opts.onState?.("recording");
      }
    }

    getState() {
      return this.state;
    }

    async stop() {
      this.state = "idle";
      return this.stopResult;
    }
  }
  return { RealtimeTranscriber: FakeTranscriber };
});

const mockedCleanup = vi.mocked(cleanupDictation);
const mockedCreateEntry = vi.mocked(createDictationEntry);
const mockedListWords = vi.mocked(listDictionaryWords);

type FakeTranscriberInstance = {
  opts: {
    onState?: (s: RealtimeState) => void;
    onUpdate?: (u: { committed: string; interim: string }) => void;
    onError?: (m: string) => void;
  };
  state: RealtimeState;
  stopResult: TranscriptSegmentInput[];
  started: boolean;
};

// Reach the static `last` instance the component just constructed.
function lastTranscriber(): FakeTranscriberInstance {
  const t = (RealtimeTranscriber as unknown as { last: FakeTranscriberInstance | null }).last;
  if (!t) throw new Error("transcriber was never constructed");
  return t;
}

function segment(text: string): TranscriptSegmentInput {
  return { text, start_ms: 0, end_ms: 1000 };
}

const getUserMedia = vi.fn();
const writeText = vi.fn();

beforeEach(() => {
  const Fake = RealtimeTranscriber as unknown as {
    last: FakeTranscriberInstance | null;
    startSetsRecording: boolean;
  };
  Fake.last = null;
  Fake.startSetsRecording = false;
  getUserMedia.mockReset().mockResolvedValue({} as MediaStream);
  writeText.mockReset().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia },
  });
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText },
  });
  mockedListWords.mockResolvedValue([]);
  mockedCleanup.mockResolvedValue({ text: "" });
  mockedCreateEntry.mockResolvedValue(undefined as never);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.useRealTimers();
});

/** Click "Start dictating" and flush the async getUserMedia + start chain. */
async function startDictation() {
  fireEvent.click(screen.getByText("Start dictating"));
  await waitFor(() => expect(lastTranscriber().started).toBe(true));
}

describe("applyDictionary", () => {
  function word(text: string, replacement: string | null): DictationDictionaryWord {
    return { client_word_id: text, word: text, replacement, occurred_at: "2026-01-01T00:00:00Z" };
  }

  it("substitutes REPLACE entries (whole word, case-insensitive)", () => {
    const { text } = applyDictionary("I use wai computer daily", [
      word("wai computer", "WaiComputer"),
    ]);
    expect(text).toBe("I use WaiComputer daily");
  });

  it("does not substitute inside larger words", () => {
    const { text } = applyDictionary("rewaiwaiable", [word("wai", "X")]);
    expect(text).toBe("rewaiwaiable");
  });

  it("collects BIAS words and replacements as preserve-vocabulary", () => {
    const { vocabulary } = applyDictionary("hello", [
      word("Deepgram", null),
      word("k8s", "Kubernetes"),
    ]);
    expect(vocabulary).toContain("Deepgram");
    expect(vocabulary).toContain("Kubernetes");
  });

  it("leaves text unchanged with an empty dictionary", () => {
    const result = applyDictionary("plain text", []);
    expect(result.text).toBe("plain text");
    expect(result.vocabulary).toEqual([]);
  });
});

describe("DictatePanel rendering", () => {
  it("renders the start button and English copy by default", () => {
    render(<DictatePanel />);
    expect(screen.getByTestId("dictate-panel")).toBeTruthy();
    expect(screen.getByText("Start dictating")).toBeTruthy();
    expect(screen.getByText(/cleans it up/)).toBeTruthy();
    expect(screen.getByText(/get the Mac app/)).toBeTruthy();
  });

  it("renders Russian copy when locale is ru", () => {
    render(<DictatePanel locale="ru" />);
    expect(screen.getByText("Начать диктовку")).toBeTruthy();
    expect(screen.getByText(/причешет текст/)).toBeTruthy();
  });
});

describe("DictatePanel microphone permission", () => {
  it("shows a denial alert when getUserMedia rejects", async () => {
    getUserMedia.mockRejectedValue(new DOMException("denied", "NotAllowedError"));
    render(<DictatePanel />);

    fireEvent.click(screen.getByText("Start dictating"));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Microphone access is required");
    // No transcriber is constructed when permission fails.
    expect(
      (RealtimeTranscriber as unknown as { last: unknown }).last,
    ).toBeNull();
  });

  it("uses the localized denial message in Russian", async () => {
    getUserMedia.mockRejectedValue(new Error("nope"));
    render(<DictatePanel locale="ru" />);

    fireEvent.click(screen.getByText("Начать диктовку"));

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("нужен доступ к микрофону");
  });
});

describe("DictatePanel recording lifecycle", () => {
  it("renders the live transcript while recording", async () => {
    render(<DictatePanel />);
    await startDictation();

    act(() => {
      const t = lastTranscriber();
      t.state = "recording";
      t.opts.onState?.("recording");
    });

    expect(screen.getByText("Listening…")).toBeTruthy();
    // Recording dot is present only while actively recording.
    expect(document.querySelector(".live-recorder__dot")).toBeTruthy();

    act(() => {
      lastTranscriber().opts.onUpdate?.({ committed: "hello", interim: "world" });
    });
    expect(screen.getByText("hello")).toBeTruthy();
    expect(screen.getByText("world")).toBeTruthy();
  });

  it("starts a wall-clock timer when the transcriber is recording, then clears it on error", async () => {
    vi.useFakeTimers();
    // Make start() report "recording" so the component opens the real
    // 1s interval (getState() === "recording" right after start resolves).
    (RealtimeTranscriber as unknown as { startSetsRecording: boolean }).startSetsRecording = true;
    render(<DictatePanel />);

    fireEvent.click(screen.getByText("Start dictating"));
    await vi.waitFor(() => expect(lastTranscriber().started).toBe(true));

    // Timer starts at 0:00.
    expect(document.querySelector(".live-recorder__timer")?.textContent).toBe("0:00");

    // Advance 65s → the minute/second formatting branch renders 1:05.
    act(() => {
      vi.advanceTimersByTime(65_000);
    });
    expect(document.querySelector(".live-recorder__timer")?.textContent).toBe("1:05");

    // An error clears the interval; further ticks must not advance the timer.
    act(() => {
      lastTranscriber().opts.onError?.("boom");
    });
    act(() => {
      vi.advanceTimersByTime(5_000);
    });
    expect(screen.getByRole("alert").textContent).toContain("boom");
  });

  it("renders the connecting label while connecting (Stop disabled)", async () => {
    render(<DictatePanel />);
    await startDictation();

    act(() => {
      lastTranscriber().opts.onState?.("connecting");
    });

    expect(screen.getByText("Connecting…")).toBeTruthy();
    const stopBtn = screen.getByRole("button", { name: "Stop" });
    expect((stopBtn as HTMLButtonElement).disabled).toBe(true);
    // No recording dot while merely connecting.
    expect(document.querySelector(".live-recorder__dot")).toBeNull();
  });

  it("surfaces transcriber onError as an alert", async () => {
    render(<DictatePanel />);
    await startDictation();

    act(() => {
      lastTranscriber().opts.onState?.("recording");
    });
    act(() => {
      lastTranscriber().opts.onError?.("stream failed");
    });

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("stream failed");
  });
});

describe("DictatePanel stop + cleanup", () => {
  async function getToRecording() {
    render(<DictatePanel />);
    await startDictation();
    act(() => {
      const t = lastTranscriber();
      t.state = "recording";
      t.opts.onState?.("recording");
    });
  }

  it("shows the empty notice when no speech was captured", async () => {
    await getToRecording();
    lastTranscriber().stopResult = [];

    fireEvent.click(screen.getByRole("button", { name: "Stop" }));

    expect(await screen.findByRole("status")).toHaveTextContent("Didn't catch anything");
    // Back to the start button — no cleanup attempted.
    expect(screen.getByText("Start dictating")).toBeTruthy();
    expect(mockedCleanup).not.toHaveBeenCalled();
  });

  it("cleans the transcript, copies it, and logs a history entry", async () => {
    mockedListWords.mockResolvedValue([
      { client_word_id: "1", word: "wai computer", replacement: "WaiComputer", occurred_at: "x" },
    ]);
    mockedCleanup.mockResolvedValue({ text: "Polished WaiComputer text." });
    await getToRecording();
    lastTranscriber().stopResult = [segment("i love wai computer"), segment("a lot")];

    fireEvent.click(screen.getByRole("button", { name: "Stop" }));

    // Result phase renders the cleaned text + paste hint.
    expect(await screen.findByTestId("dictate-result")).toBeTruthy();
    expect(screen.getByText("Polished WaiComputer text.")).toBeTruthy();
    expect(screen.getByText(/paste it wherever you like/)).toBeTruthy();

    // Dictionary REPLACE was applied to the raw transcript before cleanup,
    // and the preserve-vocabulary was forwarded.
    await waitFor(() => expect(mockedCleanup).toHaveBeenCalledTimes(1));
    expect(mockedCleanup).toHaveBeenCalledWith(
      "i love WaiComputer a lot",
      ["WaiComputer"],
    );

    // Cleaned text was copied to the clipboard.
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("Polished WaiComputer text."));

    // History entry logged with raw + cleaned text and a word count.
    await waitFor(() => expect(mockedCreateEntry).toHaveBeenCalledTimes(1));
    const entry = mockedCreateEntry.mock.calls[0][0];
    expect(entry.raw_text).toBe("i love wai computer a lot");
    expect(entry.cleaned_text).toBe("Polished WaiComputer text.");
    // word_count is whitespace-delimited: "Polished WaiComputer text." -> 3.
    expect(entry.word_count).toBe(3);
    expect(typeof entry.client_entry_id).toBe("string");
    expect(typeof entry.occurred_at).toBe("string");
  });

  it("falls back to the raw transcript and warns when AI cleanup fails", async () => {
    mockedCleanup.mockRejectedValue(new Error("cleanup down"));
    await getToRecording();
    lastTranscriber().stopResult = [segment("keep this text")];

    fireEvent.click(screen.getByRole("button", { name: "Stop" }));

    // Recovery notice + the (dictionary-applied) raw transcript as the result.
    expect(await screen.findByRole("status")).toHaveTextContent("copied the raw transcript");
    expect(screen.getByTestId("dictate-result")).toHaveTextContent("keep this text");
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("keep this text"));
  });

  it("still cleans up when the dictionary lookup fails (best-effort)", async () => {
    mockedListWords.mockRejectedValue(new Error("no dictionary"));
    mockedCleanup.mockResolvedValue({ text: "cleaned anyway" });
    await getToRecording();
    lastTranscriber().stopResult = [segment("raw words")];

    fireEvent.click(screen.getByRole("button", { name: "Stop" }));

    expect(await screen.findByText("cleaned anyway")).toBeTruthy();
    // Cleanup ran with an empty preserve-vocabulary (dictionary unavailable).
    expect(mockedCleanup).toHaveBeenCalledWith("raw words", []);
  });

  it("keeps the dictionary-applied raw text when cleanup returns empty", async () => {
    mockedCleanup.mockResolvedValue({ text: "" });
    await getToRecording();
    lastTranscriber().stopResult = [segment("non empty raw")];

    fireEvent.click(screen.getByRole("button", { name: "Stop" }));

    // `|| replaced` keeps the raw text when the cleanup result is blank.
    expect(await screen.findByTestId("dictate-result")).toHaveTextContent("non empty raw");
  });

  it("does not block the paste flow when history logging fails", async () => {
    mockedCleanup.mockResolvedValue({ text: "final text" });
    mockedCreateEntry.mockRejectedValue(new Error("history down"));
    await getToRecording();
    lastTranscriber().stopResult = [segment("something")];

    fireEvent.click(screen.getByRole("button", { name: "Stop" }));

    // Result still renders + copies despite the history failure.
    expect(await screen.findByText("final text")).toBeTruthy();
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("final text"));
  });
});

describe("DictatePanel result actions", () => {
  async function getToResult() {
    mockedCleanup.mockResolvedValue({ text: "ready text" });
    render(<DictatePanel />);
    await startDictation();
    act(() => {
      const t = lastTranscriber();
      t.state = "recording";
      t.opts.onState?.("recording");
    });
    lastTranscriber().stopResult = [segment("ready text")];
    fireEvent.click(screen.getByRole("button", { name: "Stop" }));
    await screen.findByTestId("dictate-result");
  }

  it("copies again when the user clicks Copy again", async () => {
    await getToResult();
    writeText.mockClear();

    fireEvent.click(screen.getByText("Copy again"));

    await waitFor(() => expect(writeText).toHaveBeenCalledWith("ready text"));
  });

  it("returns to the record phase when the user clicks New dictation", async () => {
    await getToResult();

    fireEvent.click(screen.getByText("New dictation"));

    expect(screen.queryByTestId("dictate-result")).toBeNull();
    expect(screen.getByText("Start dictating")).toBeTruthy();
  });

  it("swallows a clipboard write failure on Copy again", async () => {
    await getToResult();
    writeText.mockClear();
    writeText.mockRejectedValue(new Error("clipboard blocked"));

    fireEvent.click(screen.getByText("Copy again"));

    // copyText catches the rejection (returns false) — the result stays put.
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("ready text"));
    expect(screen.getByTestId("dictate-result")).toBeTruthy();
  });
});
