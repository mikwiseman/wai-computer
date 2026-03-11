import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/http";
import { ChatPanel } from "./ChatPanel";

const mockListChatSessions = vi.fn();
const mockSendChatMessage = vi.fn();
const mockGetChatSession = vi.fn();
const mockDeleteChatSession = vi.fn();

vi.mock("@/lib/api", () => ({
  listChatSessions: (...args: unknown[]) => mockListChatSessions(...args),
  sendChatMessage: (...args: unknown[]) => mockSendChatMessage(...args),
  getChatSession: (...args: unknown[]) => mockGetChatSession(...args),
  deleteChatSession: (...args: unknown[]) => mockDeleteChatSession(...args),
}));

const baseSession = {
  id: "s1",
  title: "Planning chat",
  recording_ids: null,
  created_at: "2026-03-01T00:00:00Z",
  message_count: 4,
};

const baseSessionDetail = {
  id: "s1",
  title: "Planning chat",
  recording_ids: null,
  created_at: "2026-03-01T00:00:00Z",
  messages: [
    { id: "m1", role: "user" as const, content: "What happened in the meeting?", source_segment_ids: null, source_recording_ids: null, created_at: "2026-03-01T00:01:00Z" },
    { id: "m2", role: "assistant" as const, content: "The team discussed roadmap priorities.", source_segment_ids: ["seg1"], source_recording_ids: ["r1"], created_at: "2026-03-01T00:01:05Z" },
  ],
};

const baseChatResponse = {
  answer: "Based on your recordings, the team agreed on Q3 goals.",
  session_id: "s-new",
  message_id: "msg-resp-1",
  sources: [
    {
      segment_id: "seg1",
      recording_id: "r1",
      recording_title: "Sprint Planning",
      speaker: "Alice",
      content: "We should focus on Q3 goals.",
      start_ms: 5000,
      end_ms: 12000,
    },
  ],
};

const baseRecordings = [
  { id: "r1", title: "Sprint Planning", type: "meeting" as const, audio_url: null, duration_seconds: 600, language: "en", created_at: "2026-02-28T00:00:00Z" },
  { id: "r2", title: "Design Review", type: "meeting" as const, audio_url: null, duration_seconds: 300, language: "en", created_at: "2026-02-28T01:00:00Z" },
];

function createDeferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe("ChatPanel", () => {
  beforeEach(() => {
    [mockListChatSessions, mockSendChatMessage, mockGetChatSession, mockDeleteChatSession].forEach(
      (fn) => fn.mockReset(),
    );
  });

  // --- Core rendering ---

  it("renders chat panel with session list and input area", async () => {
    mockListChatSessions.mockResolvedValue([baseSession]);

    render(<ChatPanel recordings={[]} />);

    expect(screen.getByText("Second Brain Chat")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Ask about your meetings...")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New Chat" })).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText("Planning chat")).toBeInTheDocument();
      expect(screen.getByText("(4)")).toBeInTheDocument();
    });
  });

  it("shows empty state when no sessions exist", async () => {
    mockListChatSessions.mockResolvedValue([]);

    render(<ChatPanel recordings={[]} />);

    await waitFor(() => {
      expect(mockListChatSessions).toHaveBeenCalled();
    });

    expect(screen.getByText("Ask a question about your meetings.")).toBeInTheDocument();
  });

  it("displays error messages with role='alert'", async () => {
    mockListChatSessions.mockRejectedValue(new ApiError(500, "Server error"));

    render(<ChatPanel recordings={[]} />);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("Server error");
    });
  });

  // --- Session management ---

  it("loads and displays chat sessions on mount", async () => {
    const sessions = [
      baseSession,
      { id: "s2", title: null, recording_ids: null, created_at: "2026-03-02T00:00:00Z", message_count: 1 },
    ];
    mockListChatSessions.mockResolvedValue(sessions);

    render(<ChatPanel recordings={[]} />);

    await waitFor(() => {
      expect(screen.getByText("Planning chat")).toBeInTheDocument();
      expect(screen.getByText("Untitled")).toBeInTheDocument();
      expect(screen.getByText("(1)")).toBeInTheDocument();
    });

    expect(mockListChatSessions).toHaveBeenCalledTimes(1);
  });

  it("selects a session and loads its messages", async () => {
    mockListChatSessions.mockResolvedValue([baseSession]);
    mockGetChatSession.mockResolvedValue(baseSessionDetail);

    const user = userEvent.setup();
    render(<ChatPanel recordings={[]} />);

    await waitFor(() => {
      expect(screen.getByText("Planning chat")).toBeInTheDocument();
    });

    await user.click(screen.getByText("Planning chat"));

    await waitFor(() => {
      expect(mockGetChatSession).toHaveBeenCalledWith("s1");
      expect(screen.getByText("What happened in the meeting?")).toBeInTheDocument();
      expect(screen.getByText("The team discussed roadmap priorities.")).toBeInTheDocument();
    });
  });

  it("creates a new chat session (resets to empty state)", async () => {
    mockListChatSessions.mockResolvedValue([baseSession]);
    mockGetChatSession.mockResolvedValue(baseSessionDetail);

    const user = userEvent.setup();
    render(<ChatPanel recordings={[]} />);

    await waitFor(() => {
      expect(screen.getByText("Planning chat")).toBeInTheDocument();
    });

    // Select a session first so messages are loaded
    await user.click(screen.getByText("Planning chat"));
    await waitFor(() => {
      expect(screen.getByText("What happened in the meeting?")).toBeInTheDocument();
    });

    // Click New Chat to reset
    await user.click(screen.getByRole("button", { name: "New Chat" }));

    expect(screen.queryByText("What happened in the meeting?")).not.toBeInTheDocument();
    expect(screen.getByText("Ask a question about your meetings.")).toBeInTheDocument();
  });

  // --- Sending messages ---

  it("sends a message and displays bot response", async () => {
    mockListChatSessions.mockResolvedValue([]);
    mockSendChatMessage.mockResolvedValue(baseChatResponse);

    const user = userEvent.setup();
    render(<ChatPanel recordings={[]} />);

    await waitFor(() => {
      expect(mockListChatSessions).toHaveBeenCalled();
    });

    const textarea = screen.getByPlaceholderText("Ask about your meetings...");
    await user.type(textarea, "What were the Q3 goals?");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => {
      expect(mockSendChatMessage).toHaveBeenCalledWith({
        question: "What were the Q3 goals?",
        session_id: null,
        recording_ids: null,
      });
    });

    await waitFor(() => {
      expect(screen.getByText("What were the Q3 goals?")).toBeInTheDocument();
      expect(screen.getByText("Based on your recordings, the team agreed on Q3 goals.")).toBeInTheDocument();
    });
  });

  it("shows loading state while waiting for response", async () => {
    mockListChatSessions.mockResolvedValue([]);
    const deferred = createDeferred<typeof baseChatResponse>();
    mockSendChatMessage.mockReturnValue(deferred.promise);

    const user = userEvent.setup();
    render(<ChatPanel recordings={[]} />);

    await waitFor(() => {
      expect(mockListChatSessions).toHaveBeenCalled();
    });

    const textarea = screen.getByPlaceholderText("Ask about your meetings...");
    await user.type(textarea, "Test question");
    await user.click(screen.getByRole("button", { name: "Send" }));

    // Loading state visible while waiting
    await waitFor(() => {
      expect(screen.getByText("Thinking...")).toBeInTheDocument();
    });

    // Send button should be disabled during loading
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();

    // Resolve the deferred promise
    deferred.resolve(baseChatResponse);

    await waitFor(() => {
      expect(screen.queryByText("Thinking...")).not.toBeInTheDocument();
    });
  });

  it("handles API error when sending message (displays error)", async () => {
    mockListChatSessions.mockResolvedValue([]);
    mockSendChatMessage.mockRejectedValue(new ApiError(500, "Chat service unavailable"));

    const user = userEvent.setup();
    render(<ChatPanel recordings={[]} />);

    await waitFor(() => {
      expect(mockListChatSessions).toHaveBeenCalled();
    });

    const textarea = screen.getByPlaceholderText("Ask about your meetings...");
    await user.type(textarea, "Test question");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("Chat service unavailable");
    });

    // User message should still be visible
    expect(screen.getByText("Test question")).toBeInTheDocument();
  });

  // --- Keyboard interaction ---

  it("Enter key submits the message", async () => {
    mockListChatSessions.mockResolvedValue([]);
    mockSendChatMessage.mockResolvedValue(baseChatResponse);

    const user = userEvent.setup();
    render(<ChatPanel recordings={[]} />);

    await waitFor(() => {
      expect(mockListChatSessions).toHaveBeenCalled();
    });

    const textarea = screen.getByPlaceholderText("Ask about your meetings...");
    await user.type(textarea, "Enter key test");
    await user.keyboard("{Enter}");

    await waitFor(() => {
      expect(mockSendChatMessage).toHaveBeenCalledWith({
        question: "Enter key test",
        session_id: null,
        recording_ids: null,
      });
    });
  });

  it("Shift+Enter does NOT submit (allows newline)", async () => {
    mockListChatSessions.mockResolvedValue([]);

    const user = userEvent.setup();
    render(<ChatPanel recordings={[]} />);

    await waitFor(() => {
      expect(mockListChatSessions).toHaveBeenCalled();
    });

    const textarea = screen.getByPlaceholderText("Ask about your meetings...");
    await user.type(textarea, "Line one");
    await user.keyboard("{Shift>}{Enter}{/Shift}");
    await user.type(textarea, "Line two");

    // Should NOT have submitted
    expect(mockSendChatMessage).not.toHaveBeenCalled();
  });

  // --- Recording scope ---

  it("toggles recording selection for scoped chat", async () => {
    mockListChatSessions.mockResolvedValue([]);
    mockSendChatMessage.mockResolvedValue(baseChatResponse);

    const user = userEvent.setup();
    render(<ChatPanel recordings={baseRecordings} />);

    await waitFor(() => {
      expect(mockListChatSessions).toHaveBeenCalled();
    });

    // Recording checkboxes should be visible
    const checkbox1 = screen.getByRole("checkbox", { name: /Sprint Planning/i });
    const checkbox2 = screen.getByRole("checkbox", { name: /Design Review/i });

    expect(checkbox1).not.toBeChecked();
    expect(checkbox2).not.toBeChecked();

    // Toggle first recording on
    await user.click(checkbox1);
    expect(checkbox1).toBeChecked();

    // Toggle second recording on
    await user.click(checkbox2);
    expect(checkbox2).toBeChecked();

    // Send a message -- should include both recording IDs
    const textarea = screen.getByPlaceholderText("Ask about your meetings...");
    await user.type(textarea, "Scoped question");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => {
      expect(mockSendChatMessage).toHaveBeenCalledWith({
        question: "Scoped question",
        session_id: null,
        recording_ids: ["r1", "r2"],
      });
    });

    // Toggle first recording off
    await user.click(checkbox1);
    expect(checkbox1).not.toBeChecked();
    expect(checkbox2).toBeChecked();
  });

  it("displays recording checkboxes when available", async () => {
    mockListChatSessions.mockResolvedValue([]);

    render(<ChatPanel recordings={baseRecordings} />);

    await waitFor(() => {
      expect(mockListChatSessions).toHaveBeenCalled();
    });

    // Scope label and recording names should be visible
    expect(screen.getByText("Scope:")).toBeInTheDocument();
    expect(screen.getByText("Sprint Planning")).toBeInTheDocument();
    expect(screen.getByText("Design Review")).toBeInTheDocument();

    // Two checkboxes should exist
    const checkboxes = screen.getAllByRole("checkbox");
    expect(checkboxes).toHaveLength(2);
  });

  // --- Session deletion ---

  it("deletes a session and resets chat when active session is deleted", async () => {
    mockListChatSessions
      .mockResolvedValueOnce([baseSession])
      .mockResolvedValueOnce([]);
    mockGetChatSession.mockResolvedValue(baseSessionDetail);
    mockDeleteChatSession.mockResolvedValue(undefined);

    const user = userEvent.setup();
    render(<ChatPanel recordings={[]} />);

    await waitFor(() => {
      expect(screen.getByText("Planning chat")).toBeInTheDocument();
    });

    // Select the session to make it active
    await user.click(screen.getByText("Planning chat"));
    await waitFor(() => {
      expect(screen.getByText("What happened in the meeting?")).toBeInTheDocument();
    });

    // Delete the active session
    await user.click(screen.getByTitle("Delete session"));

    await waitFor(() => {
      expect(mockDeleteChatSession).toHaveBeenCalledWith("s1");
    });

    // Should reset to empty state since active session was deleted
    await waitFor(() => {
      expect(screen.getByText("Ask a question about your meetings.")).toBeInTheDocument();
    });
  });

  it("handles delete session error", async () => {
    mockListChatSessions.mockResolvedValue([baseSession]);
    mockDeleteChatSession.mockRejectedValue(new Error("Delete failed"));

    const user = userEvent.setup();
    render(<ChatPanel recordings={[]} />);

    await waitFor(() => {
      expect(screen.getByText("Planning chat")).toBeInTheDocument();
    });

    await user.click(screen.getByTitle("Delete session"));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("Delete failed");
    });
  });

  // --- Source toggling ---

  it("toggles source visibility and displays formatted timestamps", async () => {
    mockListChatSessions.mockResolvedValue([]);
    mockSendChatMessage.mockResolvedValue(baseChatResponse);

    const user = userEvent.setup();
    render(<ChatPanel recordings={[]} />);

    await waitFor(() => {
      expect(mockListChatSessions).toHaveBeenCalled();
    });

    const textarea = screen.getByPlaceholderText("Ask about your meetings...");
    await user.type(textarea, "Show me sources");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => {
      expect(screen.getByText(/Based on your recordings/)).toBeInTheDocument();
    });

    // Source toggle button should be visible
    const toggleButton = screen.getByText("Show sources (1)");
    expect(toggleButton).toBeInTheDocument();

    // Click to show sources
    await user.click(toggleButton);

    // Source content should now be visible with formatted timestamps
    expect(screen.getByText("We should focus on Q3 goals.")).toBeInTheDocument();
    expect(screen.getByText(/Sprint Planning/)).toBeInTheDocument();
    expect(screen.getByText(/Alice/)).toBeInTheDocument();
    // formatMs: 5000ms = 0:05, 12000ms = 0:12
    expect(screen.getByText(/0:05/)).toBeInTheDocument();
    expect(screen.getByText(/0:12/)).toBeInTheDocument();

    // Button text should change to "Hide sources"
    expect(screen.getByText("Hide sources")).toBeInTheDocument();

    // Click to hide sources
    await user.click(screen.getByText("Hide sources"));
    expect(screen.queryByText("We should focus on Q3 goals.")).not.toBeInTheDocument();
  });

  it("handles sources with null timestamps and no speaker", async () => {
    const responseNoTimestamps = {
      answer: "Here is your answer.",
      session_id: "s-null",
      message_id: "msg-null",
      sources: [
        {
          segment_id: "seg-null",
          recording_id: "r-null",
          recording_title: null,
          speaker: null,
          content: "Some transcript text.",
          start_ms: null,
          end_ms: null,
        },
      ],
    };
    mockListChatSessions.mockResolvedValue([]);
    mockSendChatMessage.mockResolvedValue(responseNoTimestamps);

    const user = userEvent.setup();
    render(<ChatPanel recordings={[]} />);

    await waitFor(() => {
      expect(mockListChatSessions).toHaveBeenCalled();
    });

    const textarea = screen.getByPlaceholderText("Ask about your meetings...");
    await user.type(textarea, "Null test");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => {
      expect(screen.getByText("Here is your answer.")).toBeInTheDocument();
    });

    await user.click(screen.getByText("Show sources (1)"));

    expect(screen.getByText("Untitled recording")).toBeInTheDocument();
    expect(screen.getByText("Some transcript text.")).toBeInTheDocument();
  });

  // --- Error formatting ---

  it("displays 'Unexpected error' for non-Error thrown values", async () => {
    mockListChatSessions.mockResolvedValue([]);
    mockSendChatMessage.mockRejectedValue("string-error-not-Error-instance");

    const user = userEvent.setup();
    render(<ChatPanel recordings={[]} />);

    await waitFor(() => {
      expect(mockListChatSessions).toHaveBeenCalled();
    });

    const textarea = screen.getByPlaceholderText("Ask about your meetings...");
    await user.type(textarea, "Trigger unknown error");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("Unexpected error");
    });
  });

  // --- Select session error ---

  it("handles getChatSession error when selecting a session", async () => {
    mockListChatSessions.mockResolvedValue([baseSession]);
    mockGetChatSession.mockRejectedValue(new Error("Session load failed"));

    const user = userEvent.setup();
    render(<ChatPanel recordings={[]} />);

    await waitFor(() => {
      expect(screen.getByText("Planning chat")).toBeInTheDocument();
    });

    await user.click(screen.getByText("Planning chat"));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("Session load failed");
    });
  });

  // --- Session with recording_ids restores selection ---

  it("restores recording selection when loading a session with recording_ids", async () => {
    const sessionWithRecordings = {
      ...baseSessionDetail,
      recording_ids: ["r1"],
    };
    mockListChatSessions.mockResolvedValue([baseSession]);
    mockGetChatSession.mockResolvedValue(sessionWithRecordings);

    const user = userEvent.setup();
    render(<ChatPanel recordings={baseRecordings} />);

    await waitFor(() => {
      expect(screen.getByText("Planning chat")).toBeInTheDocument();
    });

    await user.click(screen.getByText("Planning chat"));

    await waitFor(() => {
      expect(screen.getByRole("checkbox", { name: /Sprint Planning/i })).toBeChecked();
      expect(screen.getByRole("checkbox", { name: /Design Review/i })).not.toBeChecked();
    });
  });
});
