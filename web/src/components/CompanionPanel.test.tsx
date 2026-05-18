import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CompanionPanel } from "./CompanionPanel";
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
});
