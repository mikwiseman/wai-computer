import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LiveRecorder } from "./LiveRecorder";
import type {
  RealtimeState,
  RealtimeTranscriberOptions,
} from "@/lib/realtime";
import type { TranscriptSegmentInput } from "@/lib/types";

const mockCreateRecording = vi.fn();
const mockSaveTranscript = vi.fn();

vi.mock("@/lib/api", () => ({
  createRecording: (...args: unknown[]) => mockCreateRecording(...args),
  saveTranscript: (...args: unknown[]) => mockSaveTranscript(...args),
}));

// A controllable stand-in for the real RealtimeTranscriber. It records the
// callbacks the component wires in, lets each test script the state it
// reaches on start() and the segments it returns on stop(), and exposes the
// captured callbacks so tests can push live transcript updates.
//
// Defined inside vi.hoisted so the class exists before vi.mock's (hoisted)
// factory runs — a plain top-level class would hit a TDZ "before
// initialization" error when the factory references it during import.
const { FakeTranscriber } = vi.hoisted(() => {
  class FakeTranscriber {
    static instances: FakeTranscriber[] = [];
    // Per-test knobs.
    static startState: RealtimeState = "recording";
    static stopSegments: TranscriptSegmentInput[] = [];
    static stopError: Error | null = null;

    readonly opts: RealtimeTranscriberOptions;
    private currentState: RealtimeState = "idle";
    startedWith: Array<MediaStream | MediaStream[]> = [];
    stopCalls = 0;

    constructor(opts: RealtimeTranscriberOptions) {
      this.opts = opts;
      FakeTranscriber.instances.push(this);
    }

    getState(): RealtimeState {
      return this.currentState;
    }

    async start(streams: MediaStream[]): Promise<void> {
      this.startedWith.push(streams);
      this.currentState = FakeTranscriber.startState;
      // Mirror the real client: drive the component's state machine via onState.
      this.opts.onState?.("connecting");
      this.opts.onState?.(FakeTranscriber.startState);
    }

    async stop(): Promise<TranscriptSegmentInput[]> {
      this.stopCalls += 1;
      if (FakeTranscriber.stopError) throw FakeTranscriber.stopError;
      this.currentState = "idle";
      return FakeTranscriber.stopSegments;
    }

    // Test helpers — not part of the real interface.
    emitUpdate(committed: string, interim: string): void {
      this.opts.onUpdate?.({ committed, interim });
    }

    emitError(message: string): void {
      this.opts.onError?.(message);
    }
  }
  return { FakeTranscriber };
});

vi.mock("@/lib/realtime", () => ({
  // Hand back the real class so `new RealtimeTranscriber(...)` works; a
  // vi.fn().mockImplementation wrapper is not constructable with `new`.
  RealtimeTranscriber: FakeTranscriber,
}));

function segment(text: string): TranscriptSegmentInput {
  return { text, speaker: "Speaker 1", start_ms: 0, end_ms: 1000 };
}

function setMediaDevices(value: Partial<MediaDevices>): void {
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value,
  });
}

const micStream = { id: "mic" } as unknown as MediaStream;

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

// jsdom has no MediaStream. The component does `new MediaStream(audioTracks)`
// to keep only the system-audio track; without a stub that throws and the
// system-audio branch silently falls back to mic-only.
class FakeMediaStream {
  readonly tracks: MediaStreamTrack[];
  constructor(tracks: MediaStreamTrack[] = []) {
    this.tracks = tracks;
  }
  getTracks(): MediaStreamTrack[] {
    return this.tracks;
  }
}

