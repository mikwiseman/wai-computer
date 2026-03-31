"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { sendAgentMessage } from "@/lib/api";
import { ApiError } from "@/lib/http";

interface AgentMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  intent?: string;
  toolCalls?: number;
  loading?: boolean;
}

function formatError(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Unexpected error";
}

export function AgentChat() {
  const [messages, setMessages] = useState<AgentMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [sessionId, setSessionId] = useState<string | undefined>();
  const [error, setError] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || loading) return;

    setInput("");
    setError(null);

    const userMsg: AgentMessage = {
      id: `user-${Date.now()}`,
      role: "user",
      content: text,
    };
    const loadingMsg: AgentMessage = {
      id: `loading-${Date.now()}`,
      role: "assistant",
      content: "",
      loading: true,
    };
    setMessages((prev) => [...prev, userMsg, loadingMsg]);
    setLoading(true);

    try {
      const result = await sendAgentMessage(text, sessionId);
      setSessionId(result.session_id);

      const assistantMsg: AgentMessage = {
        id: `assistant-${Date.now()}`,
        role: "assistant",
        content: result.response,
        intent: result.intent,
        toolCalls: result.tool_calls,
      };
      setMessages((prev) =>
        prev.filter((m) => !m.loading).concat(assistantMsg)
      );
    } catch (err) {
      setMessages((prev) => prev.filter((m) => !m.loading));
      setError(formatError(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      {/* Messages */}
      <div
        style={{
          flex: 1,
          overflowY: "auto",
          padding: "1.5rem",
          display: "flex",
          flexDirection: "column",
          gap: "1rem",
        }}
      >
        {messages.length === 0 && (
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
              flex: 1,
              gap: "1.5rem",
              color: "var(--muted)",
            }}
          >
            <div style={{ fontSize: "2.5rem" }}>🧠</div>
            <div style={{ fontSize: "1.1rem", fontWeight: 500 }}>
              What can I help with?
            </div>
            <div
              style={{
                display: "flex",
                gap: "0.5rem",
                flexWrap: "wrap",
                justifyContent: "center",
              }}
            >
              {[
                "Find what Alex said about pricing",
                "Create a habit tracker",
                "Build a landing page",
                "What are my commitments?",
              ].map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  onClick={() => {
                    setInput(suggestion);
                    inputRef.current?.focus();
                  }}
                  style={{
                    padding: "0.4rem 0.8rem",
                    borderRadius: "20px",
                    border: "1px solid var(--border)",
                    background: "var(--card)",
                    cursor: "pointer",
                    fontSize: "0.85rem",
                    color: "var(--ink)",
                  }}
                >
                  {suggestion}
                </button>
              ))}
            </div>
          </div>
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
                maxWidth: "80%",
                padding: "0.75rem 1rem",
                borderRadius: "12px",
                background:
                  msg.role === "user" ? "var(--accent)" : "var(--card)",
                color: msg.role === "user" ? "#fff" : "var(--ink)",
                border:
                  msg.role === "assistant"
                    ? "1px solid var(--border)"
                    : "none",
                whiteSpace: "pre-wrap",
                lineHeight: 1.5,
                fontSize: "0.95rem",
              }}
            >
              {msg.loading ? (
                <span style={{ color: "var(--muted)", fontStyle: "italic" }}>
                  Thinking...
                </span>
              ) : (
                msg.content
              )}
              {msg.intent && !msg.loading && (
                <div
                  style={{
                    marginTop: "0.5rem",
                    fontSize: "0.75rem",
                    color: "var(--muted)",
                    display: "flex",
                    gap: "0.5rem",
                  }}
                >
                  <span>{msg.intent}</span>
                  {msg.toolCalls ? (
                    <span>{msg.toolCalls} tool calls</span>
                  ) : null}
                </div>
              )}
            </div>
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* Error */}
      {error && (
        <div
          style={{
            padding: "0.5rem 1rem",
            background: "#fef2f2",
            color: "#dc2626",
            fontSize: "0.85rem",
          }}
        >
          {error}
        </div>
      )}

      {/* Input */}
      <form
        onSubmit={handleSubmit}
        style={{
          padding: "1rem 1.5rem",
          borderTop: "1px solid var(--border)",
          display: "flex",
          gap: "0.5rem",
        }}
      >
        <input
          ref={inputRef}
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Say or type what you need..."
          disabled={loading}
          style={{ flex: 1 }}
          data-testid="agent-chat-input"
        />
        <button type="submit" disabled={loading || !input.trim()}>
          {loading ? "..." : "Send"}
        </button>
      </form>
    </div>
  );
}
