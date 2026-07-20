import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import { DictatePanel, applyDictionary, dictionaryRealtimeHints } from "./DictatePanel";
import {
  createDictationEntry,
  createTranscriptionSession,
  listDictionaryWords,
} from "@/lib/api";
import { RealtimeTranscriber, type RealtimeState } from "@/lib/realtime";
import type {
  DictationDictionaryWord,
  RealtimeSessionResponse,
  TranscriptSegmentInput,
} from "@/lib/types";

vi.mock("@/lib/api", () => ({
  createDictationEntry: vi.fn(),
  createTranscriptionSession: vi.fn(),
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
      keyterms?: string[];
      replacements?: Array<{ find: string; replace: string }>;
    };
    startOptions: unknown = null;
    state: RealtimeState = "idle";
    stopResult: TranscriptSegmentInput[] = [];
    stopError: Error | null = null;
    started = false;
    stopCalls = 0;

    constructor(opts: FakeTranscriber["opts"]) {
      this.opts = opts;
      FakeTranscriber.last = this;
    }

    async start(_stream: MediaStream, options?: unknown) {
      this.startOptions = options ?? null;
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
      this.stopCalls += 1;
      if (this.stopError) throw this.stopError;
      this.state = "idle";
      return this.stopResult;
    }
  }
  function realtimeSessionRequestKey(request: {
    language?: string;
    purpose: "recording" | "dictation";
    keyterms?: string[];
    replacements?: Array<{ find: string; replace: string }>;
  }) {
    return JSON.stringify({
      language: request.language ?? "multi",
      purpose: request.purpose,
      keyterms: (request.keyterms ?? []).map((value) => value.trim()).filter(Boolean),
      replacements: (request.replacements ?? [])
        .map((value) => ({ find: value.find.trim(), replace: value.replace.trim() }))
        .filter((value) => value.find && value.replace),
    });
  }

  return { RealtimeTranscriber: FakeTranscriber, realtimeSessionRequestKey };
});

const mockedCreateEntry = vi.mocked(createDictationEntry);
const mockedCreateSession = vi.mocked(createTranscriptionSession);
const mockedListWords = vi.mocked(listDictionaryWords);

