"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import {
  deleteChatSession,
  getChatSession,
  listChatSessions,
  sendChatMessage,
} from "@/lib/api";
import { ApiError } from "@/lib/http";
import type {
  ChatSession,
  ChatSource,
  Recording,
} from "@/lib/types";

interface DisplayMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: ChatSource[];
}

interface ChatPanelProps {
  recordings: Recording[];
}

function formatError(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Unexpected error";
}

function formatMs(ms: number | null): string {
  if (ms === null) return "";
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

export function ChatPanel({ recordings }: ChatPanelProps) {
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [selectedRecordingIds, setSelectedRecordingIds] = useState<string[]>([]);
  const [showSources, setShowSources] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);

  const loadSessions = useCallback(async () => {
    try {
      const result = await listChatSessions();
      setSessions(result);
    } catch (err: unknown) {
      setError(formatError(err));
    }
  }, []);

  useEffect(() => {
    void loadSessions();
  }, [loadSessions]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function handleSend(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const question = input.trim();
    if (question.length === 0 || loading) return;

    setError(null);
    setInput("");

    const userMessage: DisplayMessage = {
      id: `user-${Date.now()}`,
      role: "user",
      content: question,
    };
    setMessages((prev) => [...prev, userMessage]);
    setLoading(true);

    try {
      const response = await sendChatMessage({
        question,
        session_id: sessionId,
        recording_ids: selectedRecordingIds.length > 0 ? selectedRecordingIds : null,
      });

      setSessionId(response.session_id);

      const assistantMessage: DisplayMessage = {
        id: response.message_id,
        role: "assistant",
        content: response.answer,
        sources: response.sources,
      };
      setMessages((prev) => [...prev, assistantMessage]);
      await loadSessions();
    } catch (err: unknown) {
      setError(formatError(err));
    } finally {
      setLoading(false);
    }
  }

  async function handleSelectSession(id: string) {
    setError(null);
    try {
      const detail = await getChatSession(id);
      setSessionId(detail.id);
      setSelectedRecordingIds(detail.recording_ids ?? []);
      const displayMessages: DisplayMessage[] = detail.messages.map((msg) => ({
        id: msg.id,
        role: msg.role,
        content: msg.content,
      }));
      setMessages(displayMessages);
    } catch (err: unknown) {
      setError(formatError(err));
    }
  }

  async function handleDeleteSession(id: string) {
    setError(null);
    try {
      await deleteChatSession(id);
      if (sessionId === id) {
        handleNewChat();
      }
      await loadSessions();
    } catch (err: unknown) {
      setError(formatError(err));
    }
  }

  function handleNewChat() {
    setSessionId(null);
    setMessages([]);
    setError(null);
  }

  function toggleSources(messageId: string) {
    setShowSources((prev) => ({ ...prev, [messageId]: !prev[messageId] }));
  }

  function handleRecordingToggle(recordingId: string) {
    setSelectedRecordingIds((prev) =>
      prev.includes(recordingId)
        ? prev.filter((id) => id !== recordingId)
        : [...prev, recordingId],
    );
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      const form = event.currentTarget.closest("form");
      if (form) {
        form.requestSubmit();
      }
    }
  }

  return (
    <section className="card stack">
      <h2>Second Brain Chat</h2>

      <div style={{ display: "flex", gap: "16px", height: "600px" }}>
        {/* Sidebar */}
        <div
          style={{
            width: "220px",
            minWidth: "220px",
            display: "flex",
            flexDirection: "column",
            gap: "8px",
            borderRight: "1px solid #e0e0e0",
            paddingRight: "12px",
            overflow: "hidden",
          }}
        >
          <button type="button" onClick={handleNewChat} style={{ padding: "8px 12px" }}>
            New Chat
          </button>

          <div
            style={{
              flex: 1,
              overflowY: "auto",
              display: "flex",
              flexDirection: "column",
              gap: "4px",
            }}
          >
            {sessions.map((session) => (
              <div
                key={session.id}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "4px",
                  padding: "6px 8px",
                  borderRadius: "4px",
                  backgroundColor: session.id === sessionId ? "#e8f0fe" : "transparent",
                  cursor: "pointer",
                }}
              >
                <button
                  type="button"
                  onClick={() => handleSelectSession(session.id)}
                  style={{
                    flex: 1,
                    textAlign: "left",
                    background: "none",
                    border: "none",
                    padding: 0,
                    cursor: "pointer",
                    fontSize: "13px",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {session.title ?? "Untitled"}
                  <span style={{ fontSize: "11px", color: "#888", marginLeft: "4px" }}>
                    ({session.message_count})
                  </span>
                </button>
                <button
                  type="button"
                  onClick={() => handleDeleteSession(session.id)}
                  style={{
                    background: "none",
                    border: "none",
                    cursor: "pointer",
                    fontSize: "12px",
                    color: "#999",
                    padding: "2px 4px",
                  }}
                  title="Delete session"
                  aria-label="Delete session"
                >
                  x
                </button>
              </div>
            ))}
          </div>
        </div>

        {/* Main chat area */}
        <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
          {/* Recording selector */}
          {recordings.length > 0 && (
            <div
              style={{
                display: "flex",
                gap: "6px",
                flexWrap: "wrap",
                paddingBottom: "8px",
                borderBottom: "1px solid #e0e0e0",
                marginBottom: "8px",
                fontSize: "13px",
              }}
            >
              <span style={{ color: "#666", lineHeight: "28px" }}>Scope:</span>
              {recordings.map((rec) => (
                <label
                  key={rec.id}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "4px",
                    padding: "4px 8px",
                    borderRadius: "4px",
                    backgroundColor: selectedRecordingIds.includes(rec.id)
                      ? "#e8f0fe"
                      : "#f5f5f5",
                    cursor: "pointer",
                  }}
                >
                  <input
                    type="checkbox"
                    checked={selectedRecordingIds.includes(rec.id)}
                    onChange={() => handleRecordingToggle(rec.id)}
                  />
                  {rec.title ?? "(untitled)"}
                </label>
              ))}
            </div>
          )}

          {/* Messages */}
          <div
            style={{
              flex: 1,
              overflowY: "auto",
              display: "flex",
              flexDirection: "column",
              gap: "12px",
              padding: "8px 0",
            }}
          >
            {messages.length === 0 && !loading && (
              <p style={{ color: "#888", textAlign: "center", marginTop: "40px" }}>
                Ask a question about your meetings.
              </p>
            )}

            {messages.map((msg) => (
              <div
                key={msg.id}
                style={{
                  display: "flex",
                  justifyContent: msg.role === "user" ? "flex-end" : "flex-start",
                }}
              >
                <div
                  style={{
                    maxWidth: "75%",
                    padding: "10px 14px",
                    borderRadius: "8px",
                    backgroundColor: msg.role === "user" ? "#0066cc" : "#f0f0f0",
                    color: msg.role === "user" ? "#fff" : "#222",
                    fontSize: "14px",
                    lineHeight: "1.5",
                    whiteSpace: "pre-wrap",
                  }}
                >
                  {msg.content}

                  {msg.role === "assistant" && msg.sources && msg.sources.length > 0 && (
                    <div style={{ marginTop: "8px" }}>
                      <button
                        type="button"
                        onClick={() => toggleSources(msg.id)}
                        style={{
                          background: "none",
                          border: "none",
                          cursor: "pointer",
                          fontSize: "12px",
                          color: "#0066cc",
                          padding: 0,
                        }}
                      >
                        {showSources[msg.id] ? "Hide sources" : `Show sources (${msg.sources.length})`}
                      </button>

                      {showSources[msg.id] && (
                        <div
                          style={{
                            marginTop: "6px",
                            display: "flex",
                            flexDirection: "column",
                            gap: "6px",
                          }}
                        >
                          {msg.sources.map((source, idx) => (
                            <div
                              key={`${source.segment_id}-${idx}`}
                              style={{
                                padding: "8px",
                                backgroundColor: "#e8e8e8",
                                borderRadius: "4px",
                                fontSize: "12px",
                              }}
                            >
                              <div style={{ fontWeight: 600, marginBottom: "2px" }}>
                                {source.recording_title ?? "Untitled recording"}
                                {source.speaker && ` - ${source.speaker}`}
                                {source.start_ms !== null && (
                                  <span style={{ color: "#666", marginLeft: "6px" }}>
                                    [{formatMs(source.start_ms)}
                                    {source.end_ms !== null && ` - ${formatMs(source.end_ms)}`}]
                                  </span>
                                )}
                              </div>
                              <div style={{ color: "#444" }}>{source.content}</div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            ))}

            {loading && (
              <div style={{ display: "flex", justifyContent: "flex-start" }}>
                <div
                  style={{
                    padding: "10px 14px",
                    borderRadius: "8px",
                    backgroundColor: "#f0f0f0",
                    color: "#888",
                    fontSize: "14px",
                  }}
                >
                  Thinking...
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>

          {/* Error */}
          {error && (
            <p role="alert" style={{ color: "#cc0000", fontSize: "13px", margin: "4px 0" }}>{error}</p>
          )}

          {/* Input */}
          <form
            onSubmit={handleSend}
            style={{
              display: "flex",
              gap: "8px",
              paddingTop: "8px",
              borderTop: "1px solid #e0e0e0",
            }}
          >
            <textarea
              value={input}
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask about your meetings..."
              rows={2}
              style={{
                flex: 1,
                padding: "10px 12px",
                borderRadius: "6px",
                border: "1px solid #ccc",
                fontSize: "14px",
                resize: "none",
                fontFamily: "inherit",
              }}
            />
            <button
              type="submit"
              disabled={loading || input.trim().length === 0}
              style={{ padding: "10px 20px", alignSelf: "flex-end" }}
            >
              Send
            </button>
          </form>
        </div>
      </div>
    </section>
  );
}
