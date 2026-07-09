import { fireEvent, render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AudioUpload } from "./AudioUpload";

const mockCreateRecording = vi.fn();
const mockUploadAudio = vi.fn();

vi.mock("@/lib/api", () => ({
  createRecording: (...args: unknown[]) => mockCreateRecording(...args),
  uploadAudio: (...args: unknown[]) => mockUploadAudio(...args),
}));

function getFileInput(container: HTMLElement): HTMLInputElement {
  const input = container.querySelector('input[type="file"]');
  if (!(input instanceof HTMLInputElement)) {
    throw new Error("File input not found");
  }
  return input;
}

describe("AudioUpload", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("rejects unsupported file extensions before creating a recording", async () => {
    const onError = vi.fn();
    const { container } = render(
      <AudioUpload onUploadComplete={vi.fn()} onError={onError} />,
    );

    fireEvent.change(getFileInput(container), {
      target: {
        files: [new File(["text"], "notes.txt", { type: "text/plain" })],
      },
    });

    await waitFor(() => {
      expect(onError).toHaveBeenCalledWith(
        "Unsupported format. Use an audio file (MP3, M4A, WAV…) or a video (MP4, MOV, MKV…).",
      );
    });
    expect(mockCreateRecording).not.toHaveBeenCalled();
    expect(mockUploadAudio).not.toHaveBeenCalled();
  });

  it("uploads a video file — the server extracts its audio track", async () => {
    mockCreateRecording.mockResolvedValueOnce({ id: "rec-video" });
    mockUploadAudio.mockResolvedValueOnce({ id: "rec-video", title: "Team call" });

    const onUploadComplete = vi.fn();
    const { container } = render(
      <AudioUpload onUploadComplete={onUploadComplete} onError={vi.fn()} />,
    );

    fireEvent.change(getFileInput(container), {
      target: {
        files: [new File(["video"], "team-call.mp4", { type: "video/mp4" })],
      },
    });

    await waitFor(() => {
      expect(mockUploadAudio).toHaveBeenCalledWith(
        "rec-video",
        expect.objectContaining({ name: "team-call.mp4" }),
      );
      expect(onUploadComplete).toHaveBeenCalledWith({ id: "rec-video", title: "Team call" });
    });
  });

  it("creates a recording and uploads a supported file", async () => {
    mockCreateRecording.mockResolvedValueOnce({ id: "rec-1" });
    mockUploadAudio.mockResolvedValueOnce({ id: "rec-1", title: "meeting" });

    const onUploadComplete = vi.fn();
    const { container } = render(
      <AudioUpload onUploadComplete={onUploadComplete} onError={vi.fn()} />,
    );

    fireEvent.change(getFileInput(container), {
      target: {
        files: [new File(["audio"], "meeting.m4a", { type: "audio/m4a" })],
      },
    });

    await waitFor(() => {
      expect(mockCreateRecording).toHaveBeenCalledWith({
        title: "",
        type: "note",
        language: "multi",
      });
      expect(mockUploadAudio).toHaveBeenCalledWith(
        "rec-1",
        expect.objectContaining({ name: "meeting.m4a" }),
      );
      expect(onUploadComplete).toHaveBeenCalledWith({ id: "rec-1", title: "meeting" });
    });
  });

  it("uploads multiple supported files sequentially", async () => {
    mockCreateRecording
      .mockResolvedValueOnce({ id: "rec-1" })
      .mockResolvedValueOnce({ id: "rec-2" });
    mockUploadAudio
      .mockResolvedValueOnce({ id: "rec-1", title: "first" })
      .mockResolvedValueOnce({ id: "rec-2", title: "second" });

    const onUploadComplete = vi.fn();
    const { container } = render(
      <AudioUpload onUploadComplete={onUploadComplete} onError={vi.fn()} />,
    );

    fireEvent.change(getFileInput(container), {
      target: {
        files: [
          new File(["audio"], "first.m4a", { type: "audio/m4a" }),
          new File(["audio"], "second.wav", { type: "audio/wav" }),
        ],
      },
    });

    await waitFor(() => {
      expect(mockUploadAudio).toHaveBeenNthCalledWith(
        1,
        "rec-1",
        expect.objectContaining({ name: "first.m4a" }),
      );
      expect(mockUploadAudio).toHaveBeenNthCalledWith(
        2,
        "rec-2",
        expect.objectContaining({ name: "second.wav" }),
      );
      expect(onUploadComplete).toHaveBeenCalledTimes(2);
    });
  });

  it("surfaces upload failures", async () => {
    mockCreateRecording.mockResolvedValueOnce({ id: "rec-2" });
    mockUploadAudio.mockRejectedValueOnce(new Error("Upload failed"));

    const onError = vi.fn();
    const { container } = render(
      <AudioUpload onUploadComplete={vi.fn()} onError={onError} />,
    );

    fireEvent.change(getFileInput(container), {
      target: {
        files: [new File(["audio"], "meeting.wav", { type: "audio/wav" })],
      },
    });

    await waitFor(() => {
      expect(onError).toHaveBeenCalledWith("Upload failed");
    });
  });
});
