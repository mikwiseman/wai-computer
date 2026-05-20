"use client";

import { useEffect, useState } from "react";
import { exportSharedRecording, getSharedRecording } from "@/lib/api";
import type { SharedRecording } from "@/lib/types";

function formatDate(value: string): string {
  return new Date(value).toLocaleDateString(undefined, { dateStyle: "medium" });
}

function formatTimestamp(ms: number | null): string {
  if (ms === null) return "";
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

function formatDuration(seconds: number | null): string {
  if (!seconds || seconds <= 0) return "";
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  if (mins > 0 && secs > 0) return `${mins} min ${secs} sec`;
  if (mins > 0) return `${mins} min`;
  return `${secs} sec`;
}

function formatError(error: unknown): string {
  if (error instanceof Error) return error.message;
  return "Shared note unavailable.";
}

function downloadFile(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function safeFileName(title: string | null): string {
  const stem = (title ?? "shared-recording")
    .replace(/[/\\:*?"<>|\u0000-\u001f\u007f]/g, "")
    .trim()
    .replace(/\s+/g, "_")
    .slice(0, 100);
  return `${stem || "shared-recording"}.md`;
}

export function SharedRecordingClient({ token }: { token: string }) {
  const [recording, setRecording] = useState<SharedRecording | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      setError(null);
      try {
        const response = await getSharedRecording(token);
        if (!cancelled) setRecording(response);
      } catch (e) {
        if (!cancelled) setError(formatError(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [token]);

  async function handleDownloadMarkdown() {
    if (!recording) return;
    setDownloading(true);
    setDownloadError(null);
    try {
      const blob = await exportSharedRecording(token, "markdown");
      downloadFile(blob, safeFileName(recording.title));
    } catch (e) {
      setDownloadError(formatError(e));
    } finally {
      setDownloading(false);
    }
  }

  if (loading) {
    return (
      <main className="shared-page">
        <div className="shared-note">
          <p className="muted-text">Opening shared note...</p>
        </div>
      </main>
    );
  }

  if (error || !recording) {
    return (
      <main className="shared-page">
        <div className="shared-note">
          <div className="empty-state empty-state--center">
            <h1>Shared note unavailable</h1>
            <p>{error ?? "The link may have been removed."}</p>
          </div>
        </div>
      </main>
    );
  }

  return (
    <main className="shared-page">
      <article className="shared-note">
        <header className="shared-note__header">
          <div className="shared-note__topline">
            <div className="brand-block shared-note__brand">
              <div className="brand-mark" aria-hidden="true" />
              <div>
                <strong>WaiComputer</strong>
                <span>Shared note</span>
              </div>
            </div>
            <button
              type="button"
              className="ghost-button compact-button shared-note__download"
              onClick={() => void handleDownloadMarkdown()}
              disabled={downloading}
            >
              {downloading ? "Downloading..." : "Download Markdown"}
            </button>
          </div>
          <h1>{recording.title ?? "Untitled recording"}</h1>
          <div className="metadata-row">
            <span>{recording.type}</span>
            <span>{formatDate(recording.created_at)}</span>
            {recording.duration_seconds ? <span>{formatDuration(recording.duration_seconds)}</span> : null}
          </div>
          {downloadError ? (
            <p className="shared-note__download-error" role="alert">
              {downloadError}
            </p>
          ) : null}
        </header>

        {recording.summary ? (
          <section className="shared-section">
            <h2>Summary</h2>
            {recording.summary.summary ? <p>{recording.summary.summary}</p> : null}
            {recording.summary.key_points?.length ? (
              <ul className="reading-list">
                {recording.summary.key_points.map((point) => (
                  <li key={point}>{point}</li>
                ))}
              </ul>
            ) : null}
          </section>
        ) : null}

        {recording.action_items.length > 0 ? (
          <section className="shared-section">
            <h2>Action Items</h2>
            <div className="reading-stack shared-action-stack">
              {recording.action_items.map((item) => (
                <div key={item.id} className="action-card">
                  <span className={`action-card__status ${item.status === "completed" ? "is-complete" : ""}`} />
                  <div>
                    <p>{item.task}</p>
                    <div className="metadata-row">
                      <span>{item.status.replace("_", " ")}</span>
                      {item.priority ? <span>{item.priority}</span> : null}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </section>
        ) : null}

        <section className="shared-section">
          <h2>Transcript</h2>
          {recording.segments.length > 0 ? (
            <div className="reading-stack shared-transcript-stack">
              {recording.segments.map((segment) => (
                <div key={segment.id} className="transcript-row">
                  <div className="metadata-row">
                    {segment.speaker ? <strong>{segment.speaker}</strong> : null}
                    <span className="mono">{formatTimestamp(segment.start_ms)}</span>
                  </div>
                  <p>{segment.content}</p>
                </div>
              ))}
            </div>
          ) : (
            <p className="muted-text">No transcript is available for this note.</p>
          )}
        </section>
      </article>
    </main>
  );
}
