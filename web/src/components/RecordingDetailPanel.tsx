"use client";

import { useCallback, useMemo, useState } from "react";
import {
  createRecordingShareLink,
  exportRecording,
  generateSummary,
  getRecording,
} from "@/lib/api";
import type { ActionItem, RecordingDetail, Segment, Summary } from "@/lib/types";

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

function formatDate(value: string): string {
  return new Date(value).toLocaleDateString(undefined, { dateStyle: "medium" });
}

function formatError(error: unknown): string {
  if (error instanceof Error) return error.message;
  return "Unexpected error";
}

function recordingTypeLabel(type: string): string {
  return type.charAt(0).toUpperCase() + type.slice(1);
}

function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }, [text]);

  return (
    <button className="ghost-button compact-button" type="button" onClick={handleCopy}>
      {copied ? "Copied" : label}
    </button>
  );
}

type Tab = "transcript" | "summary" | "actions";
type DetailMode = "active" | "trash";

export function RecordingDetailPanel({
  recording,
  mode = "active",
  onRecordingUpdate,
  onRestore,
  onDelete,
}: {
  recording: RecordingDetail;
  mode?: DetailMode;
  onRecordingUpdate?: (r: RecordingDetail) => void;
  onRestore?: (recordingId: string) => void;
  onDelete?: (recordingId: string) => void;
}) {
  const [tab, setTab] = useState<Tab>("transcript");
  const [generating, setGenerating] = useState(false);
  const [sharing, setSharing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const tabs = useMemo(
    () =>
      [
        ["transcript", "Transcript"],
        ["summary", "Summary"],
        [
          "actions",
          recording.action_items.length > 0
            ? `Action Items (${recording.action_items.length})`
            : "Action Items",
        ],
      ] as const,
    [recording.action_items.length],
  );

  const handleGenerateSummary = async () => {
    setGenerating(true);
    setError(null);
    setNotice(null);
    try {
      await generateSummary(recording.id);
      const updated = await getRecording(recording.id);
      onRecordingUpdate?.(updated);
      setTab("summary");
      setNotice("Summary generated.");
    } catch (e) {
      setError(formatError(e));
    } finally {
      setGenerating(false);
    }
  };

  const handleExport = async (format: "markdown" | "txt" | "srt") => {
    setError(null);
    setNotice(null);
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
    } catch (e) {
      setError(formatError(e));
    }
  };

  const handleShare = async () => {
    setSharing(true);
    setError(null);
    setNotice(null);

    try {
      const link = await createRecordingShareLink(recording.id);
      const shareData = {
        title: recording.title ?? "WaiSay note",
        text: "Shared WaiSay note",
        url: link.url,
      };

      if (typeof navigator.share === "function") {
        try {
          await navigator.share(shareData);
          setNotice("Share sheet opened.");
          return;
        } catch (e) {
          if (e instanceof DOMException && e.name === "AbortError") {
            setNotice("Share canceled.");
            return;
          }
        }
      }

      if (!navigator.clipboard?.writeText) {
        throw new Error("Clipboard sharing is unavailable in this browser.");
      }
      await navigator.clipboard.writeText(link.url);
      setNotice("Share link copied.");
    } catch (e) {
      setError(formatError(e));
    } finally {
      setSharing(false);
    }
  };

  return (
    <section className="detail-panel" data-testid="recording-detail">
      <header className="detail-panel__header">
        <div className="detail-panel__title-block">
          <h2>{recording.title ?? "(untitled recording)"}</h2>
          <div className="metadata-row">
            <span className="type-dot" aria-hidden="true" />
            <span>{recordingTypeLabel(recording.type)}</span>
            <span>{formatDate(recording.created_at)}</span>
            {recording.duration_seconds ? <span>{formatDuration(recording.duration_seconds)}</span> : null}
          </div>
        </div>

        <div className="detail-panel__actions">
          {mode === "active" ? (
            <>
              <button
                className="ghost-button"
                data-testid="share-recording"
                type="button"
                onClick={handleShare}
                disabled={sharing}
              >
                {sharing ? "Sharing..." : "Share"}
              </button>
              <select
                className="select-button"
                aria-label="Export recording"
                onChange={(event) => {
                  if (event.target.value) {
                    void handleExport(event.target.value as "markdown" | "txt" | "srt");
                  }
                  event.target.value = "";
                }}
                defaultValue=""
              >
                <option value="" disabled>
                  Export
                </option>
                <option value="markdown">Markdown</option>
                <option value="txt">Plain Text</option>
                <option value="srt">SRT</option>
              </select>
              {onDelete ? (
                <button className="ghost-button danger-button" type="button" onClick={() => onDelete(recording.id)}>
                  Move to Trash
                </button>
              ) : null}
            </>
          ) : (
            <>
              <button className="ghost-button" type="button" onClick={() => onRestore?.(recording.id)}>
                Restore
              </button>
              <button className="ghost-button danger-button" type="button" onClick={() => onDelete?.(recording.id)}>
                Delete Permanently
              </button>
            </>
          )}
        </div>
      </header>

      {error ? (
        <p className="inline-alert" role="alert">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p className="inline-success" role="status">
          {notice}
        </p>
      ) : null}

      <div className="tab-strip" role="tablist" aria-label="Recording detail">
        {tabs.map(([key, label]) => (
          <button
            key={key}
            id={`recording-tab-${key}`}
            className="tab-button"
            type="button"
            role="tab"
            aria-selected={tab === key}
            aria-controls={`recording-panel-${key}`}
            tabIndex={tab === key ? 0 : -1}
            onClick={() => setTab(key)}
          >
            {label}
          </button>
        ))}
      </div>

      <div
        id={`recording-panel-${tab}`}
        className="detail-panel__content"
        role="tabpanel"
        aria-labelledby={`recording-tab-${tab}`}
      >
        {tab === "transcript" && <TranscriptTab segments={recording.segments} />}
        {tab === "summary" && (
          <SummaryTab summary={recording.summary} onGenerate={handleGenerateSummary} generating={generating} />
        )}
        {tab === "actions" && <ActionsTab items={recording.action_items} />}
      </div>
    </section>
  );
}

