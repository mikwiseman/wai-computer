"use client";

import { useState } from "react";
import type { SummaryAudio } from "@/lib/types";

type Locale = "en" | "ru";

const COPY: Record<
  Locale,
  {
    download: string;
    downloading: string;
    creating: string;
    create: string;
    retry: string;
    player: string;
  }
> = {
  en: {
    download: "Download audio",
    downloading: "Downloading…",
    creating: "Creating audio…",
    create: "Create audio",
    retry: "Try audio again",
    player: "Summary audio",
  },
  ru: {
    download: "Скачать аудио",
    downloading: "Скачиваем…",
    creating: "Создаём аудио…",
    create: "Создать аудио",
    retry: "Попробовать ещё раз",
    player: "Аудио-резюме",
  },
};

interface SummaryAudioControlsProps {
  state: SummaryAudio | null | undefined;
  onCreate: () => Promise<void>;
  onDownload: () => Promise<Blob>;
  filename: string;
  locale?: Locale;
}

function isActive(state: SummaryAudio | null | undefined): boolean {
  return state?.status === "queued" || state?.status === "running";
}

export function SummaryAudioControls({
  state,
  onCreate,
  onDownload,
  filename,
  locale = "en",
}: SummaryAudioControlsProps) {
  const copy = COPY[locale];
  const [busy, setBusy] = useState(false);

  const handleCreate = async () => {
    if (busy || isActive(state)) return;
    setBusy(true);
    try {
      await onCreate();
    } finally {
      setBusy(false);
    }
  };

  const handleDownload = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const blob = await onDownload();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      link.click();
      URL.revokeObjectURL(url);
    } finally {
      setBusy(false);
    }
  };

  if (state?.status === "succeeded" && state.audio_url) {
    return (
      <div className="summary-audio" data-testid="summary-audio-ready">
        <audio
          className="summary-audio__player"
          controls
          preload="none"
          src={state.audio_url}
          aria-label={copy.player}
        />
        <button
          type="button"
          className="ghost-button compact-button"
          onClick={() => void handleDownload()}
          disabled={busy}
        >
          {busy ? copy.downloading : copy.download}
        </button>
      </div>
    );
  }

  if (isActive(state)) {
    const percent = state?.progress_percent ?? 0;
    return (
      <div className="summary-audio" data-testid="summary-audio-active" role="status">
        <button type="button" className="ghost-button compact-button" disabled>
          {copy.creating}
        </button>
        <progress max={100} value={percent} aria-label={copy.creating} />
        <span className="muted-text">{percent}%</span>
      </div>
    );
  }

  return (
    <div className="summary-audio" data-testid="summary-audio-idle">
      <button
        type="button"
        className="ghost-button compact-button"
        onClick={() => void handleCreate()}
        disabled={busy}
      >
        {busy ? copy.creating : state?.status === "failed" ? copy.retry : copy.create}
      </button>
      {state?.status === "failed" && state.error_message ? (
        <span className="error-text" role="alert">
          {state.error_message}
        </span>
      ) : null}
    </div>
  );
}