describe("LiveRecorder", () => {
  beforeEach(() => {
    mockCreateRecording.mockReset();
    mockSaveTranscript.mockReset();
    FakeTranscriber.instances = [];
    FakeTranscriber.startState = "recording";
    FakeTranscriber.stopSegments = [];
    FakeTranscriber.stopError = null;
    localStorage.clear();
    vi.stubGlobal("MediaStream", FakeMediaStream);
    // Default: mic-only environment with no system-audio support.
    setMediaDevices({
      getUserMedia: vi.fn().mockResolvedValue(micStream),
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("hides the system-audio toggle when getDisplayMedia is unavailable", () => {
    render(<LiveRecorder onRecordingComplete={vi.fn()} onError={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Record in browser" })).toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });

  it("starts a mic-only recording and renders live transcript updates", async () => {
    const user = userEvent.setup();
    render(<LiveRecorder onRecordingComplete={vi.fn()} onError={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: "Record in browser" }));

    // Moves into the active view with the Listening label, announced politely.
    await waitFor(() => expect(screen.getByText("Listening…")).toBeInTheDocument());
    expect(screen.getByText("Listening…")).toHaveAttribute("aria-live", "polite");
    expect(screen.getByTestId("live-recorder").getAttribute("data-state")).toBe("recording");
    // Timer is shown starting at 0:00.
    expect(screen.getByText("0:00")).toBeInTheDocument();

    // Only the mic stream was forwarded (no system audio captured).
    const transcriber = FakeTranscriber.instances[0];
    expect(transcriber.startedWith[0]).toEqual([micStream]);

    // Live interim + committed text renders in the transcript line.
    act(() => transcriber.emitUpdate("hello world", "and more"));
    await waitFor(() => {
      expect(screen.getByText("hello world")).toHaveAttribute("aria-live", "polite");
      expect(screen.getByText("and more")).toHaveAttribute("aria-hidden", "true");
    });
  });

  it("advances the recording timer once per second while recording", async () => {
    vi.useFakeTimers();
    try {
      render(<LiveRecorder onRecordingComplete={vi.fn()} onError={vi.fn()} />);

      // fireEvent (not userEvent) under fake timers: userEvent schedules its own
      // timers and deadlocks against vitest's fake clock.
      fireEvent.click(screen.getByRole("button", { name: "Record in browser" }));
      // Flush the async start() (getUserMedia + transcriber.start microtasks).
      await act(async () => {
        await Promise.resolve();
      });
      expect(screen.getByText("0:00")).toBeInTheDocument();

      // 65s of wall-clock ticks render as 1:05 (mm:ss, zero-padded seconds).
      act(() => {
        vi.advanceTimersByTime(65_000);
      });
      expect(screen.getByText("1:05")).toBeInTheDocument();
    } finally {
      vi.runOnlyPendingTimers();
      vi.useRealTimers();
    }
  });

  it("surfaces microphone permission failures and stays idle", async () => {
    setMediaDevices({
      getUserMedia: vi.fn().mockRejectedValue(new Error("denied")),
    });
    const onError = vi.fn();
    const user = userEvent.setup();
    render(<LiveRecorder onRecordingComplete={vi.fn()} onError={onError} locale="ru" />);

    await user.click(screen.getByRole("button", { name: "Запись в браузере" }));

    await waitFor(() =>
      expect(onError).toHaveBeenCalledWith("Для записи нужен доступ к микрофону."),
    );
    // No transcriber was constructed; UI never left the idle view.
    expect(FakeTranscriber.instances).toHaveLength(0);
    expect(screen.getByRole("button", { name: "Запись в браузере" })).toBeInTheDocument();
  });

  it("does not start the timer when the transcriber fails to reach recording", async () => {
    vi.useFakeTimers();
    try {
      FakeTranscriber.startState = "error";
      render(<LiveRecorder onRecordingComplete={vi.fn()} onError={vi.fn()} />);

      fireEvent.click(screen.getByRole("button", { name: "Record in browser" }));
      await act(async () => {
        await Promise.resolve();
      });

      // error is not an "active" state, so we stay in the idle view and the
      // setInterval that drives the timer is never created.
      expect(screen.getByRole("button", { name: "Record in browser" })).toBeInTheDocument();
      act(() => {
        vi.advanceTimersByTime(5_000);
      });
      expect(screen.queryByText(/0:0\d/)).not.toBeInTheDocument();
    } finally {
      vi.runOnlyPendingTimers();
      vi.useRealTimers();
    }
  });

  it("lets the user stop while the realtime connection is still connecting", async () => {
    FakeTranscriber.startState = "connecting";
    const user = userEvent.setup();
    render(<LiveRecorder onRecordingComplete={vi.fn()} onError={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: "Record in browser" }));
    await waitFor(() => expect(screen.getByText("Connecting…")).toBeInTheDocument());

    const stopButton = screen.getByRole("button", { name: "Stop & save" });
    expect(stopButton).not.toBeDisabled();
    await user.click(stopButton);

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Record in browser" })).toBeInTheDocument(),
    );
    expect(FakeTranscriber.instances[0].stopCalls).toBe(1);
    expect(mockCreateRecording).not.toHaveBeenCalled();
    expect(mockSaveTranscript).not.toHaveBeenCalled();
  });

  describe("with system-audio support", () => {
    it("captures shared system audio and forwards both streams", async () => {
      const sysTrack = { stop: vi.fn() } as unknown as MediaStreamTrack;
      const videoTrack = { stop: vi.fn() } as unknown as MediaStreamTrack;
      const displayStream = {
        getVideoTracks: () => [videoTrack],
        getAudioTracks: () => [sysTrack],
      } as unknown as MediaStream;
      setMediaDevices({
        getUserMedia: vi.fn().mockResolvedValue(micStream),
        getDisplayMedia: vi.fn().mockResolvedValue(displayStream),
      });
      const user = userEvent.setup();
      render(<LiveRecorder onRecordingComplete={vi.fn()} onError={vi.fn()} />);

      const checkbox = screen.getByRole("checkbox");
      await user.click(checkbox);
      // Wait for the controlled toggle to commit so the start() closure reads
      // includeSystem === true before we click Record.
      await waitFor(() => expect(checkbox).toBeChecked());
      await user.click(screen.getByRole("button", { name: "Record in browser" }));

      await waitFor(() => expect(FakeTranscriber.instances).toHaveLength(1));
      // The video track is stopped, and a second (audio-only) stream is added.
      expect((videoTrack as unknown as { stop: ReturnType<typeof vi.fn> }).stop).toHaveBeenCalled();
      const forwarded = FakeTranscriber.instances[0].startedWith[0] as MediaStream[];
      expect(forwarded).toHaveLength(2);
      expect(forwarded[0]).toBe(micStream);
    });

    it("warns when system audio is requested but no audio track is shared", async () => {
      const displayStream = {
        getVideoTracks: () => [{ stop: vi.fn() } as unknown as MediaStreamTrack],
        getAudioTracks: () => [],
      } as unknown as MediaStream;
      const getDisplayMedia = vi.fn().mockResolvedValue(displayStream);
      setMediaDevices({
        getUserMedia: vi.fn().mockResolvedValue(micStream),
        getDisplayMedia,
      });
      const user = userEvent.setup();
      render(<LiveRecorder onRecordingComplete={vi.fn()} onError={vi.fn()} />);

      const checkbox = screen.getByRole("checkbox");
      await user.click(checkbox);
      await waitFor(() => expect(checkbox).toBeChecked());
      await user.click(screen.getByRole("button", { name: "Record in browser" }));

      // The display prompt was honoured, but with no audio track shared the
      // recording proceeds mic-only (the empty-audio branch in start()).
      await waitFor(() => expect(FakeTranscriber.instances).toHaveLength(1));
      expect(getDisplayMedia).toHaveBeenCalledTimes(1);
      const forwarded = FakeTranscriber.instances[0].startedWith[0] as MediaStream[];
      expect(forwarded).toEqual([micStream]);
    });

    it("renders a localized note in the idle view when the prompt is dismissed", async () => {
      // The note only shows in the idle view, so drive the transcriber to a
      // non-recording state: that keeps us idle and lets us assert both the
      // getDisplayMedia catch branch and the note-rendering JSX.
      FakeTranscriber.startState = "error";
      const getDisplayMedia = vi.fn().mockRejectedValue(new Error("cancelled"));
      setMediaDevices({
        getUserMedia: vi.fn().mockResolvedValue(micStream),
        getDisplayMedia,
      });
      const user = userEvent.setup();
      render(<LiveRecorder onRecordingComplete={vi.fn()} onError={vi.fn()} locale="ru" />);

      const checkbox = screen.getByRole("checkbox");
      await user.click(checkbox);
      await waitFor(() => expect(checkbox).toBeChecked());
      await user.click(screen.getByRole("button", { name: "Запись в браузере" }));

      // The dismissed display capture surfaces the localized fallback note...
      await waitFor(() =>
        expect(
          screen.getByText("Системное аудио недоступно — запись только с микрофона."),
        ).toBeInTheDocument(),
      );
      // ...and must not abort the mic recording (mic stream still forwarded).
      expect(getDisplayMedia).toHaveBeenCalledTimes(1);
      expect(FakeTranscriber.instances[0].startedWith[0]).toEqual([micStream]);
    });
  });

  describe("stop()", () => {
    async function startRecording(
      onComplete = vi.fn(),
      onError = vi.fn(),
    ): Promise<{ user: ReturnType<typeof userEvent.setup>; onComplete: typeof onComplete; onError: typeof onError }> {
      const user = userEvent.setup();
      render(<LiveRecorder onRecordingComplete={onComplete} onError={onError} />);
      await user.click(screen.getByRole("button", { name: "Record in browser" }));
      await waitFor(() => expect(screen.getByText("Listening…")).toBeInTheDocument());
      return { user, onComplete, onError };
    }

    it("creates a recording and saves the transcript on a normal stop", async () => {
      FakeTranscriber.stopSegments = [segment("first"), segment("second")];
      mockCreateRecording.mockResolvedValueOnce({ id: "rec-9" });
      const savedDetail = { id: "rec-9", title: "Recording" };
      mockSaveTranscript.mockResolvedValueOnce(savedDetail);

      const { user, onComplete } = await startRecording();
      await user.click(screen.getByRole("button", { name: "Stop & save" }));

      await waitFor(() => {
        expect(mockCreateRecording).toHaveBeenCalledWith({
          title: expect.stringContaining("Recording "),
          type: "note",
        });
        expect(mockSaveTranscript).toHaveBeenCalledWith("rec-9", [
          segment("first"),
          segment("second"),
        ]);
        expect(onComplete).toHaveBeenCalledWith(savedDetail);
      });
      // Returns to the idle view.
      expect(screen.getByRole("button", { name: "Record in browser" })).toBeInTheDocument();
    });

    it("skips saving when nothing was transcribed and explains why", async () => {
      FakeTranscriber.stopSegments = [];
      const { user } = await startRecording();

      await user.click(screen.getByRole("button", { name: "Stop & save" }));

      await waitFor(() =>
        expect(screen.getByRole("button", { name: "Record in browser" })).toBeInTheDocument(),
      );
      // A "no speech captured" notice now shows instead of a silent reset.
      expect(screen.getByRole("status")).toHaveTextContent("No speech was captured");
      expect(mockCreateRecording).not.toHaveBeenCalled();
      expect(mockSaveTranscript).not.toHaveBeenCalled();
    });

    it("keeps the transcript and offers a retry when saving fails", async () => {
      FakeTranscriber.stopSegments = [segment("oops")];
      mockCreateRecording.mockResolvedValueOnce({ id: "rec-err" });
      mockSaveTranscript.mockRejectedValueOnce(new Error("network down"));

      const { user, onError } = await startRecording();
      await user.click(screen.getByRole("button", { name: "Stop & save" }));

      await waitFor(() => expect(onError).toHaveBeenCalledWith("network down"));
      // The captured speech stays on screen with a retry — not silently lost.
      const panel = screen.getByTestId("live-recorder-unsaved");
      expect(panel).toHaveTextContent("oops");
      expect(localStorage.getItem("wai:live-recorder:pending")).toContain("oops");

      // Retry reuses the already-created recording instead of duplicating it.
      const savedDetail = { id: "rec-err", title: "Recording" };
      mockSaveTranscript.mockResolvedValueOnce(savedDetail);
      await user.click(screen.getByTestId("live-recorder-retry-save"));

      await waitFor(() => {
        expect(mockSaveTranscript).toHaveBeenLastCalledWith("rec-err", [segment("oops")]);
      });
      expect(mockCreateRecording).toHaveBeenCalledTimes(1);
      expect(localStorage.getItem("wai:live-recorder:pending")).toBeNull();
      await waitFor(() =>
        expect(screen.getByRole("button", { name: "Record in browser" })).toBeInTheDocument(),
      );
    });

    it("restores an unsaved recording from a previous session and can discard it", async () => {
      localStorage.setItem(
        "wai:live-recorder:pending",
        JSON.stringify({
          title: "Recording from yesterday",
          folderId: null,
          segments: [segment("restored words")],
        }),
      );

      const user = userEvent.setup();
      render(<LiveRecorder onRecordingComplete={vi.fn()} onError={vi.fn()} />);

      const panel = screen.getByTestId("live-recorder-unsaved");
      expect(panel).toHaveTextContent("restored words");

      await user.click(screen.getByTestId("live-recorder-discard-unsaved"));
      expect(localStorage.getItem("wai:live-recorder:pending")).toBeNull();
      expect(screen.getByRole("button", { name: "Record in browser" })).toBeInTheDocument();
    });

    it("reports stop finalization failures without saving a partial recording", async () => {
      FakeTranscriber.stopError = new Error("finalize timeout");

      const { user, onError } = await startRecording();
      await user.click(screen.getByRole("button", { name: "Stop & save" }));

      await waitFor(() => expect(onError).toHaveBeenCalledWith("finalize timeout"));
      expect(mockCreateRecording).not.toHaveBeenCalled();
      expect(mockSaveTranscript).not.toHaveBeenCalled();
      expect(screen.getByRole("button", { name: "Record in browser" })).toBeInTheDocument();
    });
  });

  it("shows an inline error and keeps the transcript when the realtime connection drops", async () => {
    // Previously the realtime error was forwarded to the parent onError, which
    // swapped the recorder out and discarded the on-screen transcript. Now the
    // drop is surfaced inline (localized) with the transcript preserved.
    const onError = vi.fn();
    const user = userEvent.setup();
    render(<LiveRecorder onRecordingComplete={vi.fn()} onError={onError} />);
    await user.click(screen.getByRole("button", { name: "Record in browser" }));
    await waitFor(() => expect(screen.getByText("Listening…")).toBeInTheDocument());

    const transcriber = FakeTranscriber.instances[0];
    act(() => transcriber.emitUpdate("meeting so far", ""));
    await waitFor(() => expect(screen.getByText("meeting so far")).toBeInTheDocument());

    act(() => transcriber.emitError("Realtime connection lost"));

    // Inline localized alert, not a bubbled parent error.
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Recording stopped unexpectedly. Start again to keep going.",
    );
    expect(onError).not.toHaveBeenCalled();
    // The captured transcript stays visible, and a fresh start is offered.
    expect(screen.getByText("meeting so far")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Record in browser" })).toBeInTheDocument();
  });

  it("stops an active transcriber on unmount without saving an empty recording", async () => {
    const user = userEvent.setup();
    const { unmount } = render(<LiveRecorder onRecordingComplete={vi.fn()} onError={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Record in browser" }));
    await waitFor(() => expect(screen.getByText("Listening…")).toBeInTheDocument());
    const transcriber = FakeTranscriber.instances[0];

    unmount();

    await waitFor(() => expect(transcriber.stopCalls).toBe(1));
    expect(mockCreateRecording).not.toHaveBeenCalled();
    expect(mockSaveTranscript).not.toHaveBeenCalled();
  });

  it("stops a late microphone stream when permission resolves after unmount", async () => {
    const permission = deferred<MediaStream>();
    const stopTrack = vi.fn();
    const lateStream = {
      getTracks: () => [{ stop: stopTrack }],
    } as unknown as MediaStream;
    setMediaDevices({
      getUserMedia: vi.fn().mockReturnValue(permission.promise),
    });
    const { unmount } = render(<LiveRecorder onRecordingComplete={vi.fn()} onError={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Record in browser" }));
    unmount();
    await act(async () => {
      permission.resolve(lateStream);
      await permission.promise;
      await Promise.resolve();
    });

    expect(stopTrack).toHaveBeenCalledTimes(1);
    expect(FakeTranscriber.instances).toHaveLength(0);
    expect(mockCreateRecording).not.toHaveBeenCalled();
    expect(mockSaveTranscript).not.toHaveBeenCalled();
  });
});