type FakeTranscriberInstance = {
    opts: {
      onState?: (s: RealtimeState) => void;
      onUpdate?: (u: { committed: string; interim: string }) => void;
      onError?: (m: string) => void;
      keyterms?: string[];
      replacements?: Array<{ find: string; replace: string }>;
  };
  startOptions: unknown;
  state: RealtimeState;
  stopResult: TranscriptSegmentInput[];
  stopError: Error | null;
  started: boolean;
  stopCalls: number;
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

function sessionResponse(over: Partial<RealtimeSessionResponse> = {}): RealtimeSessionResponse {
  return {
    provider: "openai",
    token: "prefetched token",
    expires_in_seconds: 60,
    sample_rate: 24000,
    audio_format: "linear16",
    language: "multi",
    channels: 1,
    model: "gpt-realtime-whisper",
    keep_alive_interval_seconds: null,
    commit_strategy: null,
    no_verbatim: false,
    websocket_url: "wss://wai.computer/api/transcription/stream",
    auth_scheme: "query",
    ...over,
  };
}

const getUserMedia = vi.fn();
const writeText = vi.fn();

function deferred<T>(): {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (error: unknown) => void;
} {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

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
  mockedCreateSession.mockResolvedValue(sessionResponse());
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

  it("substitutes Cyrillic entries on word boundaries (\\b is ASCII-only)", () => {
    const { text } = applyDictionary("Позвони насте завтра", [word("насте", "Насте")]);
    expect(text).toBe("Позвони Насте завтра");
  });

  it("does not substitute inside larger Cyrillic words", () => {
    const { text } = applyDictionary("перенастенный", [word("насте", "X")]);
    expect(text).toBe("перенастенный");
  });

  it("treats $ in replacements literally instead of as a regex pattern", () => {
    const { text } = applyDictionary("price is high", [word("high", "$100 & up")]);
    expect(text).toBe("price is $100 & up");
  });

  it("substitutes repeated adjacent occurrences", () => {
    const { text } = applyDictionary("wai wai wai", [word("wai", "X")]);
    expect(text).toBe("X X X");
  });

  it("collects BIAS words and replacements as preserve-vocabulary", () => {
    const { vocabulary } = applyDictionary("hello", [
      word("Deepgram", null),
      word("k8s", "Kubernetes"),
    ]);
    expect(vocabulary).toContain("Deepgram");
    expect(vocabulary).toContain("Kubernetes");
  });

  it("builds realtime keyterms and replacements from dictionary entries", () => {
    const hints = dictionaryRealtimeHints([
      word("Deepgram", null),
      word("wai computer", "WaiComputer"),
    ]);

    expect(hints).toEqual({
      keyterms: ["Deepgram", "WaiComputer"],
      replacements: [{ find: "wai computer", replace: "WaiComputer" }],
    });
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
    expect(screen.getByText(/paste the transcript anywhere/)).toBeTruthy();
    expect(screen.getByText(/get the Mac app/)).toBeTruthy();
  });

  it("renders Russian copy when locale is ru", () => {
    render(<DictatePanel locale="ru" />);
    expect(screen.getByText("Начать диктовку")).toBeTruthy();
    expect(screen.getByText(/вставьте расшифровку/)).toBeTruthy();
  });

  it("prefetches dictionary hints and realtime session before the user starts dictating", async () => {
    mockedListWords.mockResolvedValue([
      { client_word_id: "1", word: "wai computer", replacement: "WaiComputer", occurred_at: "x" },
    ]);
    render(<DictatePanel />);

    await waitFor(() => expect(mockedListWords).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(mockedCreateSession).toHaveBeenCalledTimes(1));
    expect(mockedCreateSession).toHaveBeenCalledWith({
      purpose: "dictation",
      keyterms: ["WaiComputer"],
      replacements: [{ find: "wai computer", replace: "WaiComputer" }],
    });
    expect((RealtimeTranscriber as unknown as { last: unknown }).last).toBeNull();
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
    // Committed text is a polite live region; interim is hidden from SRs.
    expect(screen.getByText("hello")).toHaveAttribute("aria-live", "polite");
    expect(screen.getByText("world")).toHaveAttribute("aria-hidden", "true");
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

  it("renders the connecting label while connecting with Stop enabled", async () => {
    render(<DictatePanel />);
    await startDictation();

    act(() => {
      lastTranscriber().opts.onState?.("connecting");
    });

    expect(screen.getByText("Connecting…")).toBeTruthy();
    const stopBtn = screen.getByRole("button", { name: "Stop" });
    expect((stopBtn as HTMLButtonElement).disabled).toBe(false);
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
    // Back to the start button — no post-processing attempted.
    expect(screen.getByText("Start dictating")).toBeTruthy();
  });

  it("passes dictionary hints into realtime startup", async () => {
    mockedListWords.mockResolvedValue([
      { client_word_id: "1", word: "wai computer", replacement: "WaiComputer", occurred_at: "x" },
      { client_word_id: "2", word: "Deepgram", replacement: null, occurred_at: "x" },
    ]);
    render(<DictatePanel />);

    await startDictation();

    expect(lastTranscriber().opts.keyterms).toEqual(["WaiComputer", "Deepgram"]);
    expect(lastTranscriber().opts.replacements).toEqual([
      { find: "wai computer", replace: "WaiComputer" },
    ]);
  });

  it("passes the prefetched realtime session into startup without reminting", async () => {
    mockedListWords.mockResolvedValue([
      { client_word_id: "1", word: "Deepgram", replacement: null, occurred_at: "x" },
    ]);
    mockedCreateSession.mockResolvedValueOnce(sessionResponse({ token: "warm dictation" }));
    render(<DictatePanel />);
    await waitFor(() => expect(mockedCreateSession).toHaveBeenCalledTimes(1));

    await startDictation();

    expect(mockedCreateSession).toHaveBeenCalledTimes(1);
    expect(lastTranscriber().startOptions).toEqual({
      prefetchedSession: {
        request: {
          purpose: "dictation",
          keyterms: ["Deepgram"],
          replacements: [],
        },
        session: sessionResponse({ token: "warm dictation" }),
      },
    });
  });

  it("applies dictionary replacements, copies the transcript, and logs history", async () => {
    mockedListWords.mockResolvedValue([
      { client_word_id: "1", word: "wai computer", replacement: "WaiComputer", occurred_at: "x" },
    ]);
    await getToRecording();
    lastTranscriber().stopResult = [segment("i love wai computer"), segment("a lot")];

    fireEvent.click(screen.getByRole("button", { name: "Stop" }));

    // Result phase renders the cleaned text + paste hint.
    expect(await screen.findByTestId("dictate-result")).toBeTruthy();
    expect(screen.getByText("i love WaiComputer a lot")).toBeTruthy();
    expect(screen.getByText(/paste it wherever you like/)).toBeTruthy();

    // Dictionary REPLACE was applied locally, then copied to the clipboard.
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("i love WaiComputer a lot"));

    // History entry logged with raw + cleaned text and a word count.
    await waitFor(() => expect(mockedCreateEntry).toHaveBeenCalledTimes(1));
    const entry = mockedCreateEntry.mock.calls[0][0];
    expect(entry.raw_text).toBe("i love wai computer a lot");
    expect(entry.cleaned_text).toBe("i love WaiComputer a lot");
    // word_count is whitespace-delimited.
    expect(entry.word_count).toBe(5);
    expect(typeof entry.client_entry_id).toBe("string");
    expect(typeof entry.occurred_at).toBe("string");
  });

  it("copies raw transcript without a notice when no dictionary entries exist", async () => {
    await getToRecording();
    lastTranscriber().stopResult = [segment("keep this text")];

    fireEvent.click(screen.getByRole("button", { name: "Stop" }));

    expect(await screen.findByTestId("dictate-result")).toHaveTextContent("keep this text");
    expect(screen.queryByRole("status")).toBeNull();
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("keep this text"));
  });

  it("surfaces dictionary lookup failure and still copies the transcript", async () => {
    mockedListWords.mockRejectedValue(new Error("no dictionary"));
    await getToRecording();
    lastTranscriber().stopResult = [segment("raw words")];

    fireEvent.click(screen.getByRole("button", { name: "Stop" }));

    expect(await screen.findByRole("status")).toHaveTextContent("Dictionary could not load");
    expect(screen.getByTestId("dictate-result")).toHaveTextContent("raw words");
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("raw words"));
  });

  it("does not block the paste flow when history logging fails, but surfaces the sync error", async () => {
    mockedCreateEntry.mockRejectedValue(new Error("history down"));
    await getToRecording();
    lastTranscriber().stopResult = [segment("something")];

    fireEvent.click(screen.getByRole("button", { name: "Stop" }));

    // Result still renders + copies despite the history failure.
    expect(await screen.findByText("something")).toBeTruthy();
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("something"));
    expect(await screen.findByRole("status")).toHaveTextContent(
      "dictation history could not be saved",
    );
  });

  it("surfaces stop finalization failures without copying or logging partial text", async () => {
    await getToRecording();
    lastTranscriber().stopError = new Error("finalize timeout");

    fireEvent.click(screen.getByRole("button", { name: "Stop" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("finalize timeout");
    expect(writeText).not.toHaveBeenCalled();
    expect(mockedCreateEntry).not.toHaveBeenCalled();
    expect(screen.getByText("Start dictating")).toBeTruthy();
  });

  it("stops an active transcriber on unmount without copying or logging history", async () => {
    render(<DictatePanel />);
    await startDictation();
    const transcriber = lastTranscriber();
    act(() => {
      transcriber.state = "recording";
      transcriber.opts.onState?.("recording");
    });
    transcriber.stopResult = [segment("unmounted text")];

    cleanup();

    await waitFor(() => expect(transcriber.stopCalls).toBe(1));
    expect(writeText).not.toHaveBeenCalled();
    expect(mockedCreateEntry).not.toHaveBeenCalled();
  });

  it("stops a late microphone stream when permission resolves after unmount", async () => {
    const permission = deferred<MediaStream>();
    const stopTrack = vi.fn();
    const lateStream = {
      getTracks: () => [{ stop: stopTrack }],
    } as unknown as MediaStream;
    getUserMedia.mockReturnValueOnce(permission.promise);
    render(<DictatePanel />);

    fireEvent.click(screen.getByText("Start dictating"));
    cleanup();
    await act(async () => {
      permission.resolve(lateStream);
      await permission.promise;
      await Promise.resolve();
    });

    expect(stopTrack).toHaveBeenCalledTimes(1);
    expect(
      (RealtimeTranscriber as unknown as { last: unknown }).last,
    ).toBeNull();
  });
});

describe("DictatePanel result actions", () => {
  async function getToResult() {
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
