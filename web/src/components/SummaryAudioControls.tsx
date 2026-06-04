"use client";

import { useState } from "react";
import type { SummaryAudio } from "@/lib/types";

interface SummaryAudioControlsProps {
  state: SummaryAudio | null | undefined;
  onCreate: () => Promise<void>;
  onDownload: () => Promise<Blob>;
  filename: string;
}

function isActive(state: SummaryAudio | null | undefined): boolean {
  return state?.status === "queued" || state?.status === "running";
}

export function SummaryAudioControls({
  state,
  onCreate,
  onDownload,
  filename,
}: SummaryAudioControlsProps) {
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
        <audio className="summary-audio__player" controls preload="none" src={state.audio_url} />
        <button
          type="button"
          className="ghost-button compact-button"
          onClick={() => void handleDownload()}
          disabled={busy}
        >
          {busy ? "Downloading…" : "Download audio"}
        </button>
      </div>
    );
  }

  if (isActive(state)) {
    return (
      <div className="summary-audio" data-testid="summary-audio-active">
        <button type="button" className="ghost-button compact-button" disabled>
          Creating audio…
        </button>
        <span className="muted-text">{state?.progress_percent ?? 0}%</span>
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
        {busy ? "Creating audio…" : state?.status === "failed" ? "Try audio again" : "Create audio"}
      </button>
      {state?.status === "failed" && state.error_message ? (
        <span className="error-text">{state.error_message}</span>
      ) : null}
    </div>
  );
}
