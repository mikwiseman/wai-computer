import type React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SharedRecordingClient } from "./SharedRecordingClient";
import type { SharedRecording } from "@/lib/types";

const mockGetSharedRecording = vi.fn();
const mockExportSharedRecording = vi.fn();

vi.mock("@/lib/api", () => ({
  getSharedRecording: (...args: unknown[]) => mockGetSharedRecording(...args),
  exportSharedRecording: (...args: unknown[]) => mockExportSharedRecording(...args),
}));

vi.mock("next/link", () => ({
  default: ({
    children,
    href,
    className,
    "aria-label": ariaLabel,
    "data-testid": testId,
  }: {
    children: React.ReactNode;
    href: string;
    className?: string;
    "aria-label"?: string;
    "data-testid"?: string;
  }) => (
    <a href={href} className={className} aria-label={ariaLabel} data-testid={testId}>
      {children}
    </a>
  ),
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
    mockExportSharedRecording.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
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
    expect(screen.getByText("2 min 5 sec")).toBeInTheDocument();
  });

  it("downloads markdown from a public shared recording", async () => {
    mockGetSharedRecording.mockResolvedValue(sharedRecording);
    mockExportSharedRecording.mockResolvedValue(new Blob(["# Shared Planning"], { type: "text/markdown" }));

    const createObjectURL = vi.fn(() => "blob:shared-markdown");
    const revokeObjectURL = vi.fn();
    Object.defineProperty(globalThis, "URL", {
      value: { createObjectURL, revokeObjectURL },
      writable: true,
    });

    const clickSpy = vi.fn();
    let createdAnchor: HTMLAnchorElement | null = null;
    const createElementOrig = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation((tag) => {
      const el = createElementOrig(tag);
      if (tag === "a") {
        createdAnchor = el as HTMLAnchorElement;
        Object.defineProperty(el, "click", { value: clickSpy });
      }
      return el;
    });

    const user = userEvent.setup();
    render(<SharedRecordingClient token="share-token" />);

    await user.click(await screen.findByRole("button", { name: "Download Markdown" }));

    await waitFor(() => {
      expect(mockExportSharedRecording).toHaveBeenCalledWith("share-token", "markdown");
      expect(createObjectURL).toHaveBeenCalled();
      expect(clickSpy).toHaveBeenCalled();
      expect(revokeObjectURL).toHaveBeenCalledWith("blob:shared-markdown");
    });
    expect(createdAnchor?.download).toBe("Shared_Planning.md");
  });

  it("renders unavailable state when the public token cannot be opened", async () => {
    mockGetSharedRecording.mockRejectedValue(new Error("Shared note not found"));

    render(<SharedRecordingClient token="missing-token" />);

    await waitFor(() => {
      expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Shared note unavailable");
    });
    expect(screen.getByText("Shared note not found")).toBeInTheDocument();
  });

  it("renders unavailable state in Russian", async () => {
    mockGetSharedRecording.mockRejectedValue("network error");

    render(<SharedRecordingClient token="missing-token" locale="ru" />);

    expect(screen.getByText("Открываем общую запись...")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
        "Общая запись недоступна",
      );
    });
    expect(screen.getByText("Общая запись недоступна.")).toBeInTheDocument();
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

    render(<SharedRecordingClient token="empty-token" locale="ru" />);

    await waitFor(() => {
      expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
        "Запись без названия",
      );
    });
    expect(screen.getByText("Для этой записи нет транскрипта.")).toBeInTheDocument();
  });
});