function TranscriptTab({ segments }: { segments: Segment[] }) {
  if (segments.length === 0) {
    return (
      <div className="empty-state">
        <h3>No Transcript</h3>
        <p>This recording does not have transcript segments yet.</p>
      </div>
    );
  }

  const fullText = segments
    .map((s) => {
      const speaker = s.speaker ?? "Speaker";
      const ts = formatTimestamp(s.start_ms);
      return `[${speaker}, ${ts}] ${s.content}`;
    })
    .join("\n");

  return (
    <div className="reading-stack">
      <div className="section-heading-row">
        <h3>Transcript</h3>
        <CopyButton text={fullText} label="Copy Transcript" />
      </div>
      {segments.map((segment) => (
        <article key={segment.id} className="transcript-row">
          <div className="metadata-row">
            {segment.speaker ? <strong>{segment.speaker}</strong> : null}
            <span className="mono">{formatTimestamp(segment.start_ms)}</span>
          </div>
          <p>{segment.content}</p>
        </article>
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
      <div className="empty-state">
        <h3>No Summary</h3>
        <p>Generate a summary to see key points and follow-ups.</p>
        <button type="button" onClick={onGenerate} disabled={generating}>
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
    <div className="reading-stack">
      <div className="section-heading-row">
        <h3>Summary</h3>
        <CopyButton text={fullSummaryText} label="Copy Summary" />
      </div>

      {summary.summary ? (
        <section className="note-section">
          <h4>Overview</h4>
          <p>{summary.summary}</p>
        </section>
      ) : null}

      {summary.key_points?.length ? (
        <section className="note-section">
          <h4>Key Points</h4>
          <ul className="reading-list">
            {summary.key_points.map((point) => (
              <li key={point}>{point}</li>
            ))}
          </ul>
        </section>
      ) : null}

      {summary.decisions?.length ? (
        <section className="note-section">
          <h4>Decisions</h4>
          <ul className="reading-list">
            {summary.decisions.map((decision, index) => (
              <li key={index}>
                <strong>{String(decision.decision ?? "")}</strong>
                {decision.context ? ` - ${String(decision.context)}` : ""}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {summary.topics?.length ? (
        <section className="note-section">
          <h4>Topics</h4>
          <p className="muted-text">{summary.topics.join(" / ")}</p>
        </section>
      ) : null}

      {summary.people_mentioned?.length ? (
        <section className="note-section">
          <h4>People</h4>
          <p className="muted-text">{summary.people_mentioned.join(", ")}</p>
        </section>
      ) : null}

      {summary.sentiment ? (
        <section className="note-section">
          <h4>Sentiment</h4>
          <span className="status-pill">{summary.sentiment}</span>
        </section>
      ) : null}
    </div>
  );
}

function ActionsTab({ items }: { items: ActionItem[] }) {
  if (items.length === 0) {
    return (
      <div className="empty-state">
        <h3>No Action Items</h3>
        <p>This note does not have extracted follow-ups yet.</p>
      </div>
    );
  }

  return (
    <div className="reading-stack">
      <div className="section-heading-row">
        <h3>Action Items</h3>
        <CopyButton
          text={items.map((item, index) => `${index + 1}. ${item.task} (${item.status})`).join("\n")}
          label="Copy Actions"
        />
      </div>

      {items.map((item) => (
        <article key={item.id} className="action-card">
          <span className={`action-card__status ${item.status === "completed" ? "is-complete" : ""}`} />
          <div>
            <p className={item.status === "completed" ? "is-complete-text" : ""}>{item.task}</p>
            <div className="metadata-row">
              {item.owner ? <span>{item.owner}</span> : null}
              {item.due_date ? <span>{item.due_date}</span> : null}
              {item.priority ? <span>{item.priority}</span> : null}
              <span>{item.status.replace("_", " ")}</span>
            </div>
          </div>
        </article>
      ))}
    </div>
  );
}
