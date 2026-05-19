"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { ApiError } from "@/lib/http";
import { createDictationBenchmarkBattle, submitDictationBenchmarkVote } from "@/lib/api";
import type { DictationBenchmarkBattleResponse, DictationBenchmarkCandidate } from "@/lib/types";
import styles from "./benchmark.module.css";

type RecorderState = "idle" | "recording" | "uploading" | "done" | "error";

type ArenaCopy = {
  eyebrow: string;
  title: string;
  start: string;
  stop: string;
  steps: {
    record: string;
    run: string;
    vote: string;
  };
  statuses: Record<RecorderState, string>;
  signInMessage: string;
  signIn: string;
  modelHidden: string;
  selected: string;
  savingVote: string;
  voteSaved: string;
  pickWinner: string;
  newRound: string;
  recordingHint: string;
  resultsHint: string;
  privateRound: string;
  sameAudio: string;
  blindVote: string;
  languageLabel: string;
  runningModelsLabel: string;
  outputsReadyLabel: string;
  wordsLabel: string;
  languageOptions: Array<{ label: string; value: string }>;
  micUnavailable: string;
  requestFailed: string;
  voteFailed: string;
};

const defaultCopy: ArenaCopy = {
  eyebrow: "Live arena",
  title: "Dictate once, compare blind outputs",
  start: "Start dictation battle",
  stop: "Stop and compare",
  steps: {
    record: "Record",
    run: "Run",
    vote: "Vote",
  },
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
  savingVote: "Saving",
  voteSaved: "Vote saved",
  pickWinner: "Pick winner",
  newRound: "New round",
  recordingHint: "Speak naturally. Stop when the phrase is complete.",
  resultsHint: "Names stay hidden until you pick a winner.",
  privateRound: "Private round. Audio is used for this request only.",
  sameAudio: "One audio sample, all models.",
  blindVote: "Blind vote before reveal.",
  languageLabel: "Language",
  runningModelsLabel: "Running models",
  outputsReadyLabel: "outputs ready",
  wordsLabel: "words",
  languageOptions: [
    { label: "Auto", value: "multi" },
    { label: "English", value: "en" },
    { label: "Russian", value: "ru" },
  ],
  micUnavailable: "Microphone recording is not available in this browser.",
  requestFailed: "Benchmark request failed.",
  voteFailed: "Vote was not saved.",
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
  const [language, setLanguage] = useState("multi");
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [savingVoteId, setSavingVoteId] = useState<string | null>(null);
  const [savedVoteId, setSavedVoteId] = useState<string | null>(null);

  useEffect(() => {
    if (state !== "recording" || startedAt === null) {
      return undefined;
    }
    const interval = window.setInterval(() => {
      setElapsedSeconds(Math.max(0, Math.floor((Date.now() - startedAt) / 1000)));
    }, 250);
    return () => window.clearInterval(interval);
  }, [startedAt, state]);

  const elapsedLabel = useMemo(() => {
    const minutes = Math.floor(elapsedSeconds / 60);
    const seconds = `${elapsedSeconds % 60}`.padStart(2, "0");
    return `${minutes}:${seconds}`;
  }, [elapsedSeconds]);

  async function uploadAudio(audio: File) {
    setState("uploading");
    setError(null);
    setSelectedId(null);
    setSavingVoteId(null);
    setSavedVoteId(null);
    try {
      const result = await createDictationBenchmarkBattle({
        audio,
        filename: audio.name,
        language,
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
    setSavingVoteId(null);
    setSavedVoteId(null);
    setElapsedSeconds(0);
    chunksRef.current = [];
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const mimeType = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find((candidate) =>
        MediaRecorder.isTypeSupported(candidate),
      );
      const recorder = mimeType ? new MediaRecorder(stream, { mimeType }) : new MediaRecorder(stream);
      recorderRef.current = recorder;
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) {
          chunksRef.current.push(event.data);
        }
      };
      recorder.onstop = () => {
        const blobType = recorder.mimeType || mimeType || "audio/webm";
        const extension = blobType.includes("mp4") ? "m4a" : "webm";
        const blob = new Blob(chunksRef.current, { type: blobType });
        streamRef.current?.getTracks().forEach((track) => track.stop());
        streamRef.current = null;
        setStartedAt(null);
        void uploadAudio(new File([blob], `dictation-benchmark.${extension}`, { type: blobType }));
      };
      recorder.start();
      setStartedAt(Date.now());
      setState("recording");
    } catch (err) {
      setError(err instanceof Error ? err.message : copy.micUnavailable);
      setState("error");
    }
  }

  function stopRecording() {
    recorderRef.current?.stop();
  }

  async function pickWinner(candidate: DictationBenchmarkCandidate) {
    if (!battle || candidate.status !== "ok") {
      return;
    }
    setSelectedId(candidate.id);
    setSavingVoteId(candidate.id);
    setError(null);
    try {
      await submitDictationBenchmarkVote({
        battle_id: battle.battle_id,
        selected_candidate_id: candidate.id,
        selected_provider: candidate.provider,
        selected_model: candidate.model,
        language: battle.language,
        candidate_count: battle.candidates.length,
      });
      setSavedVoteId(candidate.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : copy.voteFailed);
    } finally {
      setSavingVoteId(null);
    }
  }

  const revealed = selectedId !== null;
  const okCount = battle?.candidates.filter((candidate) => candidate.status === "ok").length ?? 0;

  return (
    <section className={styles.arena} id="arena" aria-labelledby="arena-title">
      <div className={styles.arenaHeader}>
        <div>
          <p className={styles.eyebrow}>{copy.eyebrow}</p>
          <h2 id="arena-title">{copy.title}</h2>
        </div>
        <div className={styles.arenaStatusBoard} aria-label="Battle status">
          <span data-active={state === "recording"}>{copy.steps.record}</span>
          <span data-active={state === "uploading"}>{copy.steps.run}</span>
          <span data-active={state === "done"}>{copy.steps.vote}</span>
          <strong>{copy.statuses[state]}</strong>
        </div>
      </div>

      <div className={styles.battleConsole}>
        <div className={styles.recorderPanel}>
          <div className={styles.recorderTopline}>
            <span className={styles.liveDot} data-state={state} />
            <span className={styles.timer}>{state === "recording" ? elapsedLabel : "0:00"}</span>
          </div>
          <div className={styles.waveform} aria-hidden="true">
            {Array.from({ length: 26 }).map((_, index) => (
              <span
                key={index}
                style={{ animationDelay: `${index * 42}ms`, height: `${22 + ((index * 17) % 54)}%` }}
              />
            ))}
          </div>
          <div className={styles.battleStrip} aria-label="Battle mechanics">
            <span>{copy.sameAudio}</span>
            <strong>A</strong>
            <strong>B</strong>
            <strong>C</strong>
            <span>{copy.blindVote}</span>
          </div>
          <p className={styles.recorderHint}>
            {state === "done"
              ? `${okCount}/${battle?.candidates.length ?? 0} ${copy.outputsReadyLabel}. ${copy.resultsHint}`
              : copy.recordingHint}
          </p>
          <div className={styles.languagePicker} aria-label={copy.languageLabel}>
            <span>{copy.languageLabel}</span>
            <div>
              {copy.languageOptions.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  className={language === option.value ? styles.languageSelected : styles.languageButton}
                  onClick={() => setLanguage(option.value)}
                  disabled={state === "recording" || state === "uploading"}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>
          <div className={styles.recorderActions}>
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
                {battle ? copy.newRound : copy.start}
              </button>
            )}
            <span className={styles.privateRound}>{copy.privateRound}</span>
          </div>
        </div>

        <div className={styles.runningPanel}>
          <span className={styles.panelLabel}>{copy.runningModelsLabel}</span>
          <div className={styles.modelRails}>
            {(battle?.candidates ?? []).length > 0 ? (
              battle?.candidates.map((candidate, index) => (
                <div className={styles.modelRail} key={candidate.id}>
                  <span>{String.fromCharCode(65 + index)}</span>
                  <strong>{revealed ? candidate.label : copy.modelHidden}</strong>
                  <em data-status={candidate.status}>{candidate.status}</em>
                </div>
              ))
            ) : (
              ["ElevenLabs", "Soniox", "Deepgram"].map((model, index) => (
                <div className={styles.modelRail} key={model}>
                  <span>{String.fromCharCode(65 + index)}</span>
                  <strong>{model}</strong>
                  <em data-status="standby">standby</em>
                </div>
              ))
            )}
          </div>
        </div>
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
                <span>
                  {candidate.latency_ms ?? "—"} ms · {candidate.word_count ?? "—"} {copy.wordsLabel}
                </span>
                <button
                  type="button"
                  className={selectedId === candidate.id ? styles.voteSelected : styles.voteButton}
                  disabled={candidate.status !== "ok"}
                  onClick={() => void pickWinner(candidate)}
                >
                  {savingVoteId === candidate.id
                    ? copy.savingVote
                    : savedVoteId === candidate.id
                      ? copy.voteSaved
                      : selectedId === candidate.id
                        ? copy.selected
                        : copy.pickWinner}
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
