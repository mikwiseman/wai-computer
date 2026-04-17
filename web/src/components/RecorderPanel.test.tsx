import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RecorderPanel } from "./RecorderPanel";

const mockCreateRecording = vi.fn();
const mockUploadAudio = vi.fn();
const stopTrack = vi.fn();

vi.mock("@/lib/api", () => ({
  createRecording: (...args: unknown[]) => mockCreateRecording(...args),
  uploadAudio: (...args: unknown[]) => mockUploadAudio(...args),
}));

let recordedBlob = new Blob([new Uint8Array(1_500)], { type: "audio/webm" });

interface FakeBlobEvent {
  data: Blob;
}

class FakeMediaRecorder {
  static isTypeSupported = vi.fn(() => true);

  ondataavailable: ((event: FakeBlobEvent) => void) | null = null;
  onstop: (() => void | Promise<void>) | null = null;

  start = vi.fn(() => {
    this.ondataavailable?.({ data: recordedBlob });
  });

  stop = vi.fn(() => {
    void this.onstop?.();
  });
}

describe("RecorderPanel", () => {
  beforeEach(() => {
    recordedBlob = new Blob([new Uint8Array(1_500)], { type: "audio/webm" });
    stopTrack.mockReset();
    mockCreateRecording.mockReset();
    mockUploadAudio.mockReset();

    vi.stubGlobal("MediaRecorder", FakeMediaRecorder);
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        getUserMedia: vi.fn().mockResolvedValue({
          getTracks: () => [{ stop: stopTrack }],
        }),
      },
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("records audio, uploads it, and reports completion", async () => {
    mockCreateRecording.mockResolvedValueOnce({ id: "rec-1" });
    mockUploadAudio.mockResolvedValueOnce({ id: "rec-1", title: "Recording" });

    const onRecordingComplete = vi.fn();
    const user = userEvent.setup();

    render(
      <RecorderPanel
        onRecordingComplete={onRecordingComplete}
        onError={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Record in browser" }));
    await user.click(screen.getByRole("button", { name: "Stop" }));

    await waitFor(() => {
      expect(mockCreateRecording).toHaveBeenCalledWith({
        title: expect.stringContaining("Recording "),
        type: "note",
        language: "multi",
      });
      expect(mockUploadAudio).toHaveBeenCalledWith(
        "rec-1",
        expect.objectContaining({ name: "recording.webm" }),
      );
      expect(onRecordingComplete).toHaveBeenCalledWith({ id: "rec-1", title: "Recording" });
    });

    expect(stopTrack).toHaveBeenCalled();
  });

  it("ignores recordings that are too small to upload", async () => {
    recordedBlob = new Blob([new Uint8Array(10)], { type: "audio/webm" });
    const user = userEvent.setup();

    render(
      <RecorderPanel
        onRecordingComplete={vi.fn()}
        onError={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Record in browser" }));
    await user.click(screen.getByRole("button", { name: "Stop" }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Record in browser" })).toBeInTheDocument();
    });
    expect(mockCreateRecording).not.toHaveBeenCalled();
    expect(mockUploadAudio).not.toHaveBeenCalled();
  });

  it("surfaces microphone permission failures", async () => {
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: {
        getUserMedia: vi.fn().mockRejectedValue(new Error("denied")),
      },
    });

    const onError = vi.fn();
    const user = userEvent.setup();

    render(
      <RecorderPanel
        onRecordingComplete={vi.fn()}
        onError={onError}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Record in browser" }));

    await waitFor(() => {
      expect(onError).toHaveBeenCalledWith(
        "Microphone access denied. Please allow microphone access in your browser.",
      );
    });
  });
});
