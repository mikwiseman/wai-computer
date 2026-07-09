import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StrictMode, useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RecordingDetailPanel } from "./RecordingDetailPanel";
import type { RecordingDetail, SummaryGeneration } from "@/lib/types";

vi.mock("@/lib/api", () => ({
  startSummaryGeneration: vi.fn(),
  startRecordingSummaryAudio: vi.fn(),
  downloadRecordingSummaryAudio: vi.fn(),
  getRecording: vi.fn(),
  exportRecording: vi.fn(),
  createRecordingShareLink: vi.fn(),
  updateRecording: vi.fn(),
  rematchSpeakers: vi.fn(),
}));

const {
  startSummaryGeneration,
  startRecordingSummaryAudio,
  downloadRecordingSummaryAudio,
  getRecording,
  exportRecording,
  createRecordingShareLink,
  updateRecording,
  rematchSpeakers,
} = await import("@/lib/api");
const mockStartSummaryGeneration = vi.mocked(startSummaryGeneration);
const mockStartRecordingSummaryAudio = vi.mocked(startRecordingSummaryAudio);
const mockDownloadRecordingSummaryAudio = vi.mocked(downloadRecordingSummaryAudio);
const mockGetRecording = vi.mocked(getRecording);
const mockExportRecording = vi.mocked(exportRecording);
const mockCreateRecordingShareLink = vi.mocked(createRecordingShareLink);
const mockUpdateRecording = vi.mocked(updateRecording);
const mockRematchSpeakers = vi.mocked(rematchSpeakers);
let clipboardWriteText: ReturnType<typeof vi.fn>;

function makeSummaryGeneration(overrides?: Partial<SummaryGeneration>): SummaryGeneration {
  return {
    job_id: null,
    recording_id: "rec-1",
    status: "not_started",
    stage: "idle",
    progress_percent: 0,
    message: "Summary has not been generated.",
    requested_at: null,
    started_at: null,
    completed_at: null,
    failed_at: null,
    error_code: null,
    error_message: null,
    ...overrides,
  };
}

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
    summary_generation: makeSummaryGeneration(),
    summary_audio: {
      artifact_id: null,
      source_kind: "recording",
      source_id: "rec-1",
      status: "not_started",
      stage: "idle",
      progress_percent: 0,
      message: "Summary audio has not been created.",
      provider: null,
      model: null,
      voice_id: null,
      language: null,
      content_type: null,
      byte_size: null,
      duration_seconds: null,
      audio_url: null,
      requested_at: null,
      started_at: null,
      completed_at: null,
      failed_at: null,
      error_code: null,
      error_message: null,
    },
    action_items: [],
    highlights: [],
    ...overrides,
  };
}

