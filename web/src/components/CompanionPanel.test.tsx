import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CompanionPanel } from "./CompanionPanel";
import { ApiError } from "@/lib/http";
import type {
  CompanionConversation,
  CompanionConversationDetail,
  CompanionConversationList,
  CompanionEvent,
  Recording,
} from "@/lib/types";

const mockListChats = vi.fn<() => Promise<CompanionConversationList>>();
const mockCreateChat = vi.fn<() => Promise<CompanionConversation>>();
const mockGetChat = vi.fn<() => Promise<CompanionConversationDetail>>();
const mockPatchChat = vi.fn<() => Promise<CompanionConversation>>();
const mockDeleteChat = vi.fn<() => Promise<void>>();
const mockStreamMessage = vi.fn<() => AsyncGenerator<CompanionEvent, void, unknown>>();

vi.mock("@/lib/companion", () => ({
  listChats: (...args: unknown[]) => mockListChats(...(args as [])),
  createChat: (...args: unknown[]) => mockCreateChat(...(args as [])),
  getChat: (...args: unknown[]) => mockGetChat(...(args as [])),
  patchChat: (...args: unknown[]) => mockPatchChat(...(args as [])),
  deleteChat: (...args: unknown[]) => mockDeleteChat(...(args as [])),
  streamMessage: (...args: unknown[]) => mockStreamMessage(...(args as [])),
}));

const recordings: Recording[] = [
  {
    id: "rec-1",
    title: "Standup",
    type: "meeting",
    audio_url: null,
    status: "ready",
    failure_code: null,
    failure_message: null,
    uploaded_at: null,
    duration_seconds: null,
    language: null,
    folder_id: null,
    deleted_at: null,
    starred_at: null,
    created_at: "2026-04-16T00:00:00Z",
  },
];

function makeChat(id: string, title: string | null = null): CompanionConversation {
  return {
    id,
    title,
    scope: null,
    pinned_at: null,
    last_message_at: null,
    archived_at: null,
    created_at: "2026-05-18T10:00:00Z",
    updated_at: "2026-05-18T10:00:00Z",
  };
}

async function* eventStream(events: CompanionEvent[]) {
  for (const evt of events) {
    yield evt;
  }
}

