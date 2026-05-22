"use client";

import { useEffect, useState } from "react";
import { exportSharedRecording, getSharedRecording } from "@/lib/api";
import type { AuthLocale } from "@/lib/auth-locale";
import type { SharedRecording } from "@/lib/types";

const copy = {
  en: {
    opening: "Opening shared note...",
    unavailableTitle: "Shared note unavailable",
    unavailableFallback: "The link may have been removed.",
    unavailableError: "Shared note unavailable.",
    brandSubtitle: "Shared note",
    downloading: "Downloading...",
    downloadMarkdown: "Download Markdown",
    untitled: "Untitled recording",
    summary: "Summary",
    actionItems: "Action Items",
    transcript: "Transcript",
    noTranscript: "No transcript is available for this note.",
    minute: "min",
    second: "sec",
  },
  ru: {
    opening: "Открываем общую запись...",
    unavailableTitle: "Общая запись недоступна",
    unavailableFallback: "Ссылка могла быть удалена.",
    unavailableError: "Общая запись недоступна.",
    brandSubtitle: "Общая запись",
    downloading: "Скачиваем...",
    downloadMarkdown: "Скачать Markdown",
    untitled: "Запись без названия",
    summary: "Саммари",
    actionItems: "Действия",
    transcript: "Транскрипт",
    noTranscript: "Для этой записи нет транскрипта.",
    minute: "мин",
    second: "с",
  },
} as const;

const typeLabels = {
  en: { meeting: "Meeting", note: "Note", dictation: "Dictation" },
  ru: { meeting: "Встреча", note: "Заметка", dictation: "Диктовка" },
} as const;

const statusLabels = {
  en: { pending: "pending", completed: "completed" },
  ru: { pending: "в работе", completed: "готово" },
} as const;

const priorityLabels = {
  en: { low: "low", medium: "medium", high: "high", urgent: "urgent" },
  ru: { low: "низкий", medium: "средний", high: "важный", urgent: "срочно" },
} as const;

function formatDate(value: string, locale: AuthLocale): string {
  return new Date(value).toLocaleDateString(locale === "ru" ? "ru-RU" : "en-US", {
    dateStyle: "medium",
  });
}

function formatTimestamp(ms: number | null): string {
  if (ms === null) return "";
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

function formatDuration(seconds: number | null, locale: AuthLocale): string {
  if (!seconds || seconds <= 0) return "";
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  const labels = copy[locale];
  if (mins > 0 && secs > 0) return `${mins} ${labels.minute} ${secs} ${labels.second}`;
  if (mins > 0) return `${mins} ${labels.minute}`;
  return `${secs} ${labels.second}`;
}

function formatError(error: unknown, locale: AuthLocale): string {
  if (error instanceof Error) return error.message;
  return copy[locale].unavailableError;
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

export function SharedRecordingClient({
  token,
  locale = "en",
}: {
  token: string;
  locale?: AuthLocale;
}) {
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
        if (!cancelled) setError(formatError(e, locale));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [token, locale]);

  async function handleDownloadMarkdown() {
    if (!recording) return;
    setDownloading(true);
    setDownloadError(null);
    try {
      const blob = await exportSharedRecording(token, "markdown");
      downloadFile(blob, safeFileName(recording.title));
    } catch (e) {
      setDownloadError(formatError(e, locale));
    } finally {
      setDownloading(false);
    }
  }

  const labels = copy[locale];
  const typeLabel =
    recording && recording.type in typeLabels[locale]
      ? typeLabels[locale][recording.type as keyof typeof typeLabels.en]
      : recording?.type;

  if (loading) {
    return (
      <main className="shared-page">
        <div className="shared-note">
          <p className="muted-text">{labels.opening}</p>
        </div>
      </main>
    );
  }

  if (error || !recording) {
    return (
      <main className="shared-page">
        <div className="shared-note">
          <div className="empty-state empty-state--center">
            <h1>{labels.unavailableTitle}</h1>
            <p>{error ?? labels.unavailableFallback}</p>
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
                <span>{labels.brandSubtitle}</span>
              </div>
            </div>
            <button
              type="button"
              className="ghost-button compact-button shared-note__download"
              onClick={() => void handleDownloadMarkdown()}
              disabled={downloading}
            >
              {downloading ? labels.downloading : labels.downloadMarkdown}
            </button>
          </div>
          <h1>{recording.title ?? labels.untitled}</h1>
          <div className="metadata-row">
            <span>{typeLabel}</span>
            <span>{formatDate(recording.created_at, locale)}</span>
            {recording.duration_seconds ? (
              <span>{formatDuration(recording.duration_seconds, locale)}</span>
            ) : null}
          </div>
          {downloadError ? (
            <p className="shared-note__download-error" role="alert">
              {downloadError}
            </p>
          ) : null}
        </header>

        {recording.summary ? (
          <section className="shared-section">
            <h2>{labels.summary}</h2>
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
            <h2>{labels.actionItems}</h2>
            <div className="reading-stack shared-action-stack">
              {recording.action_items.map((item) => (
                <div key={item.id} className="action-card">
                  <span className={`action-card__status ${item.status === "completed" ? "is-complete" : ""}`} />
                  <div>
                    <p>{item.task}</p>
                    <div className="metadata-row">
                      <span>
                        {item.status in statusLabels[locale]
                          ? statusLabels[locale][item.status as keyof typeof statusLabels.en]
                          : item.status.replace("_", " ")}
                      </span>
                      {item.priority ? (
                        <span>
                          {item.priority in priorityLabels[locale]
                            ? priorityLabels[locale][item.priority as keyof typeof priorityLabels.en]
                            : item.priority}
                        </span>
                      ) : null}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </section>
        ) : null}

        <section className="shared-section">
          <h2>{labels.transcript}</h2>
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
            <p className="muted-text">{labels.noTranscript}</p>
          )}
        </section>
      </article>
    </main>
  );
}
