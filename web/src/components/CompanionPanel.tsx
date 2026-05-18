"use client";

import { FormEvent, KeyboardEvent, useEffect, useMemo, useRef, useState } from "react";

import {
  createChat,
  deleteChat,
  getChat,
  listChats,
  patchChat,
  streamMessage,
} from "@/lib/companion";
import { ApiError } from "@/lib/http";
import type {
  CompanionConversation,
  CompanionEvent,
  CompanionMessage,
  Recording,
} from "@/lib/types";

interface CompanionPanelProps {
  recordings: Recording[];
}

interface StreamingCitation {
  index: number;
  segment_id: string;
  recording_id: string;
  start_ms: number | null;
  end_ms: number | null;
}

interface StreamingAssistant {
  text: string;
  citations: StreamingCitation[];
  toolCalls: { call_id: string; tool: string; summary: string | null }[];
}

const STARTER_PROMPTS = [
  "What did I commit to this week?",
  "Summarize my last meeting.",
  "What patterns show up in my reflections?",
  "When did I first mention pricing?",
];

function formatError(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Something went wrong";
}

function chatLabel(chat: CompanionConversation): string {
  if (chat.title && chat.title.trim()) return chat.title;
  const t = chat.last_message_at ?? chat.created_at;
  const d = new Date(t);
  return `Chat · ${d.toLocaleDateString()} ${d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
}

function plainText(content: unknown): string {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    const out: string[] = [];
    for (const block of content) {
      if (block && typeof block === "object" && "text" in block) {
        const t = (block as { text?: unknown }).text;
        if (typeof t === "string") out.push(t);
      }
    }
    return out.join("");
  }
  return "";
}

export function CompanionPanel({ recordings }: CompanionPanelProps) {
  const [chats, setChats] = useState<CompanionConversation[]>([]);
  const [activeChatId, setActiveChatId] = useState<string | null>(null);
  const [messages, setMessages] = useState<CompanionMessage[]>([]);
  const [streamingAssistant, setStreamingAssistant] =
    useState<StreamingAssistant | null>(null);
  const [stage, setStage] = useState<"idle" | "searching" | "composing">("idle");
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(true);
  const abortRef = useRef<AbortController | null>(null);
  const threadEndRef = useRef<HTMLDivElement | null>(null);
  const initialized = useRef(false);

  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;
    void (async () => {
      try {
        const data = await listChats();
        setChats(data.chats);
        if (data.chats.length > 0) {
          setActiveChatId(data.chats[0].id);
        }
      } catch (e) {
        setError(formatError(e));
      }
    })();
  }, []);

  useEffect(() => {
    if (!activeChatId) {
      setMessages([]);
      return;
    }
    void (async () => {
      try {
        const detail = await getChat(activeChatId);
        setMessages(detail.messages);
        setStreamingAssistant(null);
      } catch (e) {
        setError(formatError(e));
      }
    })();
  }, [activeChatId]);

  useEffect(() => {
    threadEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, streamingAssistant?.text]);

  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  const recordingTitlesById = useMemo(() => {
    const m = new Map<string, string>();
    for (const r of recordings) m.set(r.id, r.title ?? "Untitled");
    return m;
  }, [recordings]);

  async function handleNewChat() {
    setError(null);
    try {
      const chat = await createChat();
      setChats((prev) => [chat, ...prev]);
      setActiveChatId(chat.id);
    } catch (e) {
      setError(formatError(e));
    }
  }

  async function handleDeleteChat(chatId: string) {
    setError(null);
    try {
      await deleteChat(chatId);
      setChats((prev) => prev.filter((c) => c.id !== chatId));
      if (activeChatId === chatId) {
        setActiveChatId(null);
      }
    } catch (e) {
      setError(formatError(e));
    }
  }

  async function handleRenameChat(chatId: string) {
    const next = window.prompt("Rename chat");
    if (!next) return;
    try {
      const updated = await patchChat(chatId, { title: next });
      setChats((prev) => prev.map((c) => (c.id === chatId ? updated : c)));
    } catch (e) {
      setError(formatError(e));
    }
  }

  async function handleSend(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const question = input.trim();
    if (!question || loading) return;

    setError(null);
    setInput("");
    setLoading(true);
    setStage("searching");

    let chatId = activeChatId;
    if (!chatId) {
      try {
        const chat = await createChat();
        setChats((prev) => [chat, ...prev]);
        setActiveChatId(chat.id);
        chatId = chat.id;
      } catch (e) {
        setError(formatError(e));
        setLoading(false);
        setStage("idle");
        return;
      }
    }

    // Optimistically render the user turn.
    const optimisticUser: CompanionMessage = {
      id: `local-${Date.now()}`,
      role: "user",
      content: question,
      tool_calls: null,
      citations: [],
      model: null,
      input_tokens: null,
      output_tokens: null,
      cached_tokens: null,
      latency_ms: null,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, optimisticUser]);

    const streaming: StreamingAssistant = { text: "", citations: [], toolCalls: [] };
    setStreamingAssistant(streaming);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      for await (const evt of streamMessage(chatId, question, controller.signal)) {
        handleEvent(evt, streaming);
      }
      // After the stream finishes, refetch the chat to swap optimistic rows
      // for persisted ones (and pick up authoritative IDs).
      const refreshed = await getChat(chatId);
      setMessages(refreshed.messages);
      setStreamingAssistant(null);
      // Move the active chat to the top of the list.
      setChats((prev) => {
        const idx = prev.findIndex((c) => c.id === chatId);
        if (idx < 0) return prev;
        const next = [...prev];
        const [moved] = next.splice(idx, 1);
        return [moved, ...next];
      });
    } catch (e) {
      setError(formatError(e));
      setStreamingAssistant(null);
    } finally {
      setLoading(false);
      setStage("idle");
      abortRef.current = null;
    }
  }

  function handleEvent(evt: CompanionEvent, streaming: StreamingAssistant) {
    switch (evt.type) {
      case "turn_start":
        return;
      case "tool_call":
        streaming.toolCalls.push({
          call_id: evt.call_id,
          tool: evt.tool,
          summary: null,
        });
        setStreamingAssistant({ ...streaming });
        return;
      case "tool_result": {
        const tc = streaming.toolCalls.find((t) => t.call_id === evt.call_id);
        if (tc) tc.summary = evt.summary;
        setStreamingAssistant({ ...streaming });
        return;
      }
      case "token":
        streaming.text += evt.text;
        if (streaming.text.length > 0) setStage("composing");
        setStreamingAssistant({ ...streaming });
        return;
      case "citation":
        streaming.citations.push({
          index: evt.index,
          segment_id: evt.segment_id,
          recording_id: evt.recording_id,
          start_ms: evt.start_ms,
          end_ms: evt.end_ms,
        });
        setStreamingAssistant({ ...streaming });
        return;
      case "done":
        return;
      case "error":
        setError(evt.message);
        return;
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      event.currentTarget.closest("form")?.requestSubmit();
    }
  }

  const hasNoChats = chats.length === 0 && !activeChatId;
  const isEmptyActive = !!activeChatId && messages.length === 0 && !streamingAssistant;

  return (
    <section className="qa-panel">
      <header className="qa-panel__header">
        <h2>Ask Wai</h2>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            type="button"
            className="ghost-button compact-button"
            onClick={() => setSidebarCollapsed((c) => !c)}
            aria-pressed={!sidebarCollapsed}
            data-testid="companion-toggle-history"
          >
            {sidebarCollapsed ? `Chats (${chats.length})` : "Hide chats"}
          </button>
          <button
            type="button"
            className="ghost-button compact-button"
            onClick={handleNewChat}
            data-testid="companion-new-chat"
          >
            + New chat
          </button>
        </div>
      </header>

      {!sidebarCollapsed ? (
        <aside
          className="qa-scope"
          aria-label="Chat history"
          data-testid="companion-chat-list"
        >
          {chats.length === 0 ? (
            <span>No chats yet.</span>
          ) : (
            chats.map((c) => (
              <span key={c.id} className="scope-chip" style={{ gap: 6 }}>
                <button
                  type="button"
                  onClick={() => setActiveChatId(c.id)}
                  aria-current={c.id === activeChatId ? "page" : undefined}
                  style={{
                    background: "transparent",
                    border: "none",
                    padding: 0,
                    cursor: "pointer",
                    fontWeight: c.id === activeChatId ? 600 : 400,
                  }}
                >
                  {chatLabel(c)}
                </button>
                <button
                  type="button"
                  className="ghost-button compact-button"
                  onClick={() => handleRenameChat(c.id)}
                  aria-label="Rename chat"
                >
                  Rename
                </button>
                <button
                  type="button"
                  className="ghost-button compact-button"
                  onClick={() => handleDeleteChat(c.id)}
                  aria-label="Delete chat"
                >
                  Delete
                </button>
              </span>
            ))
          )}
        </aside>
      ) : null}

      <div className="qa-output" data-testid="companion-thread">
        {hasNoChats ? (
          <div className="empty-state empty-state--center">
            <h3>What do you want to know?</h3>
            <p>Wai answers from your recordings.</p>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8, justifyContent: "center" }}>
              {STARTER_PROMPTS.map((p) => (
                <button
                  key={p}
                  type="button"
                  className="ghost-button compact-button"
                  onClick={() => setInput(p)}
                >
                  {p}
                </button>
              ))}
            </div>
          </div>
        ) : null}

        {isEmptyActive ? (
          <div className="empty-state empty-state--center">
            <h3>What do you want to know?</h3>
            <p>Wai answers from your recordings.</p>
          </div>
        ) : null}

        {messages.map((m) => (
          <article
            key={m.id}
            className="qa-bubble"
            data-role={m.role}
            data-testid={`companion-message-${m.role}`}
            style={{ marginBottom: 12, whiteSpace: "pre-wrap" }}
          >
            <strong style={{ display: "block", fontSize: 12, opacity: 0.6 }}>
              {m.role === "user" ? "You" : "Wai"}
            </strong>
            <div>{plainText(m.content)}</div>
            {m.citations.length > 0 ? (
              <CitationStrip
                citations={m.citations.map((c) => ({
                  index: c.citation_index,
                  segment_id: c.segment_id ?? "",
                  recording_id: c.recording_id ?? "",
                  start_ms: null,
                  end_ms: null,
                }))}
                recordingTitles={recordingTitlesById}
              />
            ) : null}
          </article>
        ))}

        {streamingAssistant ? (
          <article
            className="qa-bubble qa-bubble--loading"
            data-testid="companion-streaming"
            style={{ whiteSpace: "pre-wrap" }}
          >
            <strong style={{ display: "block", fontSize: 12, opacity: 0.6 }}>Wai</strong>
            {stage === "searching" && streamingAssistant.text.length === 0 ? (
              <div style={{ fontStyle: "italic", opacity: 0.7 }}>
                Searching recordings…
              </div>
            ) : null}
            {streamingAssistant.toolCalls.length > 0 && streamingAssistant.text.length === 0 ? (
              <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13, opacity: 0.7 }}>
                {streamingAssistant.toolCalls.map((tc) => (
                  <li key={tc.call_id}>
                    {tc.tool}
                    {tc.summary ? ` → ${tc.summary}` : "…"}
                  </li>
                ))}
              </ul>
            ) : null}
            {streamingAssistant.text.length > 0 ? (
              <div>{streamingAssistant.text}</div>
            ) : null}
            {streamingAssistant.citations.length > 0 ? (
              <CitationStrip
                citations={streamingAssistant.citations}
                recordingTitles={recordingTitlesById}
              />
            ) : null}
          </article>
        ) : null}

        <div ref={threadEndRef} />

        {error ? (
          <p role="alert" className="inline-alert">
            {error}
          </p>
        ) : null}
      </div>

      <form className="qa-input" onSubmit={handleSend}>
        <textarea
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask about your recordings…"
          rows={3}
          disabled={loading}
          data-testid="companion-composer"
        />
        <button type="submit" disabled={loading || input.trim().length === 0}>
          {loading ? "Sending…" : "Ask"}
        </button>
      </form>
    </section>
  );
}

function CitationStrip({
  citations,
  recordingTitles,
}: {
  citations: StreamingCitation[];
  recordingTitles: Map<string, string>;
}) {
  const sorted = [...citations].sort((a, b) => a.index - b.index);
  return (
    <div
      className="qa-sources"
      style={{ marginTop: 8, display: "flex", flexWrap: "wrap", gap: 6 }}
      data-testid="companion-citations"
    >
      {sorted.map((c) => {
        const title = recordingTitles.get(c.recording_id) ?? "Recording";
        return (
          <span key={`${c.segment_id}-${c.index}`} className="scope-chip">
            [{c.index}] {title}
            {c.start_ms !== null ? ` · ${formatMs(c.start_ms)}` : ""}
          </span>
        );
      })}
    </div>
  );
}

function formatMs(ms: number): string {
  const total = Math.floor(ms / 1000);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}
