"use client";

import { FormEvent, KeyboardEvent, useEffect, useRef, useState } from "react";
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

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      event.currentTarget.closest("form")?.requestSubmit();
    }
  }

  return (
    <section className="qa-panel">
      <header className="qa-panel__header">
        <h2>Ask Wai</h2>
        <p>{recordings.length} {recordings.length === 1 ? "recording" : "recordings"}</p>
      </header>

      {recordings.length > 0 ? (
        <div className="qa-scope" aria-label="Question scope">
          <span>Scope</span>
          {recordings.map((rec) => (
            <label key={rec.id} className="scope-chip">
              <input
                type="checkbox"
                checked={selectedRecordingIds.includes(rec.id)}
                onChange={() => handleRecordingToggle(rec.id)}
              />
              {rec.title ?? "(untitled)"}
            </label>
          ))}
        </div>
      ) : null}

      <div className="qa-output">
        {!answer && !loading ? (
          <div className="empty-state empty-state--center">
            <h3>No answer yet</h3>
          </div>
        ) : null}

        {loading ? <div className="qa-bubble qa-bubble--loading">Searching database...</div> : null}

        {answer ? (
          <div ref={answerRef} className="qa-answer">
            <div className="qa-bubble">{answer}</div>

            {sources.length > 0 ? (
              <div className="qa-sources">
                <button
                  type="button"
                  className="ghost-button compact-button"
                  onClick={() => setShowSources(!showSources)}
                >
                  {showSources ? "Hide sources" : `Show sources (${sources.length})`}
                </button>

                {showSources ? (
                  <div className="source-list">
                    {sources.map((source, idx) => (
                      <article key={`${source.segment_id}-${idx}`} className="source-card">
                        <h3>
                          {source.recording_title ?? "Untitled recording"}
                          {source.speaker ? ` - ${source.speaker}` : ""}
                          {source.start_ms !== null ? (
                            <span>
                              {" "}
                              [{formatMs(source.start_ms)}
                              {source.end_ms !== null ? ` - ${formatMs(source.end_ms)}` : ""}]
                            </span>
                          ) : null}
                        </h3>
                        <p>{source.content}</p>
                      </article>
                    ))}
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>
        ) : null}

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
          placeholder="Ask about your recordings..."
          rows={3}
        />
        <button type="submit" disabled={loading || input.trim().length === 0}>
          Ask
        </button>
      </form>
    </section>
  );
}
