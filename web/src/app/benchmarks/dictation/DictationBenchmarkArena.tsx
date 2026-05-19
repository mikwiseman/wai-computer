"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { ApiError } from "@/lib/http";
import { createDictationBenchmarkBattle } from "@/lib/api";
import type { DictationBenchmarkBattleResponse } from "@/lib/types";
import styles from "./benchmark.module.css";

type RecorderState = "idle" | "recording" | "uploading" | "done" | "error";

type ArenaCopy = {
  eyebrow: string;
  title: string;
  start: string;
  stop: string;
  statuses: Record<RecorderState, string>;
  signInMessage: string;
  signIn: string;
  modelHidden: string;
  selected: string;
  pickWinner: string;
  micUnavailable: string;
  requestFailed: string;
};

const defaultCopy: ArenaCopy = {
  eyebrow: "Live arena",
  title: "Dictate once, compare blind outputs",
  start: "Start dictation battle",
  stop: "Stop and compare",
  statuses: {
    idle: "Ready",
    recording: "Recording",
    uploading: "Running models",
    done: "Choose the best transcript",
    error: "Needs attention",
  },
  signInMessage: "Sign in to run a private live benchmark.",
  signIn: "Sign in",
  modelHidden: "Model hidden",
  selected: "Selected",
  pickWinner: "Pick winner",
  micUnavailable: "Microphone recording is not available in this browser.",
  requestFailed: "Benchmark request failed.",
};

export function DictationBenchmarkArena({
  copy = defaultCopy,
  signInHref = "/login",
}: {
  copy?: ArenaCopy;
  signInHref?: string;
}) {
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);
  const [state, setState] = useState<RecorderState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [battle, setBattle] = useState<DictationBenchmarkBattleResponse | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  async function uploadAudio(blob: Blob) {
    setState("uploading");
    setError(null);
    setSelectedId(null);
    try {
      const result = await createDictationBenchmarkBattle({
        audio: blob,
        filename: "dictation-benchmark.webm",
        language: "multi",
      });
      setBattle(result);
      setState("done");
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setError(copy.signInMessage);
      } else if (err instanceof Error) {
        setError(err.message);
      } else {
        setError(copy.requestFailed);
      }
      setState("error");
    }
  }

  async function startRecording() {
    if (!navigator.mediaDevices?.getUserMedia) {
      setError(copy.micUnavailable);
      setState("error");
      return;
    }

    setBattle(null);
    setError(null);
    setSelectedId(null);
    chunksRef.current = [];
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : "audio/webm";
      const recorder = new MediaRecorder(stream, { mimeType });
      recorderRef.current = recorder;
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          chunksRef.current.push(event.data);
        }
      };
      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        streamRef.current?.getTracks().forEach((track) => track.stop());
        streamRef.current = null;
        void uploadAudio(blob);
      };
      recorder.start();
      setState("recording");
    } catch (err) {
      setError(err instanceof Error ? err.message : copy.micUnavailable);
      setState("error");
    }
  }

  function stopRecording() {
    recorderRef.current?.stop();
  }

  const revealed = selectedId !== null;

  return (
    <section className={styles.arena} aria-labelledby="arena-title">
      <div className={styles.sectionHeader}>
        <p className={styles.eyebrow}>{copy.eyebrow}</p>
        <h2 id="arena-title">{copy.title}</h2>
      </div>

      <div className={styles.recorderBar}>
        {state === "recording" ? (
          <button className={styles.primaryButton} type="button" onClick={stopRecording}>
            {copy.stop}
          </button>
        ) : (
          <button
            className={styles.primaryButton}
            type="button"
            onClick={() => void startRecording()}
            disabled={state === "uploading"}
          >
            {copy.start}
          </button>
        )}
        <span className={styles.recorderStatus} data-state={state}>
          {copy.statuses[state]}
        </span>
      </div>

      {error ? (
        <div className={styles.notice}>
          <span>{error}</span>
          {error === copy.signInMessage ? <Link href={signInHref}>{copy.signIn}</Link> : null}
        </div>
      ) : null}

      {battle ? (
        <div className={styles.candidateGrid}>
          {battle.candidates.map((candidate, index) => (
            <article className={styles.candidate} key={candidate.id}>
              <div className={styles.candidateTop}>
                <span className={styles.candidateLetter}>{String.fromCharCode(65 + index)}</span>
                <span className={styles.candidateMeta}>
                  {revealed ? candidate.label : copy.modelHidden}
                </span>
              </div>
              <p className={styles.transcriptText}>
                {candidate.status === "ok" ? candidate.transcript : candidate.error}
              </p>
              <div className={styles.candidateFooter}>
                <span>{candidate.latency_ms ?? "—"} ms</span>
                <button
                  type="button"
                  className={selectedId === candidate.id ? styles.voteSelected : styles.voteButton}
                  onClick={() => setSelectedId(candidate.id)}
                >
                  {selectedId === candidate.id ? copy.selected : copy.pickWinner}
                </button>
              </div>
              {revealed ? (
                <div className={styles.reveal}>
                  {candidate.provider} / {candidate.model}
                </div>
              ) : null}
            </article>
          ))}
        </div>
      ) : null}
    </section>
  );
}
