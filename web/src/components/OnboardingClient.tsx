"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { enrollVoice } from "@/lib/api";

const PROMPT_TEXT =
  "Hi, I'm setting up Wai Computer. It records meetings, calls, and ideas through my day so I don't have to remember them all. Wai listens, transcribes the people I talk to, and keeps the moments that matter.";

const MAX_DURATION_S = 20;
const STORAGE_KEY = "voice_onboarding_complete";

type RecorderState = "idle" | "recording" | "recorded" | "uploading";

export function OnboardingClient() {
  const router = useRouter();
  const [state, setState] = useState<RecorderState>("idle");
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [audioBlob, setAudioBlob] = useState<Blob | null>(null);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const startedAtRef = useRef<number>(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    return () => {
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  function stopStream() {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
  }

  function pickMimeType(): { mimeType: string; filename: string } {
    if (typeof MediaRecorder !== "undefined") {
      if (MediaRecorder.isTypeSupported("audio/webm;codecs=opus")) {
        return { mimeType: "audio/webm;codecs=opus", filename: "enrollment.webm" };
      }
      if (MediaRecorder.isTypeSupported("audio/mp4")) {
        return { mimeType: "audio/mp4", filename: "enrollment.m4a" };
      }
      if (MediaRecorder.isTypeSupported("audio/ogg;codecs=opus")) {
        return { mimeType: "audio/ogg;codecs=opus", filename: "enrollment.ogg" };
      }
    }
    return { mimeType: "audio/webm", filename: "enrollment.webm" };
  }

  async function startRecording() {
    setError(null);
    setAudioBlob(null);
    chunksRef.current = [];
    setElapsed(0);

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const { mimeType } = pickMimeType();
      const recorder = new MediaRecorder(stream, { mimeType });
      mediaRecorderRef.current = recorder;

      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) chunksRef.current.push(event.data);
      };
      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: mimeType });
        setAudioBlob(blob);
        setState("recorded");
        stopStream();
        if (timerRef.current) {
          clearInterval(timerRef.current);
          timerRef.current = null;
        }
      };

      recorder.start();
      startedAtRef.current = Date.now();
      setState("recording");

      timerRef.current = setInterval(() => {
        const seconds = (Date.now() - startedAtRef.current) / 1000;
        setElapsed(seconds);
        if (seconds >= MAX_DURATION_S) {
          recorder.stop();
        }
      }, 100);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start microphone");
      stopStream();
      setState("idle");
    }
  }

  function stopRecording() {
    mediaRecorderRef.current?.stop();
  }

  async function submit() {
    if (!audioBlob) return;
    setState("uploading");
    setError(null);
    try {
      const { filename } = pickMimeType();
      await enrollVoice({ audio: audioBlob, filename });
      window.localStorage.setItem(STORAGE_KEY, "true");
      router.replace("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
      setState("recorded");
    }
  }

  function skip() {
    window.localStorage.setItem(STORAGE_KEY, "true");
    router.replace("/dashboard");
  }

  function reset() {
    setAudioBlob(null);
    setElapsed(0);
    setState("idle");
    setError(null);
  }

  const progress = Math.min((elapsed / MAX_DURATION_S) * 100, 100);
  const isRecording = state === "recording";

  return (
    <div className="onboarding-shell">
      <h1>Teach Wai your voice</h1>
      <p className="onboarding-lead">
        Read the prompt for ~20 seconds. Wai will recognise you in future meetings
        automatically.
      </p>

      <article className="onboarding-prompt-card">
        <p>{PROMPT_TEXT}</p>
      </article>

      <div className="onboarding-controls">
        <button
          type="button"
          className={`onboarding-record-button ${isRecording ? "onboarding-record-button--recording" : ""}`}
          onClick={isRecording ? stopRecording : startRecording}
          disabled={state === "uploading"}
        >
          {isRecording ? "Stop" : "Record"}
        </button>

        <div className="onboarding-progress-stack">
          <div className="onboarding-progress-bar">
            <div
              className="onboarding-progress-fill"
              style={{ width: `${progress}%` }}
              aria-hidden="true"
            />
          </div>
          <p className="onboarding-status">{statusLabel(state, elapsed)}</p>
          {error ? <p className="onboarding-error">{error}</p> : null}
        </div>
      </div>

      {state === "recorded" ? (
        <div className="onboarding-take-actions">
          <button type="button" className="primary" onClick={submit}>
            Use this take
          </button>
          <button type="button" className="ghost" onClick={reset}>
            Re-record
          </button>
        </div>
      ) : null}

      {state === "uploading" ? (
        <p className="onboarding-status">Uploading voice signature…</p>
      ) : null}

      <button type="button" className="ghost" onClick={skip}>
        Skip for now
      </button>

      <p className="onboarding-privacy">
        We store a 192-number signature, not your audio. The recording is deleted
        after the signature is created.
      </p>
    </div>
  );
}

function statusLabel(state: RecorderState, elapsed: number): string {
  switch (state) {
    case "idle":
      return "Press the mic to start";
    case "recording":
      return `Recording… ${Math.floor(elapsed)}s / ${MAX_DURATION_S}s`;
    case "recorded":
      return `Recorded ${Math.floor(elapsed)}s. Use it or re-record.`;
    case "uploading":
      return "Uploading voice signature…";
  }
}
