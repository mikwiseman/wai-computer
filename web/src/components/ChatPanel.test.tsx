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
  { id: "r1", title: "Sprint Planning", type: "meeting" as const, audio_url: null, status: "processed", failure_code: null, failure_message: null, uploaded_at: "2026-02-28T00:00:00Z", duration_seconds: 600, language: "en", folder_id: null, deleted_at: null, starred_at: null, created_at: "2026-02-28T00:00:00Z" },
  { id: "r2", title: "Design Review", type: "meeting" as const, audio_url: null, status: "processed", failure_code: null, failure_message: null, uploaded_at: "2026-02-28T01:00:00Z", duration_seconds: 300, language: "en", folder_id: null, deleted_at: null, starred_at: null, created_at: "2026-02-28T01:00:00Z" },
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

  // --- Sources from loaded sessions ---

  it("maps source_segment_ids to sources when loading a session", async () => {
    const sessionWithSources = {
      ...baseSessionDetail,
      messages: [
        {
          id: "m1",
          role: "user" as const,
          content: "What happened?",
          source_segment_ids: null,
          source_recording_ids: null,
          created_at: "2026-03-01T00:01:00Z",
        },
        {
          id: "m2",
          role: "assistant" as const,
          content: "The team discussed priorities.",
          source_segment_ids: ["seg1", "seg2"],
          source_recording_ids: ["r1", "r2"],
          created_at: "2026-03-01T00:01:05Z",
        },
      ],
    };
    mockListChatSessions.mockResolvedValue([baseSession]);
    mockGetChatSession.mockResolvedValue(sessionWithSources);

    const user = userEvent.setup();
    render(<ChatPanel recordings={[]} />);

    await waitFor(() => {
      expect(screen.getByText("Planning chat")).toBeInTheDocument();
    });

    await user.click(screen.getByText("Planning chat"));

    await waitFor(() => {
      expect(screen.getByText("The team discussed priorities.")).toBeInTheDocument();
    });

    // The assistant message should have a sources toggle since source_segment_ids were mapped
    expect(screen.getByText("Show sources (2)")).toBeInTheDocument();
  });

  // --- Pinned session display ---

  it("displays pinned sessions (sessions with pinned_at) in the sidebar", async () => {
    const pinnedSession = {
      id: "s-pinned",
      title: "Pinned Discussion",
      recording_ids: null,
      created_at: "2026-03-01T00:00:00Z",
      message_count: 6,
      pinned_at: "2026-03-05T10:00:00Z",
    };
    const unpinnedSession = {
      id: "s-unpinned",
      title: "Regular Chat",
      recording_ids: null,
      created_at: "2026-03-02T00:00:00Z",
      message_count: 2,
      pinned_at: null,
    };
    mockListChatSessions.mockResolvedValue([pinnedSession, unpinnedSession]);

    render(<ChatPanel recordings={[]} />);

    await waitFor(() => {
      expect(screen.getByText("Pinned Discussion")).toBeInTheDocument();
      expect(screen.getByText("Regular Chat")).toBeInTheDocument();
      expect(screen.getByText("(6)")).toBeInTheDocument();
      expect(screen.getByText("(2)")).toBeInTheDocument();
    });
  });

  // --- Empty message cannot be sent ---

  it("does not send empty or whitespace-only messages", async () => {
    mockListChatSessions.mockResolvedValue([]);

    const user = userEvent.setup();
    render(<ChatPanel recordings={[]} />);

    await waitFor(() => {
      expect(mockListChatSessions).toHaveBeenCalled();
    });

    // The send button should be disabled when input is empty
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();

    // Type whitespace only
    const textarea = screen.getByPlaceholderText("Ask about your meetings...");
    await user.type(textarea, "   ");

    // Button should still be disabled for whitespace-only input
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();

    // Should never have called sendChatMessage
    expect(mockSendChatMessage).not.toHaveBeenCalled();
  });

  // --- Multiple messages in a conversation ---

  it("accumulates messages in a single conversation", async () => {
    mockListChatSessions.mockResolvedValue([]);
    const firstResponse = {
      answer: "First answer.",
      session_id: "s-conv",
      message_id: "msg-1",
      sources: [],
    };
    const secondResponse = {
      answer: "Second answer.",
      session_id: "s-conv",
      message_id: "msg-2",
      sources: [],
    };
    mockSendChatMessage
      .mockResolvedValueOnce(firstResponse)
      .mockResolvedValueOnce(secondResponse);

    const user = userEvent.setup();
    render(<ChatPanel recordings={[]} />);

    await waitFor(() => {
      expect(mockListChatSessions).toHaveBeenCalled();
    });

    // Send first message
    const textarea = screen.getByPlaceholderText("Ask about your meetings...");
    await user.type(textarea, "First question");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => {
      expect(screen.getByText("First question")).toBeInTheDocument();
      expect(screen.getByText("First answer.")).toBeInTheDocument();
    });

    // Send second message
    await user.type(textarea, "Second question");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => {
      expect(screen.getByText("Second question")).toBeInTheDocument();
      expect(screen.getByText("Second answer.")).toBeInTheDocument();
    });

    // First messages should still be visible
    expect(screen.getByText("First question")).toBeInTheDocument();
    expect(screen.getByText("First answer.")).toBeInTheDocument();

    // Second call should include session_id from first response
    expect(mockSendChatMessage).toHaveBeenNthCalledWith(2, {
      question: "Second question",
      session_id: "s-conv",
      recording_ids: null,
    });
  });

  // --- Deselecting all recordings sends null ---

  it("sends null recording_ids when all recordings are deselected", async () => {
    mockListChatSessions.mockResolvedValue([]);
    mockSendChatMessage.mockResolvedValue(baseChatResponse);

    const user = userEvent.setup();
    render(<ChatPanel recordings={baseRecordings} />);

    await waitFor(() => {
      expect(mockListChatSessions).toHaveBeenCalled();
    });

    const checkbox1 = screen.getByRole("checkbox", { name: /Sprint Planning/i });

    // Select then deselect
    await user.click(checkbox1);
    expect(checkbox1).toBeChecked();
    await user.click(checkbox1);
    expect(checkbox1).not.toBeChecked();

    // Send a message — recording_ids should be null since nothing is selected
    const textarea = screen.getByPlaceholderText("Ask about your meetings...");
    await user.type(textarea, "No scope question");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => {
      expect(mockSendChatMessage).toHaveBeenCalledWith({
        question: "No scope question",
        session_id: null,
        recording_ids: null,
      });
    });
  });

  // --- Multiple sources with toggle ---

  it("correctly counts and displays multiple sources", async () => {
    const multiSourceResponse = {
      answer: "Here are findings from multiple recordings.",
      session_id: "s-multi",
      message_id: "msg-multi",
      sources: [
        {
          segment_id: "seg1",
          recording_id: "r1",
          recording_title: "Meeting A",
          speaker: "Alice",
          content: "First source content.",
          start_ms: 1000,
          end_ms: 5000,
        },
        {
          segment_id: "seg2",
          recording_id: "r2",
          recording_title: "Meeting B",
          speaker: "Bob",
          content: "Second source content.",
          start_ms: 2000,
          end_ms: 8000,
        },
        {
          segment_id: "seg3",
          recording_id: "r3",
          recording_title: "Meeting C",
          speaker: null,
          content: "Third source content.",
          start_ms: null,
          end_ms: null,
        },
      ],
    };
    mockListChatSessions.mockResolvedValue([]);
    mockSendChatMessage.mockResolvedValue(multiSourceResponse);

    const user = userEvent.setup();
    render(<ChatPanel recordings={[]} />);

    await waitFor(() => {
      expect(mockListChatSessions).toHaveBeenCalled();
    });

    const textarea = screen.getByPlaceholderText("Ask about your meetings...");
    await user.type(textarea, "Multi source test");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => {
      expect(screen.getByText(/findings from multiple/)).toBeInTheDocument();
    });

    // Should show count of 3 sources
    expect(screen.getByText("Show sources (3)")).toBeInTheDocument();

    // Expand sources
    await user.click(screen.getByText("Show sources (3)"));

    expect(screen.getByText("First source content.")).toBeInTheDocument();
    expect(screen.getByText("Second source content.")).toBeInTheDocument();
    expect(screen.getByText("Third source content.")).toBeInTheDocument();
    expect(screen.getByText(/Meeting A/)).toBeInTheDocument();
    expect(screen.getByText(/Meeting B/)).toBeInTheDocument();
    expect(screen.getByText(/Meeting C/)).toBeInTheDocument();
  });

  // --- New chat clears recording selection ---

  it("clears recording selection when starting a new chat after session load", async () => {
    const sessionWithRecordings = {
      ...baseSessionDetail,
      recording_ids: ["r1"],
    };
    mockListChatSessions.mockResolvedValue([baseSession]);
    mockGetChatSession.mockResolvedValue(sessionWithRecordings);
    mockSendChatMessage.mockResolvedValue(baseChatResponse);

    const user = userEvent.setup();
    render(<ChatPanel recordings={baseRecordings} />);

    await waitFor(() => {
      expect(screen.getByText("Planning chat")).toBeInTheDocument();
    });

    // Select session that has recording_ids, which restores checkbox
    await user.click(screen.getByText("Planning chat"));
    await waitFor(() => {
      expect(screen.getByRole("checkbox", { name: /Sprint Planning/i })).toBeChecked();
    });

    // Click New Chat
    await user.click(screen.getByRole("button", { name: "New Chat" }));

    // Recording selection should NOT be automatically cleared per current component behavior,
    // but the session should be reset
    expect(screen.getByText("Ask a question about your meetings.")).toBeInTheDocument();
  });

  // --- Response with zero sources shows no toggle button ---

  it("does not show source toggle when response has no sources", async () => {
    const noSourceResponse = {
      answer: "I don't have specific sources for that.",
      session_id: "s-no-src",
      message_id: "msg-no-src",
      sources: [],
    };
    mockListChatSessions.mockResolvedValue([]);
    mockSendChatMessage.mockResolvedValue(noSourceResponse);

    const user = userEvent.setup();
    render(<ChatPanel recordings={[]} />);

    await waitFor(() => {
      expect(mockListChatSessions).toHaveBeenCalled();
    });

    const textarea = screen.getByPlaceholderText("Ask about your meetings...");
    await user.type(textarea, "No sources question");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => {
      expect(screen.getByText("I don't have specific sources for that.")).toBeInTheDocument();
    });

    // No "Show sources" button should appear
    expect(screen.queryByText(/Show sources/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Hide sources/)).not.toBeInTheDocument();
  });

  // --- Session list fetched on send after new session is created ---

  it("refreshes session list after sending a message that creates a new session", async () => {
    const newSessionInList = {
      id: "s-new",
      title: "New Session",
      recording_ids: null,
      created_at: "2026-03-10T00:00:00Z",
      message_count: 1,
      pinned_at: null,
    };
    mockListChatSessions
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([newSessionInList]);
    mockSendChatMessage.mockResolvedValue(baseChatResponse);

    const user = userEvent.setup();
    render(<ChatPanel recordings={[]} />);

    await waitFor(() => {
      expect(mockListChatSessions).toHaveBeenCalledTimes(1);
    });

    const textarea = screen.getByPlaceholderText("Ask about your meetings...");
    await user.type(textarea, "Start new session");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => {
      // Session list should have been re-fetched after the message was sent
      expect(mockListChatSessions).toHaveBeenCalledTimes(2);
    });

    await waitFor(() => {
      expect(screen.getByText("New Session")).toBeInTheDocument();
    });
  });

  // --- handleNewChat clears selectedRecordingIds (bugfix verification) ---

  it("handleNewChat unchecks all recording checkboxes", async () => {
    const sessionWithMultipleRecordings = {
      ...baseSessionDetail,
      recording_ids: ["r1", "r2"],
    };
    mockListChatSessions.mockResolvedValue([baseSession]);
    mockGetChatSession.mockResolvedValue(sessionWithMultipleRecordings);

    const user = userEvent.setup();
    render(<ChatPanel recordings={baseRecordings} />);

    await waitFor(() => {
      expect(screen.getByText("Planning chat")).toBeInTheDocument();
    });

    // Load session that has both recordings selected
    await user.click(screen.getByText("Planning chat"));
    await waitFor(() => {
      expect(screen.getByRole("checkbox", { name: /Sprint Planning/i })).toBeChecked();
      expect(screen.getByRole("checkbox", { name: /Design Review/i })).toBeChecked();
    });

    // Click New Chat — should clear ALL recording selections
    await user.click(screen.getByRole("button", { name: "New Chat" }));

    expect(screen.getByRole("checkbox", { name: /Sprint Planning/i })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: /Design Review/i })).not.toBeChecked();
  });

  it("handleNewChat clears selectedRecordingIds so next message sends null", async () => {
    const sessionWithRecordings = {
      ...baseSessionDetail,
      recording_ids: ["r1"],
    };
    mockListChatSessions.mockResolvedValue([baseSession]);
    mockGetChatSession.mockResolvedValue(sessionWithRecordings);
    mockSendChatMessage.mockResolvedValue(baseChatResponse);

    const user = userEvent.setup();
    render(<ChatPanel recordings={baseRecordings} />);

    await waitFor(() => {
      expect(screen.getByText("Planning chat")).toBeInTheDocument();
    });

    // Load session that restores recording selection
    await user.click(screen.getByText("Planning chat"));
    await waitFor(() => {
      expect(screen.getByRole("checkbox", { name: /Sprint Planning/i })).toBeChecked();
    });

    // Start a new chat
    await user.click(screen.getByRole("button", { name: "New Chat" }));

    // Send a message — recording_ids should be null since New Chat cleared them
    const textarea = screen.getByPlaceholderText("Ask about your meetings...");
    await user.type(textarea, "After new chat");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => {
      expect(mockSendChatMessage).toHaveBeenCalledWith({
        question: "After new chat",
        session_id: null,
        recording_ids: null,
      });
    });
  });

  // --- Loading a session sets selectedRecordingIds from session data ---

  it("loading a session with multiple recording_ids checks all corresponding checkboxes", async () => {
    const sessionWithBothRecordings = {
      ...baseSessionDetail,
      recording_ids: ["r1", "r2"],
    };
    mockListChatSessions.mockResolvedValue([baseSession]);
    mockGetChatSession.mockResolvedValue(sessionWithBothRecordings);

    const user = userEvent.setup();
    render(<ChatPanel recordings={baseRecordings} />);

    await waitFor(() => {
      expect(screen.getByText("Planning chat")).toBeInTheDocument();
    });

    await user.click(screen.getByText("Planning chat"));

    await waitFor(() => {
      expect(screen.getByRole("checkbox", { name: /Sprint Planning/i })).toBeChecked();
      expect(screen.getByRole("checkbox", { name: /Design Review/i })).toBeChecked();
    });
  });

  it("loading a session with null recording_ids clears all recording checkboxes", async () => {
    // First manually check a recording
    mockListChatSessions.mockResolvedValue([baseSession]);
    mockGetChatSession.mockResolvedValue(baseSessionDetail); // recording_ids is null

    const user = userEvent.setup();
    render(<ChatPanel recordings={baseRecordings} />);

    await waitFor(() => {
      expect(mockListChatSessions).toHaveBeenCalled();
    });

    // Manually select a recording
    await user.click(screen.getByRole("checkbox", { name: /Sprint Planning/i }));
    expect(screen.getByRole("checkbox", { name: /Sprint Planning/i })).toBeChecked();

    // Load a session that has no recording_ids (null) — should clear selection
    await user.click(screen.getByText("Planning chat"));

    await waitFor(() => {
      expect(screen.getByRole("checkbox", { name: /Sprint Planning/i })).not.toBeChecked();
      expect(screen.getByRole("checkbox", { name: /Design Review/i })).not.toBeChecked();
    });
  });
});
