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
        files: [new File(["video"], "clip.mp4", { type: "audio/mp4" })],
      },
    });

    await waitFor(() => {
      expect(onError).toHaveBeenCalledWith(
        "Unsupported format. Use MP3, M4A, WAV, WebM, OGG, OPUS, or FLAC.",
      );
    });
    expect(mockCreateRecording).not.toHaveBeenCalled();
    expect(mockUploadAudio).not.toHaveBeenCalled();
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
        title: "meeting",
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
