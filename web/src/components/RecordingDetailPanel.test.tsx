import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RecordingDetailPanel } from "./RecordingDetailPanel";
import type { RecordingDetail } from "@/lib/types";

vi.mock("@/lib/api", () => ({
  generateSummary: vi.fn(),
  getRecording: vi.fn(),
  exportRecording: vi.fn(),
  createRecordingShareLink: vi.fn(),
}));

const { generateSummary, getRecording, exportRecording, createRecordingShareLink } = await import(
  "@/lib/api"
);
const mockGenerateSummary = vi.mocked(generateSummary);
const mockGetRecording = vi.mocked(getRecording);
const mockExportRecording = vi.mocked(exportRecording);
const mockCreateRecordingShareLink = vi.mocked(createRecordingShareLink);
let clipboardWriteText: ReturnType<typeof vi.fn>;

function makeRecording(overrides?: Partial<RecordingDetail>): RecordingDetail {
  return {
    id: "rec-1",
    title: "Budget Meeting",
    type: "meeting",
    audio_url: null,
    status: "completed",
    failure_code: null,
    failure_message: null,
    uploaded_at: null,
    duration_seconds: 360,
    language: "en",
    folder_id: null,
    deleted_at: null,
    starred_at: null,
    created_at: "2026-04-01T10:00:00Z",
    segments: [],
    summary: null,
    action_items: [],
    highlights: [],
    ...overrides,
  };
}

