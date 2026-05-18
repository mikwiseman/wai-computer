import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SpeakerChip } from "./SpeakerChip";
import type { Person, RecordingDetail, Segment } from "@/lib/types";

vi.mock("@/lib/api", () => ({
  assignSpeaker: vi.fn(),
  listPeople: vi.fn(),
}));

const { assignSpeaker, listPeople } = await import("@/lib/api");
const mockAssignSpeaker = vi.mocked(assignSpeaker);
const mockListPeople = vi.mocked(listPeople);

function makeSegment(overrides?: Partial<Segment>): Segment {
  return {
    id: "seg-1",
    speaker: "Speaker 0",
    raw_label: "Speaker 0",
    person_id: null,
    display_name: null,
    auto_assigned: false,
    match_confidence: null,
    content: "hello",
    start_ms: 0,
    end_ms: 1000,
    confidence: null,
    ...overrides,
  };
}

function makePerson(overrides?: Partial<Person>): Person {
  return {
    id: "person-1",
    display_name: "Vasya",
    color: null,
    aliases: null,
    voiceprint_count: 0,
    created_at: "2026-05-18T10:00:00Z",
    updated_at: "2026-05-18T10:00:00Z",
    ...overrides,
  };
}

function makeRecording(): RecordingDetail {
  return {
    id: "rec-1",
    title: null,
    type: "meeting",
    audio_url: null,
    status: "completed",
    failure_code: null,
    failure_message: null,
    uploaded_at: null,
    duration_seconds: 60,
    language: "en",
    folder_id: null,
    deleted_at: null,
    starred_at: null,
    created_at: "2026-05-18T10:00:00Z",
    segments: [],
    summary: null,
    action_items: [],
    highlights: [],
  };
}

describe("SpeakerChip", () => {
  beforeEach(() => {
    mockAssignSpeaker.mockReset();
    mockListPeople.mockReset();
  });

  it("shows raw_label when no person assigned", () => {
    render(
      <SpeakerChip segment={makeSegment()} recordingId="rec-1" onUpdated={() => {}} />,
    );
    expect(screen.getByRole("button", { name: /Speaker 0/ })).toBeInTheDocument();
  });

  it("shows display_name with confidence indicator when auto-assigned", () => {
    const segment = makeSegment({
      person_id: "person-1",
      display_name: "Vasya",
      auto_assigned: true,
      match_confidence: 0.87,
    });
    render(
      <SpeakerChip segment={segment} recordingId="rec-1" onUpdated={() => {}} />,
    );
    expect(screen.getByText("Vasya")).toBeInTheDocument();
    expect(screen.getByText(/87%/)).toBeInTheDocument();
  });

  it("opens popover and shows existing people on click", async () => {
    mockListPeople.mockResolvedValue([
      makePerson({ id: "p-1", display_name: "Vasya" }),
      makePerson({ id: "p-2", display_name: "Masha" }),
    ]);
    const user = userEvent.setup();

    render(
      <SpeakerChip segment={makeSegment()} recordingId="rec-1" onUpdated={() => {}} />,
    );

    await user.click(screen.getByRole("button", { name: /Speaker 0/ }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Vasya" })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Masha" })).toBeInTheDocument();
    });
  });

  it("calls assignSpeaker with person_id when picking an existing person", async () => {
    mockListPeople.mockResolvedValue([
      makePerson({ id: "person-9", display_name: "Vasya" }),
    ]);
    mockAssignSpeaker.mockResolvedValue(makeRecording());
    const onUpdated = vi.fn();
    const user = userEvent.setup();

    render(
      <SpeakerChip segment={makeSegment()} recordingId="rec-1" onUpdated={onUpdated} />,
    );

    await user.click(screen.getByRole("button", { name: /Speaker 0/ }));
    await waitFor(() => screen.getByRole("button", { name: "Vasya" }));
    await user.click(screen.getByRole("button", { name: "Vasya" }));

    await waitFor(() => {
      expect(mockAssignSpeaker).toHaveBeenCalledWith("rec-1", {
        raw_label: "Speaker 0",
        person_id: "person-9",
      });
      expect(onUpdated).toHaveBeenCalled();
    });
  });

  it("creates a new person when search input has no match", async () => {
    mockListPeople.mockResolvedValue([
      makePerson({ id: "p-1", display_name: "Vasya" }),
    ]);
    mockAssignSpeaker.mockResolvedValue(makeRecording());
    const onUpdated = vi.fn();
    const user = userEvent.setup();

    render(
      <SpeakerChip segment={makeSegment()} recordingId="rec-1" onUpdated={onUpdated} />,
    );
    await user.click(screen.getByRole("button", { name: /Speaker 0/ }));
    await waitFor(() => screen.getByPlaceholderText(/Search or create/i));

    await user.type(screen.getByPlaceholderText(/Search or create/i), "Fedya");
    await user.click(screen.getByRole("button", { name: /Create.*Fedya/ }));

    await waitFor(() => {
      expect(mockAssignSpeaker).toHaveBeenCalledWith("rec-1", {
        raw_label: "Speaker 0",
        new_display_name: "Fedya",
      });
    });
  });

  it("renders disabled when no raw_label is available", () => {
    const segment = makeSegment({ raw_label: null, speaker: null });
    render(
      <SpeakerChip segment={segment} recordingId="rec-1" onUpdated={() => {}} />,
    );
    expect(screen.getByRole("button", { name: /Speaker/ })).toBeDisabled();
  });
});
