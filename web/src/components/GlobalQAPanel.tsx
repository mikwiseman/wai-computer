"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { askDatabase } from "@/lib/api";
import { ApiError } from "@/lib/http";
import type { QASource, Recording } from "@/lib/types";

interface GlobalQAPanelProps {
  recordings: Recording[];
}

function formatError(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Unexpected error";
}

function formatMs(ms: number | null): string {
  if (ms === null) return "";
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

export function GlobalQAPanel({ recordings }: GlobalQAPanelProps) {
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [selectedRecordingIds, setSelectedRecordingIds] = useState<string[]>([]);
  const [showSources, setShowSources] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [answer, setAnswer] = useState<string | null>(null);
  const [sources, setSources] = useState<QASource[]>([]);

  const answerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (answer) {
      answerRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [answer]);

  async function handleSend(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const question = input.trim();
    if (question.length === 0 || loading) return;

    setError(null);
    setAnswer(null);
    setSources([]);
    setLoading(true);

    try {
      const response = await askDatabase({
        question,
        recording_ids: selectedRecordingIds.length > 0 ? selectedRecordingIds : null,
      });

      setAnswer(response.answer);
      setSources(response.sources || []);
      setInput("");
      setShowSources(false);
    } catch (err: unknown) {
      setError(formatError(err));
    } finally {
      setLoading(false);
    }
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
      if (form) form.requestSubmit();
    }
  }

  return (
    <section className="card stack">
      <h2>Ask Your Database</h2>

      <div style={{ display: "flex", flexDirection: "column", gap: "16px", minHeight: "400px" }}>
        {/* Scope selector */}
        {recordings.length > 0 && (
          <div
            style={{
              display: "flex",
              gap: "6px",
              flexWrap: "wrap",
              paddingBottom: "8px",
              borderBottom: "1px solid #e0e0e0",
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

        {/* Output area */}
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
          {!answer && !loading && (
            <p style={{ color: "#888", textAlign: "center", marginTop: "40px" }}>
              Ask a question about any of your recordings and notes.
            </p>
          )}

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
                Searching database...
              </div>
            </div>
          )}

          {answer && (
            <div ref={answerRef} style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
              <div
                style={{
                  padding: "16px",
                  borderRadius: "8px",
                  backgroundColor: "#f9f9f9",
                  color: "#222",
                  fontSize: "15px",
                  lineHeight: "1.6",
                  whiteSpace: "pre-wrap",
                  borderLeft: "4px solid #0066cc"
                }}
              >
                {answer}
              </div>

              {sources.length > 0 && (
                <div>
                  <button
                    type="button"
                    onClick={() => setShowSources(!showSources)}
                    style={{
                      background: "none",
                      border: "none",
                      cursor: "pointer",
                      fontSize: "13px",
                      color: "#0066cc",
                      padding: 0,
                    }}
                  >
                    {showSources ? "Hide sources" : `Show sources (${sources.length})`}
                  </button>

                  {showSources && (
                    <div
                      style={{
                        marginTop: "10px",
                        display: "flex",
                        flexDirection: "column",
                        gap: "8px",
                      }}
                    >
                      {sources.map((source, idx) => (
                        <div
                          key={`${source.segment_id}-${idx}`}
                          style={{
                            padding: "10px",
                            backgroundColor: "#f0f0f0",
                            borderRadius: "6px",
                            fontSize: "13px",
                          }}
                        >
                          <div style={{ fontWeight: 600, marginBottom: "4px" }}>
                            {source.recording_title ?? "Untitled recording"}
                            {source.speaker && ` - ${source.speaker}`}
                            {source.start_ms !== null && (
                              <span style={{ color: "#666", marginLeft: "6px" }}>
                                [{formatMs(source.start_ms)}
                                {source.end_ms !== null && ` - ${formatMs(source.end_ms)}`}]
                              </span>
                            )}
                          </div>
                          <div style={{ color: "#444", lineHeight: "1.4" }}>{source.content}</div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {error && (
            <p role="alert" style={{ color: "#cc0000", fontSize: "14px", margin: "4px 0" }}>
              {error}
            </p>
          )}
        </div>

        {/* Input */}
        <form
          onSubmit={handleSend}
          style={{
            display: "flex",
            gap: "8px",
            paddingTop: "12px",
            borderTop: "1px solid #e0e0e0",
          }}
        >
          <textarea
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about your recordings..."
            rows={3}
            style={{
              flex: 1,
              padding: "12px",
              borderRadius: "6px",
              border: "1px solid #ccc",
              fontSize: "15px",
              resize: "none",
              fontFamily: "inherit",
            }}
          />
          <button
            type="submit"
            disabled={loading || input.trim().length === 0}
            style={{ padding: "10px 24px", alignSelf: "flex-end", fontWeight: "bold" }}
          >
            Ask
          </button>
        </form>
      </div>
    </section>
  );
}