describe("RecordingDetailPanel", () => {
  beforeEach(() => {
    mockGenerateSummary.mockReset();
    mockGetRecording.mockReset();
    mockExportRecording.mockReset();
    mockCreateRecordingShareLink.mockReset();
    vi.unstubAllGlobals();
    Object.defineProperty(navigator, "share", {
      configurable: true,
      value: undefined,
    });
    if (!navigator.clipboard) {
      Object.defineProperty(navigator, "clipboard", {
        configurable: true,
        value: { writeText: vi.fn() },
      });
    }
    clipboardWriteText = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue(undefined);
  });

  it("renders title and metadata", () => {
    render(<RecordingDetailPanel recording={makeRecording()} />);
    expect(screen.getByText("Budget Meeting")).toBeTruthy();
    expect(screen.getByText("Meeting")).toBeTruthy();
    expect(screen.getByText("6:00")).toBeTruthy();
  });

  it("renders untitled when title is null", () => {
    render(
      <RecordingDetailPanel recording={makeRecording({ title: null })} />,
    );
    expect(screen.getByText("(untitled recording)")).toBeTruthy();
  });

  it("hides duration when not present", () => {
    render(
      <RecordingDetailPanel
        recording={makeRecording({ duration_seconds: null })}
      />,
    );
    expect(screen.queryByText("6:00")).toBeNull();
  });

  // Transcript tab
  it("shows empty transcript message", () => {
    render(<RecordingDetailPanel recording={makeRecording()} />);
    expect(screen.getByText("No Transcript")).toBeTruthy();
  });

  it("renders transcript segments with speakers and timestamps", () => {
    const recording = makeRecording({
      segments: [
        {
          id: "s1",
          speaker: "Alice",
          content: "Let's discuss the budget",
          start_ms: 5000,
          end_ms: 10000,
          confidence: 0.95,
        },
        {
          id: "s2",
          speaker: null,
          content: "Sounds good",
          start_ms: 12000,
          end_ms: 15000,
          confidence: null,
        },
      ],
    });
    render(<RecordingDetailPanel recording={recording} />);
    expect(screen.getByText("Alice")).toBeTruthy();
    expect(screen.getByText("Let's discuss the budget")).toBeTruthy();
    expect(screen.getByText("0:05")).toBeTruthy();
    expect(screen.getByText("Sounds good")).toBeTruthy();
  });

  // Summary tab
  it("shows generate summary button when no summary", async () => {
    const user = userEvent.setup();
    render(<RecordingDetailPanel recording={makeRecording()} />);

    await user.click(screen.getByText("Summary"));
    expect(screen.getByText("No Summary")).toBeTruthy();
    expect(screen.getByText("Generate Summary")).toBeTruthy();
  });

  it("generates summary and switches to summary tab", async () => {
    const updatedRecording = makeRecording({
      summary: {
        summary: "Meeting covered Q2 budget allocation.",
        key_points: ["Budget set at $50k"],
        decisions: null,
        topics: ["budget"],
        people_mentioned: ["Alice"],
        sentiment: "positive",
      },
    });
    mockGenerateSummary.mockResolvedValue(undefined);
    mockGetRecording.mockResolvedValue(updatedRecording);

    const onUpdate = vi.fn();
    const user = userEvent.setup();
    render(
      <RecordingDetailPanel
        recording={makeRecording()}
        onRecordingUpdate={onUpdate}
      />,
    );

    await user.click(screen.getByText("Summary"));
    await user.click(screen.getByText("Generate Summary"));

    await waitFor(() => {
      expect(mockGenerateSummary).toHaveBeenCalledWith("rec-1");
    });
    await waitFor(() => {
      expect(onUpdate).toHaveBeenCalledWith(updatedRecording);
    });
  });

  it("shows error when summary generation fails", async () => {
    mockGenerateSummary.mockRejectedValue(new Error("API down"));

    const user = userEvent.setup();
    render(<RecordingDetailPanel recording={makeRecording()} />);

    await user.click(screen.getByText("Summary"));
    await user.click(screen.getByText("Generate Summary"));

    await waitFor(() => {
      expect(screen.getByText("API down")).toBeTruthy();
    });
  });

  it("renders full summary with all sections", async () => {
    const recording = makeRecording({
      summary: {
        summary: "Discussed Q2 plans.",
        key_points: ["Increase budget", "Hire 2 engineers"],
        decisions: [
          { decision: "Approve budget", context: "For Q2" },
        ],
        topics: ["budget", "hiring"],
        people_mentioned: ["Alice", "Bob"],
        sentiment: "positive",
      },
    });
    const user = userEvent.setup();
    render(<RecordingDetailPanel recording={recording} />);

    await user.click(screen.getByRole("tab", { name: "Summary" }));
    expect(screen.getByText("Discussed Q2 plans.")).toBeTruthy();
    expect(screen.getByText("Increase budget")).toBeTruthy();
    expect(screen.getByText("Hire 2 engineers")).toBeTruthy();
    expect(screen.getByText(/Approve budget/)).toBeTruthy();
    expect(screen.getByText("positive")).toBeTruthy();
  });

  // Actions tab
  it("shows empty actions message", async () => {
    const user = userEvent.setup();
    render(<RecordingDetailPanel recording={makeRecording()} />);

    const actionsTab = screen.getByRole("tab", { name: /Action Items/ });
    await user.click(actionsTab);
    expect(screen.getByText("No Action Items")).toBeTruthy();
  });

  it("renders action items with priority and status", async () => {
    const recording = makeRecording({
      action_items: [
        {
          id: "ai1",
          recording_id: "rec-1",
          task: "Send budget proposal",
          owner: "Alice",
          due_date: "2026-04-15",
          priority: "high",
          status: "pending",
          source: "ai",
          created_at: "2026-04-01T10:00:00Z",
        },
        {
          id: "ai2",
          recording_id: "rec-1",
          task: "Review Q1 results",
          owner: null,
          due_date: null,
          priority: "medium",
          status: "completed",
          source: "ai",
          created_at: "2026-04-01T10:00:00Z",
        },
      ],
    });

    const user = userEvent.setup();
    render(<RecordingDetailPanel recording={recording} />);

    const actionsTab = screen.getByRole("tab", { name: /Action Items/ });
    await user.click(actionsTab);
    expect(screen.getByText("Send budget proposal")).toBeTruthy();
    expect(screen.getByText("Alice")).toBeTruthy();
    expect(screen.getByText("2026-04-15")).toBeTruthy();
    expect(screen.getByText("high")).toBeTruthy();
    expect(screen.getByText("Review Q1 results")).toBeTruthy();
    expect(screen.getByText("medium")).toBeTruthy();
  });

  it("shows action items count in tab label", () => {
    const recording = makeRecording({
      action_items: [
        {
          id: "ai1",
          recording_id: "rec-1",
          task: "Task 1",
          owner: null,
          due_date: null,
          priority: null,
          status: "pending",
          source: "ai",
          created_at: "2026-04-01T10:00:00Z",
        },
      ],
    });
    render(<RecordingDetailPanel recording={recording} />);
    expect(screen.getByText("Action Items (1)")).toBeTruthy();
  });

  it("creates and copies a web share link", async () => {
    mockCreateRecordingShareLink.mockResolvedValue({
      recording_id: "rec-1",
      token: "share-token",
      url: "https://wai.computer/share/share-token",
      created_at: "2026-05-04T12:00:00Z",
    });

    const user = userEvent.setup();
    render(<RecordingDetailPanel recording={makeRecording()} />);

    await user.click(screen.getByRole("button", { name: "Share" }));

    await waitFor(() => {
      expect(mockCreateRecordingShareLink).toHaveBeenCalledWith("rec-1");
    });
    await waitFor(() => {
      expect(clipboardWriteText).toHaveBeenCalledWith(
        "https://wai.computer/share/share-token",
      );
    });
    await waitFor(() => {
      expect(screen.getByText("Share link copied.")).toBeTruthy();
    });
  });

  // Export
  it("triggers export download", async () => {
    const blob = new Blob(["test content"], { type: "text/plain" });
    mockExportRecording.mockResolvedValue(blob);

    const createObjectURL = vi.fn(() => "blob:test");
    const revokeObjectURL = vi.fn();
    Object.defineProperty(globalThis, "URL", {
      value: { createObjectURL, revokeObjectURL },
      writable: true,
    });

    const clickSpy = vi.fn();
    const createElementOrig = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation((tag) => {
      const el = createElementOrig(tag);
      if (tag === "a") {
        Object.defineProperty(el, "click", { value: clickSpy });
      }
      return el;
    });

    const user = userEvent.setup();
    render(<RecordingDetailPanel recording={makeRecording()} />);

    const select = screen.getByDisplayValue("Export");
    await user.selectOptions(select, "txt");

    await waitFor(() => {
      expect(mockExportRecording).toHaveBeenCalledWith("rec-1", "txt");
    });
    await waitFor(() => {
      expect(clickSpy).toHaveBeenCalled();
    });

    vi.restoreAllMocks();
  });

  it("shows error on export failure", async () => {
    mockExportRecording.mockRejectedValue(new Error("Download failed"));

    const user = userEvent.setup();
    render(<RecordingDetailPanel recording={makeRecording()} />);

    const select = screen.getByDisplayValue("Export");
    await user.selectOptions(select, "markdown");

    await waitFor(() => {
      expect(screen.getByText("Download failed")).toBeTruthy();
    });
  });
});
