import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SharedRecordingClient } from "./SharedRecordingClient";
import type { SharedRecording } from "@/lib/types";

const mockGetSharedRecording = vi.fn();

vi.mock("@/lib/api", () => ({
  getSharedRecording: (...args: unknown[]) => mockGetSharedRecording(...args),
}));

const sharedRecording: SharedRecording = {
  id: "rec-1",
  title: "Shared Planning",
  type: "meeting",
  duration_seconds: 125,
  language: "en",
  created_at: "2026-05-04T12:00:00Z",
  shared_at: "2026-05-04T12:30:00Z",
  segments: [
    {
      id: "seg-1",
      speaker: "Mik",
      content: "Open the shared note in the web app.",
      start_ms: 1000,
      end_ms: 5000,
      confidence: 0.96,
    },
  ],
  summary: {
    summary: "The team reviewed public sharing.",
    key_points: ["Open shared notes on web"],
    decisions: [],
    topics: ["sharing"],
    people_mentioned: ["Mik"],
    sentiment: "positive",
  },
  action_items: [
    {
      id: "action-1",
      recording_id: "rec-1",
      task: "Add the Mac share button",
      owner: null,
      due_date: null,
      priority: "high",
      status: "pending",
      source: "generated",
      created_at: "2026-05-04T12:00:00Z",
    },
  ],
  highlights: [],
};

describe("SharedRecordingClient", () => {
  beforeEach(() => {
    mockGetSharedRecording.mockReset();
  });

  it("loads and renders a public shared recording", async () => {
    mockGetSharedRecording.mockResolvedValue(sharedRecording);

    render(<SharedRecordingClient token="share-token" />);

    expect(screen.getByText("Opening shared note...")).toBeInTheDocument();

    await waitFor(() => {
      expect(mockGetSharedRecording).toHaveBeenCalledWith("share-token");
      expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Shared Planning");
    });

    expect(screen.getByText("The team reviewed public sharing.")).toBeInTheDocument();
    expect(screen.getByText("Open shared notes on web")).toBeInTheDocument();
    expect(screen.getByText("Add the Mac share button")).toBeInTheDocument();
    expect(screen.getByText("Open the shared note in the web app.")).toBeInTheDocument();
    expect(screen.getByText("Mik")).toBeInTheDocument();
    expect(screen.getByText("2:05")).toBeInTheDocument();
  });

  it("renders unavailable state when the public token cannot be opened", async () => {
    mockGetSharedRecording.mockRejectedValue(new Error("Shared note not found"));

    render(<SharedRecordingClient token="missing-token" />);

    await waitFor(() => {
      expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Shared note unavailable");
    });
    expect(screen.getByText("Shared note not found")).toBeInTheDocument();
  });

  it("renders a transcript empty state", async () => {
    mockGetSharedRecording.mockResolvedValue({
      ...sharedRecording,
      title: null,
      segments: [],
      summary: null,
      action_items: [],
      duration_seconds: null,
    });

    render(<SharedRecordingClient token="empty-token" />);

    await waitFor(() => {
      expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Untitled recording");
    });
    expect(screen.getByText("No transcript is available for this note.")).toBeInTheDocument();
  });
});
