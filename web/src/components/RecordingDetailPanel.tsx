"use client";

import { useState, useCallback } from "react";
import { exportRecording, generateSummary, getRecording } from "@/lib/api";
import type { RecordingDetail, Segment, Summary, ActionItem } from "@/lib/types";

function formatTimestamp(ms: number | null): string {
  if (ms === null) return "";
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const secs = totalSeconds % 60;
  return `${minutes}:${secs.toString().padStart(2, "0")}`;
}

function formatDuration(seconds: number | null): string {
  if (!seconds || seconds <= 0) return "";
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

function CopyButton({ text, label }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }, [text]);

  return (
    <button
      type="button"
      onClick={handleCopy}
      title={copied ? "Copied!" : label ?? "Copy"}
      style={{
        background: "none",
        border: "none",
        cursor: "pointer",
        padding: "2px 6px",
        fontSize: "0.8rem",
        color: copied ? "var(--accent, #d18a30)" : "var(--text-secondary, #888)",
        transition: "color 0.2s",
      }}
    >
      {copied ? "\u2713" : "\u2398"}
    </button>
  );
}

type Tab = "transcript" | "summary" | "actions";

export function RecordingDetailPanel({
  recording,
  onRecordingUpdate,
}: {
  recording: RecordingDetail;
  onRecordingUpdate?: (r: RecordingDetail) => void;
}) {
  const [tab, setTab] = useState<Tab>("transcript");
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleGenerateSummary = async () => {
    setGenerating(true);
    setError(null);
    try {
      await generateSummary(recording.id);
      const updated = await getRecording(recording.id);
      onRecordingUpdate?.(updated);
      setTab("summary");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to generate summary");
    } finally {
      setGenerating(false);
    }
  };

  const handleExport = async (format: "markdown" | "txt" | "srt") => {
    try {
      const blob = await exportRecording(recording.id, format);
      const url = URL.createObjectURL(blob);
      const ext = format === "markdown" ? "md" : format;
      const title = recording.title ?? "recording";
      const a = document.createElement("a");
      a.href = url;
      a.download = `${title.replace(/[/\\]/g, "_")}.${ext}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      setError("Export failed");
    }
  };

  return (
    <section className="card stack" data-testid="recording-detail" style={{ flex: 1 }}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <h2 style={{ margin: 0 }}>{recording.title ?? "(untitled recording)"}</h2>
          <div
            style={{
              display: "flex",
              gap: "0.75rem",
              fontSize: "0.85rem",
              color: "var(--text-secondary, #888)",
              marginTop: "0.25rem",
            }}
          >
            <span style={{ textTransform: "capitalize" }}>{recording.type}</span>
            <span>{new Date(recording.created_at).toLocaleDateString(undefined, { dateStyle: "medium" })}</span>
            {recording.duration_seconds ? <span>{formatDuration(recording.duration_seconds)}</span> : null}
          </div>
        </div>
        <div style={{ display: "flex", gap: "0.5rem" }}>
          <select
            onChange={(e) => {
              if (e.target.value) handleExport(e.target.value as "markdown" | "txt" | "srt");
              e.target.value = "";
            }}
            defaultValue=""
            style={{ fontSize: "0.8rem", padding: "2px 4px" }}
          >
            <option value="" disabled>
              Export...
            </option>
            <option value="markdown">Markdown</option>
            <option value="txt">Plain Text</option>
            <option value="srt">SRT</option>
          </select>
        </div>
      </div>

      {error && <p style={{ color: "var(--error, red)", fontSize: "0.85rem" }}>{error}</p>}

      {/* Tabs */}
      <div
        style={{
          display: "flex",
          gap: "2rem",
          borderBottom: "1px solid var(--border, #333)",
          paddingBottom: "1rem",
        }}
      >
        {(["transcript", "summary", "actions"] as Tab[]).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            style={{
              background: "none",
              border: "none",
              cursor: "pointer",
              padding: "0.5rem 0",
              fontSize: "0.9rem",
              fontWeight: tab === t ? 600 : 400,
              color: tab === t ? "var(--accent, #d18a30)" : "var(--text-secondary, #888)",
              borderBottom: tab === t ? "2px solid var(--accent, #d18a30)" : "2px solid transparent",
            }}
          >
            {t === "actions"
              ? `Action Items${recording.action_items.length > 0 ? ` (${recording.action_items.length})` : ""}`
              : t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      <div style={{ flex: 1, overflow: "auto", maxHeight: "60vh" }}>
        {tab === "transcript" && <TranscriptTab segments={recording.segments} />}
        {tab === "summary" && (
          <SummaryTab
            summary={recording.summary}
            onGenerate={handleGenerateSummary}
            generating={generating}
          />
        )}
        {tab === "actions" && <ActionsTab items={recording.action_items} />}
      </div>
    </section>
  );
}

function TranscriptTab({ segments }: { segments: Segment[] }) {
  if (segments.length === 0) {
    return <p style={{ color: "var(--text-secondary, #888)" }}>No transcript segments.</p>;
  }

  const fullText = segments
    .map((s) => {
      const speaker = s.speaker ?? "Speaker";
      const ts = formatTimestamp(s.start_ms);
      return `[${speaker}, ${ts}] ${s.content}`;
    })
    .join("\n");

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: "0.5rem" }}>
        <CopyButton text={fullText} label="Copy Transcript" />
      </div>
      {segments.map((segment) => (
        <div key={segment.id} style={{ marginBottom: "1rem" }}>
          <div style={{ display: "flex", gap: "0.5rem", fontSize: "0.8rem", marginBottom: "0.25rem" }}>
            {segment.speaker && (
              <span style={{ fontWeight: 600, color: "var(--accent, #d18a30)" }}>{segment.speaker}</span>
            )}
            <span style={{ color: "var(--text-secondary, #888)", fontFamily: "monospace" }}>
              {formatTimestamp(segment.start_ms)}
            </span>
          </div>
          <p style={{ margin: 0, lineHeight: 1.6 }}>{segment.content}</p>
        </div>
      ))}
    </div>
  );
}

function SummaryTab({
  summary,
  onGenerate,
  generating,
}: {
  summary: Summary | null;
  onGenerate: () => void;
  generating: boolean;
}) {
  if (!summary) {
    return (
      <div style={{ textAlign: "center", padding: "2rem" }}>
        <p style={{ color: "var(--text-secondary, #888)" }}>No summary generated yet.</p>
        <button type="button" onClick={onGenerate} disabled={generating} style={{ marginTop: "0.5rem" }}>
          {generating ? "Generating..." : "Generate Summary"}
        </button>
      </div>
    );
  }

  const fullSummaryText = [
    summary.summary,
    summary.key_points?.length ? "\nKey Points:\n" + summary.key_points.map((p) => `- ${p}`).join("\n") : null,
    summary.topics?.length ? "\nTopics: " + summary.topics.join(", ") : null,
    summary.people_mentioned?.length ? "\nPeople: " + summary.people_mentioned.join(", ") : null,
  ]
    .filter(Boolean)
    .join("\n");

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: "0.5rem" }}>
        <CopyButton text={fullSummaryText} label="Copy All" />
      </div>

      {summary.summary && (
        <div style={{ marginBottom: "1.25rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <h4 style={{ margin: "0 0 0.25rem 0" }}>Summary</h4>
            <CopyButton text={summary.summary} label="Copy Summary" />
          </div>
          <p style={{ margin: 0, lineHeight: 1.6 }}>{summary.summary}</p>
        </div>
      )}

      {summary.key_points && summary.key_points.length > 0 && (
        <div style={{ marginBottom: "1.25rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <h4 style={{ margin: "0 0 0.25rem 0" }}>Key Points</h4>
            <CopyButton text={summary.key_points.map((p) => `- ${p}`).join("\n")} label="Copy Key Points" />
          </div>
          <ul style={{ margin: 0, paddingLeft: "1.25rem" }}>
            {summary.key_points.map((point, i) => (
              <li key={i} style={{ lineHeight: 1.6 }}>
                {point}
              </li>
            ))}
          </ul>
        </div>
      )}

      {summary.decisions && summary.decisions.length > 0 && (
        <div style={{ marginBottom: "1.25rem" }}>
          <h4 style={{ margin: "0 0 0.25rem 0" }}>Decisions</h4>
          <ul style={{ margin: 0, paddingLeft: "1.25rem" }}>
            {summary.decisions.map((d, i) => (
              <li key={i} style={{ lineHeight: 1.6 }}>
                <strong>{String(d.decision ?? "")}</strong>
                {d.context ? ` — ${String(d.context)}` : ""}
              </li>
            ))}
          </ul>
        </div>
      )}

      {summary.topics && summary.topics.length > 0 && (
        <div style={{ marginBottom: "1.25rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <h4 style={{ margin: "0 0 0.25rem 0" }}>Topics</h4>
            <CopyButton text={summary.topics.join(", ")} label="Copy Topics" />
          </div>
          <p style={{ margin: 0, color: "var(--text-secondary, #888)" }}>
            {summary.topics.join(" \u00B7 ")}
          </p>
        </div>
      )}

      {summary.people_mentioned && summary.people_mentioned.length > 0 && (
        <div style={{ marginBottom: "1.25rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <h4 style={{ margin: "0 0 0.25rem 0" }}>People</h4>
            <CopyButton text={summary.people_mentioned.join(", ")} label="Copy People" />
          </div>
          <p style={{ margin: 0, color: "var(--text-secondary, #888)" }}>
            {summary.people_mentioned.join(", ")}
          </p>
        </div>
      )}

      {summary.sentiment && (
        <div>
          <h4 style={{ margin: "0 0 0.25rem 0" }}>Sentiment</h4>
          <span
            style={{
              textTransform: "capitalize",
              fontSize: "0.85rem",
              padding: "2px 8px",
              borderRadius: "4px",
              background: "var(--surface-subtle, #222)",
            }}
          >
            {summary.sentiment}
          </span>
        </div>
      )}
    </div>
  );
}

function ActionsTab({ items }: { items: ActionItem[] }) {
  if (items.length === 0) {
    return <p style={{ color: "var(--text-secondary, #888)" }}>No action items.</p>;
  }

  return (
    <div>
      {items.map((item) => (
        <div
          key={item.id}
          style={{
            padding: "1.25rem",
            marginBottom: "1rem",
            borderRadius: "6px",
            background: "var(--surface-subtle, #222)",
          }}
        >
          <div style={{ display: "flex", alignItems: "flex-start", gap: "1rem" }}>
            <span style={{ fontSize: "1.1rem" }}>
              {item.status === "completed" ? "\u2705" : "\u25CB"}
            </span>
            <div style={{ flex: 1 }}>
              <p
                style={{
                  margin: 0,
                  textDecoration: item.status === "completed" ? "line-through" : "none",
                  color: item.status === "completed" ? "var(--text-secondary, #888)" : "inherit",
                }}
              >
                {item.task}
              </p>
              <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.25rem", fontSize: "0.8rem" }}>
                {item.owner && (
                  <span style={{ color: "var(--text-secondary, #888)" }}>{item.owner}</span>
                )}
                {item.priority && (
                  <span
                    style={{
                      padding: "1px 6px",
                      borderRadius: "3px",
                      background:
                        item.priority === "high"
                          ? "rgba(239,68,68,0.15)"
                          : item.priority === "medium"
                            ? "rgba(245,158,11,0.15)"
                            : "rgba(156,163,175,0.15)",
                      color:
                        item.priority === "high"
                          ? "#ef4444"
                          : item.priority === "medium"
                            ? "#f59e0b"
                            : "#9ca3af",
                    }}
                  >
                    {item.priority}
                  </span>
                )}
                {item.due_date && (
                  <span style={{ color: "var(--text-secondary, #888)" }}>{item.due_date}</span>
                )}
              </div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

