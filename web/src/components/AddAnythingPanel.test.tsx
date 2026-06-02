import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AddAnythingPanel } from "./AddAnythingPanel";

const mockCreateItem = vi.fn();
const mockGetItem = vi.fn();
const mockUploadItem = vi.fn();

vi.mock("@/lib/api", () => ({
  createItem: (...args: unknown[]) => mockCreateItem(...args),
  getItem: (...args: unknown[]) => mockGetItem(...args),
  uploadItem: (...args: unknown[]) => mockUploadItem(...args),
}));

function summarizedItem(overrides = {}) {
  return {
    id: "item-1",
    source: "url",
    source_ref: null,
    url: "https://x/post",
    kind: "article",
    title: "Solar Explainer",
    body: "...",
    occurred_at: null,
    state: "raw",
    status: "ready",
    error: null,
    folder_id: null,
    created_at: "2026-06-01T00:00:00Z",
    summary: {
      summary: "A clear explainer about solar economics.",
      key_points: ["costs fell"],
      action_items: [],
      topics: ["energy"],
      people_mentioned: [],
      highlights: [],
      key_moments: [
        {
          timestamp: "00:42",
          moment: "Thesis stated",
          why_it_matters: "Frames the argument",
          quote: null,
          importance: "high",
        },
      ],
      sentiment: "positive",
    },
    ...overrides,
  };
}

describe("AddAnythingPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("creates a URL item and renders summary + key-moments table", async () => {
    mockCreateItem.mockResolvedValue({ id: "item-1", state: "raw", summary: null });
    mockGetItem.mockResolvedValue(summarizedItem());

    render(<AddAnythingPanel />);
    fireEvent.change(screen.getByPlaceholderText(/Paste a link or any text/i), {
      target: { value: "https://x/post" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Add to brain/i }));

    await waitFor(() => {
      expect(screen.getByText("Solar Explainer")).toBeInTheDocument();
    });
    expect(mockCreateItem).toHaveBeenCalledWith({
      source: "url",
      kind: "article",
      url: "https://x/post",
    });
    expect(screen.getByText("Thesis stated")).toBeInTheDocument();
    expect(screen.getByText("00:42")).toBeInTheDocument();
  });

  it("sends pasted text as a note (not a url)", async () => {
    mockCreateItem.mockResolvedValue({ id: "item-2", state: "raw", summary: null });
    mockGetItem.mockResolvedValue(summarizedItem({ id: "item-2", title: "My Note" }));

    render(<AddAnythingPanel />);
    fireEvent.change(screen.getByPlaceholderText(/Paste a link or any text/i), {
      target: { value: "just some thoughts about the day" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Add to brain/i }));

    await waitFor(() => expect(mockCreateItem).toHaveBeenCalled());
    expect(mockCreateItem).toHaveBeenCalledWith({
      source: "paste",
      kind: "note",
      body: "just some thoughts about the day",
    });
  });

  it("shows a share-the-file message when a link needs input", async () => {
    mockCreateItem.mockResolvedValue({ id: "item-3", state: "raw", summary: null });
    mockGetItem.mockResolvedValue(
      summarizedItem({ id: "item-3", state: "needs_input", title: null, summary: null }),
    );

    render(<AddAnythingPanel />);
    fireEvent.change(screen.getByPlaceholderText(/Paste a link or any text/i), {
      target: { value: "https://instagram.com/reel/x" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Add to brain/i }));

    await waitFor(() => {
      expect(screen.getByText(/share the file or paste the text/i)).toBeInTheDocument();
    });
  });

  it("surfaces the backend's real error message on needs_input", async () => {
    mockCreateItem.mockResolvedValue({ id: "item-4", state: "raw", summary: null });
    mockGetItem.mockResolvedValue(
      summarizedItem({
        id: "item-4",
        state: "needs_input",
        status: "needs_input",
        title: null,
        summary: null,
        error: { code: "youtube_no_transcript", message: "This video has no transcript." },
      }),
    );

    render(<AddAnythingPanel />);
    fireEvent.change(screen.getByPlaceholderText(/Paste a link or any text/i), {
      target: { value: "https://youtube.com/watch?v=z" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Add to brain/i }));

    await waitFor(() =>
      expect(screen.getByText("This video has no transcript.")).toBeInTheDocument(),
    );
  });

  it("surfaces API errors via onError", async () => {
    const onError = vi.fn();
    mockCreateItem.mockRejectedValue(new Error("boom"));

    render(<AddAnythingPanel onError={onError} />);
    fireEvent.change(screen.getByPlaceholderText(/Paste a link or any text/i), {
      target: { value: "https://x/post" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Add to brain/i }));

    await waitFor(() => expect(onError).toHaveBeenCalledWith("boom"));
  });

  it("disables the button when input is empty", () => {
    render(<AddAnythingPanel />);
    expect(screen.getByRole("button", { name: /Add to brain/i })).toBeDisabled();
  });

  it("uploads a chosen document and shows its summary", async () => {
    mockUploadItem.mockResolvedValue({
      kind: "item",
      item: { id: "up-1", state: "raw", status: "summarizing", error: null, summary: null },
    });
    mockGetItem.mockResolvedValue(summarizedItem({ id: "up-1", title: "Uploaded Doc" }));

    const { container } = render(<AddAnythingPanel />);
    const input = container.querySelector(
      '[data-testid="add-anything-file"]',
    ) as HTMLInputElement;
    const file = new File(["pdf bytes"], "doc.pdf", { type: "application/pdf" });
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => expect(mockUploadItem).toHaveBeenCalledWith(file));
    await waitFor(() => expect(screen.getByText("Uploaded Doc")).toBeInTheDocument());
  });

  it("routes an audio/video upload to transcription (no item to poll)", async () => {
    mockUploadItem.mockResolvedValue({ kind: "recording", status: "processing" });

    const { container } = render(<AddAnythingPanel />);
    const input = container.querySelector(
      '[data-testid="add-anything-file"]',
    ) as HTMLInputElement;
    const file = new File(["video bytes"], "clip.mp4", { type: "video/mp4" });
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => expect(mockUploadItem).toHaveBeenCalledWith(file));
    await waitFor(() =>
      expect(screen.getByText(/appear in your recordings shortly/i)).toBeInTheDocument(),
    );
    // Media has no Item — we must NOT try to poll a summary.
    expect(mockGetItem).not.toHaveBeenCalled();
  });

  it("surfaces upload errors via onError", async () => {
    const onError = vi.fn();
    mockUploadItem.mockRejectedValue(new Error("upload boom"));

    const { container } = render(<AddAnythingPanel onError={onError} />);
    const input = container.querySelector(
      '[data-testid="add-anything-file"]',
    ) as HTMLInputElement;
    const file = new File(["x"], "doc.pdf", { type: "application/pdf" });
    fireEvent.change(input, { target: { files: [file] } });

    await waitFor(() => expect(onError).toHaveBeenCalledWith("upload boom"));
  });
});