describe("RecordingDetailPanel", () => {
  beforeEach(() => {
    mockStartSummaryGeneration.mockReset();
    mockStartRecordingSummaryAudio.mockReset();
    mockDownloadRecordingSummaryAudio.mockReset();
    mockGetRecording.mockReset();
    mockExportRecording.mockReset();
    mockCreateRecordingShareLink.mockReset();
    mockUpdateRecording.mockReset();
    mockRematchSpeakers.mockReset();
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

  it("renders title and metadata without the default meeting label", () => {
    render(<RecordingDetailPanel recording={makeRecording()} />);
    expect(screen.getByText("Budget Meeting")).toBeTruthy();
    // Nearly every recording is a meeting — the default type is hidden noise.
    expect(screen.queryByText("Meeting")).toBeNull();
    expect(screen.getByText(/April 1/)).toBeTruthy();
    expect(screen.getByText("6:00")).toBeTruthy();
  });

  it("labels non-default recording types", () => {
    render(<RecordingDetailPanel recording={makeRecording({ type: "note" })} />);
    expect(screen.getByText("Note")).toBeTruthy();
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

  it("shows processing transcript state while transcription is running", () => {
    render(<RecordingDetailPanel recording={makeRecording({ status: "processing" })} />);
    expect(screen.getByText("Transcript is processing")).toBeTruthy();
    expect(screen.queryByText("No Transcript")).toBeNull();
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

  // Re-match speakers (Mac parity)
  it("re-matches speakers and refreshes the recording", async () => {
    const withSegments = makeRecording({
      segments: [
        {
          id: "s1",
          speaker: "Speaker 1",
          raw_label: "Speaker 1",
          person_id: null,
          display_name: null,
          auto_assigned: true,
          match_confidence: 0.8,
          content: "Hello",
          start_ms: 0,
          end_ms: 1000,
          confidence: 0.9,
        },
      ],
    });
    mockRematchSpeakers.mockResolvedValue({
      recording_id: "rec-1",
      updated_clusters: 2,
      matched_clusters: 1,
    });
    mockGetRecording.mockResolvedValue(withSegments);
    const onUpdate = vi.fn();
    const user = userEvent.setup();
    render(<RecordingDetailPanel recording={withSegments} onRecordingUpdate={onUpdate} />);

    await user.click(screen.getByTestId("rematch-speakers"));

    await waitFor(() => expect(mockRematchSpeakers).toHaveBeenCalledWith("rec-1"));
    await waitFor(() => expect(onUpdate).toHaveBeenCalledWith(withSegments));
    await waitFor(() => expect(screen.getByText(/Voice re-match complete/)).toBeTruthy());
  });

  it("hides re-match speakers when there are no segments", () => {
    render(<RecordingDetailPanel recording={makeRecording()} />);
    expect(screen.queryByTestId("rematch-speakers")).toBeNull();
  });

  // Summary tab
  it("shows summary as unavailable when no transcript exists", async () => {
    const user = userEvent.setup();
    render(<RecordingDetailPanel recording={makeRecording()} />);

    await user.click(screen.getByText("Summary"));
    expect(screen.getByText("Summary unavailable")).toBeTruthy();
    expect(screen.queryByText("Generate Summary")).toBeNull();
  });

  it("starts summary generation automatically for a ready transcript without a job", async () => {
    const initialRecording = makeRecording({
      status: "ready",
      segments: [
        {
          id: "s1",
          speaker: "Speaker 1",
          raw_label: "speaker_0",
          person_id: null,
          display_name: null,
          auto_assigned: false,
          match_confidence: null,
          content: "Automatically summarize this transcript.",
          start_ms: 0,
          end_ms: 2400,
          confidence: 0.94,
        },
      ],
    });
    const queuedRecording = makeRecording({
      ...initialRecording,
      summary_generation: makeSummaryGeneration({
        job_id: "job-1",
        status: "queued",
        stage: "queued",
        progress_percent: 5,
        message: "Summary generation is queued.",
      }),
    });
    mockStartSummaryGeneration.mockResolvedValue(queuedRecording.summary_generation!);
    mockGetRecording.mockResolvedValue(queuedRecording);

    function Harness() {
      const [recording, setRecording] = useState<RecordingDetail>(initialRecording);
      return <RecordingDetailPanel recording={recording} onRecordingUpdate={setRecording} />;
    }

    render(<Harness />);

    await waitFor(() => {
      expect(mockStartSummaryGeneration).toHaveBeenCalledWith("rec-1", { instructions: null });
    });
    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent("Summary generation queued.");
    });
  });

  it("does not double-start automatic summary generation under StrictMode", async () => {
    const initialRecording = makeRecording({
      status: "ready",
      segments: [
        {
          id: "s1",
          speaker: "Speaker 1",
          raw_label: "speaker_0",
          person_id: null,
          display_name: null,
          auto_assigned: false,
          match_confidence: null,
          content: "Strict mode should not double queue this summary.",
          start_ms: 0,
          end_ms: 2400,
          confidence: 0.94,
        },
      ],
    });
    const queuedRecording = makeRecording({
      ...initialRecording,
      summary_generation: makeSummaryGeneration({
        job_id: "job-1",
        status: "queued",
        stage: "queued",
        progress_percent: 5,
        message: "Summary generation is queued.",
      }),
    });
    mockStartSummaryGeneration.mockResolvedValue(queuedRecording.summary_generation!);
    mockGetRecording.mockResolvedValue(queuedRecording);

    function Harness() {
      const [recording, setRecording] = useState<RecordingDetail>(initialRecording);
      return <RecordingDetailPanel recording={recording} onRecordingUpdate={setRecording} />;
    }

    render(
      <StrictMode>
        <Harness />
      </StrictMode>,
    );

    await waitFor(() => {
      expect(screen.getByRole("status")).toHaveTextContent("Summary generation queued.");
    });
    expect(mockStartSummaryGeneration).toHaveBeenCalledTimes(1);
  });

  it("renders queued summary generation progress instead of a manual generate button", async () => {
    const user = userEvent.setup();
    render(
      <RecordingDetailPanel
        recording={makeRecording({
          status: "ready",
          segments: [
            {
              id: "s1",
              speaker: "Speaker 1",
              raw_label: "speaker_0",
              person_id: null,
              display_name: null,
              auto_assigned: false,
              match_confidence: null,
              content: "Queued summary transcript.",
              start_ms: 0,
              end_ms: 1200,
              confidence: 0.92,
            },
          ],
          summary_generation: makeSummaryGeneration({
            job_id: "job-1",
            status: "running",
            stage: "generating_summary",
            progress_percent: 35,
            message: "Generating summary.",
          }),
        })}
      />,
    );

    await user.click(screen.getByText("Summary"));
    expect(screen.getByText("Summary is being generated")).toBeTruthy();
    expect(screen.getByRole("progressbar")).toHaveAttribute("value", "35");
    expect(screen.queryByText("Generate Summary")).toBeNull();
  });

  it("starts summary audio generation from the summary tab", async () => {
    const recording = makeRecording({
      summary: {
        summary: "Meeting covered Q2 budget allocation.",
        key_points: ["Budget set at $50k"],
        decisions: null,
        topics: ["budget"],
        people_mentioned: ["Alice"],
        sentiment: "positive",
      },
    });
    const updatedRecording = makeRecording({
      ...recording,
      summary_audio: {
        ...recording.summary_audio,
        artifact_id: "audio-1",
        status: "queued",
        progress_percent: 5,
        provider: "xai",
        model: "xai-text-to-speech",
        voice_id: "ara",
        language: "auto",
      },
    });
    mockStartRecordingSummaryAudio.mockResolvedValue(updatedRecording.summary_audio);
    mockGetRecording.mockResolvedValue(updatedRecording);

    const onUpdate = vi.fn();
    const user = userEvent.setup();
    render(<RecordingDetailPanel recording={recording} onRecordingUpdate={onUpdate} />);

    await user.click(screen.getByText("Summary"));
    await user.click(screen.getByText("Create audio"));

    await waitFor(() => {
      expect(mockStartRecordingSummaryAudio).toHaveBeenCalledWith("rec-1");
    });
    await waitFor(() => {
      expect(onUpdate).toHaveBeenCalledWith(updatedRecording);
    });
  });

  it("shows failed summary generation state with explicit retry", async () => {
    mockStartSummaryGeneration.mockResolvedValue(
      makeSummaryGeneration({
        job_id: "job-2",
        status: "queued",
        stage: "queued",
        progress_percent: 5,
        message: "Summary generation is queued.",
      }),
    );
    mockGetRecording.mockResolvedValue(
      makeRecording({
        status: "ready",
        summary_generation: makeSummaryGeneration({
          job_id: "job-2",
          status: "queued",
          stage: "queued",
          progress_percent: 5,
          message: "Summary generation is queued.",
        }),
      }),
    );

    const user = userEvent.setup();
    render(
      <RecordingDetailPanel
        recording={makeRecording({
          status: "ready",
          segments: [
            {
              id: "s1",
              speaker: "Speaker 1",
              raw_label: "speaker_0",
              person_id: null,
              display_name: null,
              auto_assigned: false,
              match_confidence: null,
              content: "Retry this failed summary.",
              start_ms: 0,
              end_ms: 1500,
              confidence: 0.91,
            },
          ],
          summary_generation: makeSummaryGeneration({
            job_id: "job-1",
            status: "failed",
            stage: "failed",
            progress_percent: 100,
            message: "Summary generation failed.",
            error_code: "summarization_failed",
            error_message: "Provider rejected the request.",
          }),
        })}
      />,
    );

    await user.click(screen.getByText("Summary"));
    expect(screen.getByText("Summary generation failed")).toBeTruthy();
    expect(screen.getByText("Provider rejected the request.")).toBeTruthy();

    await user.click(screen.getByText("Retry"));

    await waitFor(() => {
      expect(mockStartSummaryGeneration).toHaveBeenCalledWith("rec-1", { instructions: null });
    });
  });

  it("shows error when manual summary retry fails", async () => {
    mockStartSummaryGeneration.mockRejectedValue(new Error("API down"));

    const user = userEvent.setup();
    render(
      <RecordingDetailPanel
        recording={makeRecording({
          status: "ready",
          segments: [
            {
              id: "s1",
              speaker: "Speaker 1",
              raw_label: "speaker_0",
              person_id: null,
              display_name: null,
              auto_assigned: false,
              match_confidence: null,
              content: "Manual retry fails.",
              start_ms: 0,
              end_ms: 1500,
              confidence: 0.91,
            },
          ],
          summary_generation: makeSummaryGeneration({
            job_id: "job-1",
            status: "failed",
            stage: "failed",
            progress_percent: 100,
            message: "Summary generation failed.",
            error_code: "summarization_failed",
            error_message: "Provider rejected the request.",
          }),
        })}
      />,
    );

    await user.click(screen.getByText("Summary"));
    await user.click(screen.getByText("Retry"));

    await waitFor(() => {
      expect(screen.getByText("API down")).toBeTruthy();
    });
  });

  it("renders Mac-parity summary (overview / key points / topics / people)", async () => {
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
    // Mac source-of-truth: no Decisions section, no Sentiment chip on web.
    expect(screen.queryByText(/Decisions/i)).toBeNull();
    expect(screen.queryByText("Approve budget")).toBeNull();
    expect(screen.queryByText("Sentiment")).toBeNull();
    expect(screen.queryByText("positive")).toBeNull();
  });

  it("does not render the removed actions tab", () => {
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
      ],
    });
    render(<RecordingDetailPanel recording={recording} />);
    expect(screen.queryByRole("tab", { name: /Action Items/ })).toBeNull();
    expect(screen.queryByText("Send budget proposal")).toBeNull();
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
      expect(mockExportRecording).toHaveBeenCalledWith("rec-1", "txt", { locale: "en" });
    });
    await waitFor(() => {
      expect(clickSpy).toHaveBeenCalled();
    });

    vi.restoreAllMocks();
  });

  it("renames the selected recording", async () => {
    mockUpdateRecording.mockResolvedValue({ ...makeRecording(), title: "New title" });
    mockGetRecording.mockResolvedValue(makeRecording({ title: "New title" }));

    const user = userEvent.setup();
    const onUpdate = vi.fn();
    render(<RecordingDetailPanel recording={makeRecording()} onRecordingUpdate={onUpdate} />);

    await user.click(screen.getByRole("button", { name: "Rename" }));
    await user.clear(screen.getByDisplayValue("Budget Meeting"));
    await user.type(screen.getByDisplayValue(""), "New title");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(mockUpdateRecording).toHaveBeenCalledWith("rec-1", { title: "New title" });
      expect(onUpdate).toHaveBeenCalledWith(makeRecording({ title: "New title" }));
    });
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

  // --- Move-to-folder control ---------------------------------------------

  it("renders 'Move to folder' select when folders + onAssignFolder are provided", () => {
    const folders = [
      { id: "folder-a", name: "Work", created_at: "2026-05-27T00:00:00Z" },
      { id: "folder-b", name: "Personal", created_at: "2026-05-27T00:00:00Z" },
    ];
    render(
      <RecordingDetailPanel
        recording={makeRecording()}
        folders={folders}
        onAssignFolder={() => {}}
      />,
    );

    const select = screen.getByTestId("assign-folder-select");
    expect(select).toBeTruthy();
    expect(select.getAttribute("aria-label")).toBe("Move to folder");
    expect(screen.getByText("(no folder)")).toBeTruthy();
    expect(screen.getByText("Work")).toBeTruthy();
    expect(screen.getByText("Personal")).toBeTruthy();
  });

  it("renders Russian label when locale='ru'", () => {
    render(
      <RecordingDetailPanel
        recording={makeRecording()}
        folders={[]}
        locale="ru"
        onAssignFolder={() => {}}
      />,
    );

    const select = screen.getByTestId("assign-folder-select");
    expect(select.getAttribute("aria-label")).toBe("Переместить в папку");
    expect(screen.getByText("(без папки)")).toBeTruthy();
  });

  it("calls onAssignFolder when a folder is selected from the dropdown", async () => {
    const folders = [
      { id: "folder-work", name: "Work", created_at: "2026-05-27T00:00:00Z" },
    ];
    const onAssignFolder = vi.fn();
    const onUpdate = vi.fn();
    const user = userEvent.setup();
    render(
      <RecordingDetailPanel
        recording={makeRecording()}
        folders={folders}
        onAssignFolder={onAssignFolder}
        onRecordingUpdate={onUpdate}
      />,
    );

    await user.selectOptions(screen.getByTestId("assign-folder-select"), "folder-work");

    await waitFor(() => {
      expect(onAssignFolder).toHaveBeenCalledWith("rec-1", "folder-work");
    });
    // Optimistic local update fires too.
    expect(onUpdate).toHaveBeenCalledWith(
      expect.objectContaining({ id: "rec-1", folder_id: "folder-work" }),
    );
  });

  it("calls onAssignFolder with null when the '(no folder)' option is selected", async () => {
    const folders = [
      { id: "folder-work", name: "Work", created_at: "2026-05-27T00:00:00Z" },
    ];
    const onAssignFolder = vi.fn();
    const user = userEvent.setup();
    render(
      <RecordingDetailPanel
        recording={makeRecording({ folder_id: "folder-work" })}
        folders={folders}
        onAssignFolder={onAssignFolder}
      />,
    );

    await user.selectOptions(screen.getByTestId("assign-folder-select"), "");

    await waitFor(() => {
      expect(onAssignFolder).toHaveBeenCalledWith("rec-1", null);
    });
  });

  it("hides the move-to-folder select when no folders prop is passed", () => {
    render(<RecordingDetailPanel recording={makeRecording()} />);
    expect(screen.queryByTestId("assign-folder-select")).toBeNull();
  });
});
