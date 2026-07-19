"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { exportSharedRecording, getSharedRecording } from "@/lib/api";
import type { AuthLocale } from "@/lib/auth-locale";
import { formatDurationClock, stripInlineCodeMarkdown } from "@/lib/format";
import { mergeTurns } from "@/lib/transcript";
import { SummaryMarkdown, renderSummaryInline } from "@/components/SummaryMarkdown";
import { ThemeToggle } from "@/components/ThemeToggle";
import type { SharedRecording } from "@/lib/types";

const copy = {
  en: {
    opening: "Opening shared note…",
    unavailableTitle: "Shared note unavailable",
    unavailableFallback: "This link may have been removed or expired. Ask the sender for a new one.",
    unavailableError: "Shared note unavailable.",
    brandSubtitle: "Shared note",
    downloading: "Downloading…",
    downloadMarkdown: "Download Markdown",
    untitled: "Untitled recording",
    summary: "Summary",
    keyPoints: "Key points",
    actionItems: "Action items",
    keyMoments: "Key moments",
    transcript: "Transcript",
    noTranscript: "No transcript is available for this note.",
    dueLabel: "due",
    minute: "min",
    second: "sec",
    ctaTagline: "Capture every meeting, dictation and idea.",
    ctaLink: "Try WaiComputer free →",
    homeLink: "wai.computer",
  },
  ru: {
    opening: "Открываем общую запись…",
    unavailableTitle: "Общая запись недоступна",
    unavailableFallback: "Ссылка могла быть удалена или устарела. Попросите отправителя поделиться заново.",
    unavailableError: "Общая запись недоступна.",
    brandSubtitle: "Общая запись",
    downloading: "Скачиваем…",
    downloadMarkdown: "Скачать Markdown",
    untitled: "Запись без названия",
    summary: "Саммари",
    keyPoints: "Ключевые пункты",
    actionItems: "Задачи",
    keyMoments: "Ключевые моменты",
    transcript: "Транскрипт",
    noTranscript: "Для этой записи нет транскрипта.",
    dueLabel: "срок",
    minute: "мин",
    second: "с",
    ctaTagline: "Сохраняйте все встречи, диктовки и идеи.",
    ctaLink: "Попробуйте WaiComputer бесплатно →",
    homeLink: "wai.computer",
  },
} as const;

const typeLabels = {
  en: { meeting: "Meeting", note: "Note", dictation: "Dictation" },
  ru: { meeting: "Встреча", note: "Заметка", dictation: "Диктовка" },
} as const;

function formatDate(value: string, locale: AuthLocale): string {
  return new Date(value).toLocaleDateString(locale === "ru" ? "ru-RU" : "en-US", {
    dateStyle: "medium",
  });
}

function formatTimestamp(ms: number | null): string {
  if (ms === null) return "";
  return formatDurationClock(Math.floor(ms / 1000)) || "0:00";
}