describe("CompanionPanel", () => {
  beforeEach(() => {
    mockListChats.mockReset();
    mockCreateChat.mockReset();
    mockGetChat.mockReset();
    mockPatchChat.mockReset();
    mockDeleteChat.mockReset();
    mockStreamMessage.mockReset();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: vi.fn(),
    });
  });

  it("shows the empty home state with starter prompts when there are no chats", async () => {
    mockListChats.mockResolvedValue({ chats: [] });

    render(<CompanionPanel recordings={recordings} />);

    expect(await screen.findByText("What do you want to know?")).toBeInTheDocument();
    expect(screen.getByText("What did I commit to this week?")).toBeInTheDocument();
  });

  it("clicking a starter prompt fills the composer", async () => {
    const user = userEvent.setup();
    mockListChats.mockResolvedValue({ chats: [] });

    render(<CompanionPanel recordings={recordings} />);

    await screen.findByText("What do you want to know?");
    await user.click(screen.getByText("Summarize my last meeting."));
    const composer = screen.getByTestId("companion-composer") as HTMLTextAreaElement;
    expect(composer.value).toBe("Summarize my last meeting.");
  });

  it("creates a new chat via the + New chat button", async () => {
    const user = userEvent.setup();
    mockListChats.mockResolvedValue({ chats: [] });
    const newChat = makeChat("new-1");
    mockCreateChat.mockResolvedValue(newChat);
    mockGetChat.mockResolvedValue({ ...newChat, messages: [] });

    render(<CompanionPanel recordings={recordings} />);
    await screen.findByText("What do you want to know?");

    await user.click(screen.getByTestId("companion-new-chat"));

    await waitFor(() => {
      expect(mockCreateChat).toHaveBeenCalled();
    });
  });

  it("renders persisted messages from getChat", async () => {
    const chat = makeChat("c1", "Past chat");
    mockListChats.mockResolvedValue({ chats: [chat] });
    mockGetChat.mockResolvedValue({
      ...chat,
      messages: [
        {
          id: "u1",
          role: "user",
          content: "What did Anna commit to?",
          tool_calls: null,
          citations: [],
          model: null,
          input_tokens: null,
          output_tokens: null,
          cached_tokens: null,
          latency_ms: null,
          created_at: "2026-05-18T10:00:01Z",
        },
        {
          id: "a1",
          role: "assistant",
          content: [{ type: "text", text: "Anna agreed to ship Friday [1]." }],
          tool_calls: null,
          citations: [
            {
              id: "cit1",
              segment_id: "seg-1",
              recording_id: "rec-1",
              span_start: 0,
              span_end: 10,
              citation_index: 1,
            },
          ],
          model: "gpt-5.5",
          input_tokens: 100,
          output_tokens: 50,
          cached_tokens: null,
          latency_ms: 1200,
          created_at: "2026-05-18T10:00:02Z",
        },
      ],
    });

    render(<CompanionPanel recordings={recordings} />);

    expect(await screen.findByText("What did Anna commit to?")).toBeInTheDocument();
    expect(screen.getByText("Anna agreed to ship Friday [1].")).toBeInTheDocument();
    // Citation chip resolves the recording title
    expect(screen.getByText(/\[1\] Standup/)).toBeInTheDocument();
  });

  it("streams a turn end-to-end, optimistically rendering user input and refetching", async () => {
    const user = userEvent.setup();
    const chat = makeChat("c1");
    mockListChats.mockResolvedValue({ chats: [chat] });
    mockGetChat
      .mockResolvedValueOnce({ ...chat, messages: [] })
      .mockResolvedValueOnce({
        ...chat,
        messages: [
          {
            id: "u-server",
            role: "user",
            content: "Hi",
            tool_calls: null,
            citations: [],
            model: null,
            input_tokens: null,
            output_tokens: null,
            cached_tokens: null,
            latency_ms: null,
            created_at: "2026-05-18T10:00:01Z",
          },
          {
            id: "a-server",
            role: "assistant",
            content: [{ type: "text", text: "Done." }],
            tool_calls: null,
            citations: [],
            model: "gpt-5.5",
            input_tokens: 10,
            output_tokens: 5,
            cached_tokens: null,
            latency_ms: 800,
            created_at: "2026-05-18T10:00:02Z",
          },
        ],
      });
    mockStreamMessage.mockImplementation(() =>
      eventStream([
        { type: "turn_start", message_id: "m1", conversation_id: "c1" },
        { type: "token", text: "Done." },
        {
          type: "done",
          message_id: "a-server",
          input_tokens: 10,
          output_tokens: 5,
          cached_tokens: null,
          model: "gpt-5.5",
          latency_ms: 800,
        },
      ]),
    );

    render(<CompanionPanel recordings={recordings} />);
    await screen.findByText("What do you want to know?");

    const composer = screen.getByTestId("companion-composer");
    await user.type(composer, "Hi");
    await user.click(screen.getByRole("button", { name: /ask/i }));

    await waitFor(() => {
      expect(screen.getByText("Done.")).toBeInTheDocument();
    });
    expect(mockStreamMessage).toHaveBeenCalledWith("c1", "Hi", expect.any(AbortSignal));
  });

  it("renders Russian copy when the ru locale prop is supplied", async () => {
    mockListChats.mockResolvedValue({ chats: [] });

    render(<CompanionPanel recordings={recordings} locale="ru" />);

    expect(await screen.findByText("Что хотите узнать?")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Спросить Wai" })).toBeInTheDocument();
    // The ask button uses the Russian label.
    expect(screen.getByRole("button", { name: "Спросить" })).toBeInTheDocument();
  });

  it("surfaces an error when the initial chat list fails to load", async () => {
    mockListChats.mockRejectedValue(new ApiError(500, "List boom"));

    render(<CompanionPanel recordings={recordings} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("List boom");
  });

  it("falls back to the generic error copy for non-Error rejections", async () => {
    mockListChats.mockRejectedValue("just a string");

    render(<CompanionPanel recordings={recordings} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Something went wrong");
  });

  it("toggles the chat history sidebar and renders a dated label for untitled chats", async () => {
    const user = userEvent.setup();
    const titled = makeChat("c1", "Quarterly review");
    const untitled = makeChat("c2");
    untitled.last_message_at = "2026-05-18T14:30:00Z";
    mockListChats.mockResolvedValue({ chats: [titled, untitled] });
    mockGetChat.mockResolvedValue({ ...titled, messages: [] });

    render(<CompanionPanel recordings={recordings} />);
    await screen.findByText("What do you want to know?");

    // Sidebar starts collapsed; the toggle advertises the chat count.
    const toggle = screen.getByTestId("companion-toggle-history");
    expect(toggle).toHaveTextContent("Chats (2)");
    expect(screen.queryByTestId("companion-chat-list")).not.toBeInTheDocument();

    await user.click(toggle);

    expect(screen.getByTestId("companion-chat-list")).toBeInTheDocument();
    expect(toggle).toHaveTextContent("Hide chats");
    // Titled chat keeps its title; untitled chat shows the "Chat · …" date label.
    expect(screen.getByText("Quarterly review")).toBeInTheDocument();
    expect(screen.getByText(/^Chat · /)).toBeInTheDocument();

    await user.click(toggle);
    expect(screen.queryByTestId("companion-chat-list")).not.toBeInTheDocument();
  });

  it("shows an empty-history hint when there are chats but the list is empty", async () => {
    // activeChatId is set, so the home starter state is suppressed, but the
    // sidebar still renders the "no chats yet" message.
    const user = userEvent.setup();
    const chat = makeChat("c1", "Only chat");
    mockListChats.mockResolvedValue({ chats: [chat] });
    mockGetChat.mockResolvedValue({ ...chat, messages: [] });

    render(<CompanionPanel recordings={recordings} />);
    await screen.findByTestId("companion-toggle-history");
    await user.click(screen.getByTestId("companion-toggle-history"));
    expect(screen.getByText("Only chat")).toBeInTheDocument();

    mockDeleteChat.mockResolvedValue(undefined);
    await user.click(screen.getByRole("button", { name: "Delete" }));
    await user.click(screen.getByTestId("companion-confirm-accept"));

    await waitFor(() => {
      expect(screen.getByText("No chats yet.")).toBeInTheDocument();
    });
  });

  it("renames a chat through the rename modal and updates the list", async () => {
    const user = userEvent.setup();
    const chat = makeChat("c1", "Old name");
    mockListChats.mockResolvedValue({ chats: [chat] });
    mockGetChat.mockResolvedValue({ ...chat, messages: [] });
    mockPatchChat.mockResolvedValue(makeChat("c1", "New name"));

    render(<CompanionPanel recordings={recordings} />);
    await screen.findByTestId("companion-toggle-history");
    await user.click(screen.getByTestId("companion-toggle-history"));

    await user.click(screen.getByRole("button", { name: "Rename" }));
    const input = screen.getByTestId("companion-rename-input") as HTMLInputElement;
    expect(input.value).toBe("Old name");
    await user.clear(input);
    await user.type(input, "New name");
    await user.click(screen.getByTestId("companion-rename-save"));

    await waitFor(() => {
      expect(mockPatchChat).toHaveBeenCalledWith("c1", { title: "New name" });
    });
    expect(screen.queryByTestId("companion-rename-modal")).not.toBeInTheDocument();
    expect(screen.getByText("New name")).toBeInTheDocument();
  });

  it("ignores a rename submit when the trimmed value is empty", async () => {
    const user = userEvent.setup();
    const chat = makeChat("c1", "Keep me");
    mockListChats.mockResolvedValue({ chats: [chat] });
    mockGetChat.mockResolvedValue({ ...chat, messages: [] });

    render(<CompanionPanel recordings={recordings} />);
    await screen.findByTestId("companion-toggle-history");
    await user.click(screen.getByTestId("companion-toggle-history"));
    await user.click(screen.getByRole("button", { name: "Rename" }));

    const input = screen.getByTestId("companion-rename-input");
    await user.clear(input);
    await user.type(input, "   ");
    await user.click(screen.getByTestId("companion-rename-save"));

    // Modal closes, no patch fired, original title intact.
    await waitFor(() => {
      expect(screen.queryByTestId("companion-rename-modal")).not.toBeInTheDocument();
    });
    expect(mockPatchChat).not.toHaveBeenCalled();
    expect(screen.getByText("Keep me")).toBeInTheDocument();
  });

  it("surfaces an error when renaming fails", async () => {
    const user = userEvent.setup();
    const chat = makeChat("c1", "Old name");
    mockListChats.mockResolvedValue({ chats: [chat] });
    mockGetChat.mockResolvedValue({ ...chat, messages: [] });
    mockPatchChat.mockRejectedValue(new ApiError(409, "Rename clash"));

    render(<CompanionPanel recordings={recordings} />);
    await screen.findByTestId("companion-toggle-history");
    await user.click(screen.getByTestId("companion-toggle-history"));
    await user.click(screen.getByRole("button", { name: "Rename" }));
    await user.type(screen.getByTestId("companion-rename-input"), "x");
    await user.click(screen.getByTestId("companion-rename-save"));

    expect(await screen.findByRole("alert")).toHaveTextContent("Rename clash");
  });

  it("closes the rename modal via the Cancel button without patching", async () => {
    const user = userEvent.setup();
    const chat = makeChat("c1", "Untouched");
    mockListChats.mockResolvedValue({ chats: [chat] });
    mockGetChat.mockResolvedValue({ ...chat, messages: [] });

    render(<CompanionPanel recordings={recordings} />);
    await screen.findByTestId("companion-toggle-history");
    await user.click(screen.getByTestId("companion-toggle-history"));
    await user.click(screen.getByRole("button", { name: "Rename" }));
    await user.click(screen.getByTestId("companion-rename-cancel"));

    expect(screen.queryByTestId("companion-rename-modal")).not.toBeInTheDocument();
    expect(mockPatchChat).not.toHaveBeenCalled();
  });

  it("closes the rename modal when Escape is pressed on the backdrop", async () => {
    const user = userEvent.setup();
    const chat = makeChat("c1", "Untouched");
    mockListChats.mockResolvedValue({ chats: [chat] });
    mockGetChat.mockResolvedValue({ ...chat, messages: [] });

    render(<CompanionPanel recordings={recordings} />);
    await screen.findByTestId("companion-toggle-history");
    await user.click(screen.getByTestId("companion-toggle-history"));
    await user.click(screen.getByRole("button", { name: "Rename" }));

    const modal = screen.getByTestId("companion-rename-modal");
    modal.focus();
    await user.keyboard("{Escape}");

    expect(screen.queryByTestId("companion-rename-modal")).not.toBeInTheDocument();
  });

  it("closes the delete modal when its backdrop is clicked", async () => {
    const user = userEvent.setup();
    const chat = makeChat("c1", "Survivor");
    mockListChats.mockResolvedValue({ chats: [chat] });
    mockGetChat.mockResolvedValue({ ...chat, messages: [] });

    render(<CompanionPanel recordings={recordings} />);
    await screen.findByTestId("companion-toggle-history");
    await user.click(screen.getByTestId("companion-toggle-history"));
    await user.click(screen.getByRole("button", { name: "Delete" }));

    // Clicking the backdrop itself (not the card) dismisses the dialog.
    await user.click(screen.getByTestId("companion-confirm-modal"));

    expect(screen.queryByTestId("companion-confirm-modal")).not.toBeInTheDocument();
    expect(mockDeleteChat).not.toHaveBeenCalled();
    expect(screen.getByText("Survivor")).toBeInTheDocument();
  });

  it("deletes the active chat, clears the thread, and refreshes to the home state", async () => {
    const user = userEvent.setup();
    const chat = makeChat("c1", "Doomed");
    mockListChats.mockResolvedValue({ chats: [chat] });
    mockGetChat.mockResolvedValue({ ...chat, messages: [] });
    mockDeleteChat.mockResolvedValue(undefined);

    render(<CompanionPanel recordings={recordings} />);
    await screen.findByTestId("companion-toggle-history");
    await user.click(screen.getByTestId("companion-toggle-history"));
    await user.click(screen.getByRole("button", { name: "Delete" }));
    await user.click(screen.getByTestId("companion-confirm-accept"));

    await waitFor(() => {
      expect(mockDeleteChat).toHaveBeenCalledWith("c1");
    });
    // activeChatId was the deleted chat → it resets to null, surfacing the home state.
    expect(await screen.findByText("What did I commit to this week?")).toBeInTheDocument();
  });

  it("surfaces an error when deletion fails", async () => {
    const user = userEvent.setup();
    const chat = makeChat("c1", "Sticky");
    mockListChats.mockResolvedValue({ chats: [chat] });
    mockGetChat.mockResolvedValue({ ...chat, messages: [] });
    mockDeleteChat.mockRejectedValue(new ApiError(403, "Delete denied"));

    render(<CompanionPanel recordings={recordings} />);
    await screen.findByTestId("companion-toggle-history");
    await user.click(screen.getByTestId("companion-toggle-history"));
    await user.click(screen.getByRole("button", { name: "Delete" }));
    await user.click(screen.getByTestId("companion-confirm-accept"));

    expect(await screen.findByRole("alert")).toHaveTextContent("Delete denied");
  });

  it("surfaces an error when loading a chat's messages fails", async () => {
    const chat = makeChat("c1", "Broken thread");
    mockListChats.mockResolvedValue({ chats: [chat] });
    mockGetChat.mockRejectedValue(new Error("Detail down"));

    render(<CompanionPanel recordings={recordings} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Detail down");
  });

  it("creates a chat on send when none is active, then reports a creation failure", async () => {
    const user = userEvent.setup();
    mockListChats.mockResolvedValue({ chats: [] });
    mockCreateChat.mockRejectedValue(new ApiError(500, "Create failed"));

    render(<CompanionPanel recordings={recordings} />);
    await screen.findByText("What do you want to know?");

    await user.type(screen.getByTestId("companion-composer"), "Hello?");
    await user.click(screen.getByRole("button", { name: /ask/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Create failed");
    expect(mockStreamMessage).not.toHaveBeenCalled();
    // Composer re-enabled after the failed turn.
    expect(screen.getByTestId("companion-composer")).not.toBeDisabled();
  });

  it("renders tool-call progress, then the answer with a formatted citation chip", async () => {
    const user = userEvent.setup();
    const chat = makeChat("c1");
    mockListChats.mockResolvedValue({ chats: [chat] });
    mockGetChat
      .mockResolvedValueOnce({ ...chat, messages: [] })
      .mockResolvedValueOnce({
        ...chat,
        messages: [
          {
            id: "u-server",
            role: "user",
            content: "When did pricing come up?",
            tool_calls: null,
            citations: [],
            model: null,
            input_tokens: null,
            output_tokens: null,
            cached_tokens: null,
            latency_ms: null,
            created_at: "2026-05-18T10:00:01Z",
          },
          {
            id: "a-server",
            role: "assistant",
            content: [{ type: "text", text: "Pricing surfaced on Tuesday [1]." }],
            tool_calls: null,
            citations: [],
            model: "gpt-5.5",
            input_tokens: 10,
            output_tokens: 5,
            cached_tokens: null,
            latency_ms: 800,
            created_at: "2026-05-18T10:00:02Z",
          },
        ],
      });

    // Drive the stream manually so we can assert each live streaming-bubble
    // state in turn: (1) tool-call list while no text has streamed, (2) the
    // streamed answer + formatted citation chip, then reconciliation to the
    // persisted turn. Two gates pause the generator between phases.
    let releaseToken: () => void = () => {};
    const tokenGate = new Promise<void>((resolve) => {
      releaseToken = resolve;
    });
    let releaseDone: () => void = () => {};
    const doneGate = new Promise<void>((resolve) => {
      releaseDone = resolve;
    });
    mockStreamMessage.mockImplementation(async function* () {
      yield { type: "turn_start", message_id: "m1", conversation_id: "c1" };
      yield { type: "tool_call", call_id: "call-1", tool: "search", args: {} };
      yield { type: "tool_result", call_id: "call-1", summary: "3 hits" };
      await tokenGate;
      yield { type: "token", text: "Pricing surfaced on Tuesday [1]." };
      yield {
        type: "citation",
        index: 1,
        segment_id: "seg-9",
        recording_id: "rec-1",
        start_ms: 65000,
        end_ms: 70000,
        span_start: 0,
        span_end: 5,
      };
      // Duplicate citation must be ignored by the dedup guard.
      yield {
        type: "citation",
        index: 1,
        segment_id: "seg-9",
        recording_id: "rec-1",
        start_ms: 65000,
        end_ms: 70000,
        span_start: 0,
        span_end: 5,
      };
      await doneGate;
      yield {
        type: "done",
        message_id: "a-server",
        input_tokens: 10,
        output_tokens: 5,
        cached_tokens: null,
        model: "gpt-5.5",
        latency_ms: 800,
      };
    });

    render(<CompanionPanel recordings={recordings} />);
    await screen.findByText("What do you want to know?");

    await user.type(screen.getByTestId("companion-composer"), "When did pricing come up?");
    await user.click(screen.getByRole("button", { name: /ask/i }));

    // Phase 1: before any token, the searching hint + tool-call progress show.
    const bubble = await screen.findByTestId("companion-streaming");
    expect(within(bubble).getByText("Searching your Inbox...")).toBeInTheDocument();
    await waitFor(() => {
      expect(within(bubble).getByText(/search → 3 hits/)).toBeInTheDocument();
    });

    // Phase 2: token + citations stream in; tool list yields to the answer.
    releaseToken();
    await waitFor(() => {
      expect(within(bubble).getByText("Pricing surfaced on Tuesday [1].")).toBeInTheDocument();
    });
    expect(within(bubble).queryByText(/search → 3 hits/)).not.toBeInTheDocument();
    // 65000ms → 1:05; the recording title resolves from props; dedup → one chip.
    const chips = within(bubble).getByTestId("companion-citations");
    expect(chips).toHaveTextContent("[1] Standup · 1:05");
    expect(chips.querySelectorAll(".scope-chip")).toHaveLength(1);

    // Phase 3: releasing `done` reconciles to the persisted assistant turn.
    releaseDone();
    await waitFor(() => {
      expect(screen.queryByTestId("companion-streaming")).not.toBeInTheDocument();
    });
    expect(screen.getByTestId("companion-message-assistant")).toHaveTextContent(
      "Pricing surfaced on Tuesday [1].",
    );
  });

  it("surfaces an inline error event and skips list reordering", async () => {
    const user = userEvent.setup();
    const chat = makeChat("c1", "Erroring");
    mockListChats.mockResolvedValue({ chats: [chat] });
    mockGetChat.mockResolvedValue({ ...chat, messages: [] });
    mockStreamMessage.mockImplementation(() =>
      eventStream([
        { type: "turn_start", message_id: "m1", conversation_id: "c1" },
        { type: "error", code: "rate_limited", message: "Slow down" },
      ]),
    );

    render(<CompanionPanel recordings={recordings} />);
    await screen.findByTestId("companion-composer");

    await user.type(screen.getByTestId("companion-composer"), "Hi");
    await user.click(screen.getByRole("button", { name: /ask/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Slow down");
    // Stream finished (error branch), so the composer is interactive again.
    await waitFor(() => {
      expect(screen.getByTestId("companion-composer")).not.toBeDisabled();
    });
  });

  it("stops an in-flight stream, clearing the streaming bubble and re-enabling input", async () => {
    const user = userEvent.setup();
    const chat = makeChat("c1", "Stoppable");
    mockListChats.mockResolvedValue({ chats: [chat] });
    mockGetChat.mockResolvedValue({ ...chat, messages: [] });

    // A stream that never resolves past the first token keeps loading=true.
    let releaseHang: () => void = () => {};
    const hang = new Promise<void>((resolve) => {
      releaseHang = resolve;
    });
    mockStreamMessage.mockImplementation(async function* () {
      yield { type: "turn_start", message_id: "m1", conversation_id: "c1" };
      yield { type: "token", text: "partial" };
      await hang;
    });

    render(<CompanionPanel recordings={recordings} />);
    await screen.findByTestId("companion-composer");

    await user.type(screen.getByTestId("companion-composer"), "Hi");
    await user.click(screen.getByRole("button", { name: /ask/i }));

    // The Stop button appears while loading.
    const stop = await screen.findByTestId("companion-stop");
    await user.click(stop);

    await waitFor(() => {
      expect(screen.queryByTestId("companion-streaming")).not.toBeInTheDocument();
    });
    expect(screen.getByTestId("companion-composer")).not.toBeDisabled();
    expect(screen.getByRole("button", { name: /ask/i })).toBeInTheDocument();
    releaseHang();
  });

  it("submits the composer when Enter is pressed without Shift", async () => {
    const user = userEvent.setup();
    const chat = makeChat("c1", "Keyboard");
    mockListChats.mockResolvedValue({ chats: [chat] });
    mockGetChat
      .mockResolvedValueOnce({ ...chat, messages: [] })
      .mockResolvedValueOnce({
        ...chat,
        messages: [
          {
            id: "u-server",
            role: "user",
            content: "Quick",
            tool_calls: null,
            citations: [],
            model: null,
            input_tokens: null,
            output_tokens: null,
            cached_tokens: null,
            latency_ms: null,
            created_at: "2026-05-18T10:00:01Z",
          },
        ],
      });
    mockStreamMessage.mockImplementation(() =>
      eventStream([
        { type: "turn_start", message_id: "m1", conversation_id: "c1" },
        { type: "token", text: "ok" },
        {
          type: "done",
          message_id: "a-server",
          input_tokens: 1,
          output_tokens: 1,
          cached_tokens: null,
          model: "gpt-5.5",
          latency_ms: 10,
        },
      ]),
    );

    render(<CompanionPanel recordings={recordings} />);
    await screen.findByTestId("companion-composer");

    const composer = screen.getByTestId("companion-composer");
    await user.type(composer, "Quick");
    await user.type(composer, "{Enter}");

    await waitFor(() => {
      expect(mockStreamMessage).toHaveBeenCalledWith("c1", "Quick", expect.any(AbortSignal));
    });
  });

  it("inserts a newline (no submit) when Shift+Enter is pressed", async () => {
    const user = userEvent.setup();
    mockListChats.mockResolvedValue({ chats: [] });

    render(<CompanionPanel recordings={recordings} />);
    await screen.findByText("What do you want to know?");

    const composer = screen.getByTestId("companion-composer") as HTMLTextAreaElement;
    await user.type(composer, "line1");
    await user.type(composer, "{Shift>}{Enter}{/Shift}");
    await user.type(composer, "line2");

    expect(composer.value).toBe("line1\nline2");
    expect(mockStreamMessage).not.toHaveBeenCalled();
  });
});