function formatError(error: unknown, locale: AuthLocale): string {
  const labels = copy[locale];
  if (error instanceof Error) {
    // The backend's terse "not found" would only repeat the page title —
    // surface the actionable explanation instead.
    if (/not found/i.test(error.message)) return labels.unavailableFallback;
    return error.message;
  }
  return labels.unavailableError;
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
    .replace(/[/\\:*?"<>|\x00-\x1f\x7f]/g, "")
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
  const homeHref = locale === "ru" ? "/ru" : "/";
  const typeLabel =
    recording && recording.type in typeLabels[locale]
      ? typeLabels[locale][recording.type as keyof typeof typeLabels.en]
      : recording?.type;

  // A long meeting shares thousands of raw utterances; rendering one row per
  // utterance froze this page. Merge them into readable turns once (same view
  // the dashboard uses) and strip markdown per utterance before merging so the
  // join can't pair backticks across utterances.
  const transcriptTurns = useMemo(() => {
    if (!recording) return [];
    const stripped = recording.segments.map((segment) => ({
      ...segment,
      content: stripInlineCodeMarkdown(segment.content),
    }));
    return mergeTurns(stripped, locale);
  }, [recording, locale]);

  const sortedHighlights = useMemo(
    () =>
      recording
        ? [...recording.highlights].sort((a, b) => (a.start_ms ?? 0) - (b.start_ms ?? 0))
        : [],
    [recording],
  );

  if (loading) {
    return (
      <main id="main" className="shared-page">
        <div className="shared-note">
          <p className="muted-text" role="status">{labels.opening}</p>
        </div>
      </main>
    );
  }

  if (error || !recording) {
    return (
      <main id="main" className="shared-page">
        <div className="shared-note">
          <div className="empty-state empty-state--center">
            <h1>{labels.unavailableTitle}</h1>
            <p>{error ?? labels.unavailableFallback}</p>
          </div>
        </div>
        <SharedFooterCta locale={locale} homeHref={homeHref} />
      </main>
    );
  }

  return (
    <main id="main" className="shared-page">
      <article className="shared-note">
        <header className="shared-note__header">
          <div className="shared-note__topline">
            <Link
              href={homeHref}
              className="brand-block shared-note__brand"
              aria-label="WaiComputer"
            >
              <div className="brand-mark" aria-hidden="true" />
              <div>
                <strong>WaiComputer</strong>
                <span>{labels.brandSubtitle}</span>
              </div>
            </Link>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: "var(--space-sm)",
              }}
            >
              <ThemeToggle locale={locale} />
              <button
                type="button"
                className="ghost-button compact-button shared-note__download"
                onClick={() => void handleDownloadMarkdown()}
                disabled={downloading}
              >
                {downloading ? labels.downloading : labels.downloadMarkdown}
              </button>
            </div>
          </div>
          <h1>{recording.title ?? labels.untitled}</h1>
          <div className="metadata-row">
            <span>{typeLabel}</span>
            <span>{formatDate(recording.created_at, locale)}</span>
            {recording.duration_seconds ? (
              <span>{formatDurationClock(recording.duration_seconds)}</span>
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
            {recording.summary.summary ? (
              <SummaryMarkdown text={recording.summary.summary} />
            ) : null}
            {recording.summary.key_points?.length ? (
              <>
                <h3 className="shared-subheading">{labels.keyPoints}</h3>
                <ul className="reading-list">
                  {recording.summary.key_points.map((point) => (
                    <li key={point}>{renderSummaryInline(point, point)}</li>
                  ))}
                </ul>
              </>
            ) : null}
          </section>
        ) : null}

        {recording.action_items.length > 0 ? (
          <section className="shared-section">
            <h2>{labels.actionItems}</h2>
            <ul className="reading-list shared-action-items">
              {recording.action_items.map((item) => (
                <li key={item.id}>
                  <span aria-hidden="true">☐ </span>
                  {renderSummaryInline(item.task, item.id)}
                  {item.owner ? <strong> — {item.owner}</strong> : null}
                  {item.due_date ? (
                    <span className="muted-text">
                      {" "}
                      · {labels.dueLabel} {formatDate(item.due_date, locale)}
                    </span>
                  ) : null}
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {recording.highlights.length > 0 ? (
          <section className="shared-section">
            <h2>{labels.keyMoments}</h2>
            <div className="reading-stack">
              {sortedHighlights.map((highlight) => (
                  <div key={highlight.id} className="transcript-row">
                    <div className="metadata-row">
                      {highlight.start_ms !== null ? (
                        <span className="mono">{formatTimestamp(highlight.start_ms)}</span>
                      ) : null}
                      <strong>{renderSummaryInline(highlight.title, highlight.id)}</strong>
                    </div>
                    {highlight.description ? (
                      <p>{renderSummaryInline(highlight.description, `${highlight.id}-d`)}</p>
                    ) : null}
                  </div>
                ))}
            </div>
          </section>
        ) : null}

        <section className="shared-section">
          <h2>{labels.transcript}</h2>
          {transcriptTurns.length > 0 ? (
            <div className="reading-stack shared-transcript-stack">
              {transcriptTurns.map((turn) => (
                <div key={turn.segments[0]?.id ?? turn.key} className="transcript-row">
                  <div className="metadata-row">
                    <strong>{turn.speaker}</strong>
                    <span className="mono">{formatTimestamp(turn.startMs)}</span>
                  </div>
                  <p>{turn.text}</p>
                </div>
              ))}
            </div>
          ) : (
            <p className="muted-text">{labels.noTranscript}</p>
          )}
        </section>
      </article>
      <SharedFooterCta locale={locale} homeHref={homeHref} />
    </main>
  );
}

function SharedFooterCta({
  locale,
  homeHref,
}: {
  locale: AuthLocale;
  homeHref: string;
}) {
  const labels = copy[locale];
  return (
    <footer role="contentinfo" className="shared-footer">
      <p style={{ color: "var(--ink-soft)", margin: 0 }}>{labels.ctaTagline}</p>
      <Link href={homeHref} className="primary-button" data-testid="shared-cta">
        {labels.ctaLink}
      </Link>
    </footer>
  );
}
