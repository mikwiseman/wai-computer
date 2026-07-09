"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { createRecording, uploadAudio } from "@/lib/api";
import type { RecordingDetail } from "@/lib/types";

interface RecorderPanelProps {
  onRecordingComplete: (detail: RecordingDetail) => void;
  onError: (message: string) => void;
}

export function RecorderPanel({ onRecordingComplete, onError }: RecorderPanelProps) {
  const [recording, setRecording] = useState(false);
  const [duration, setDuration] = useState(0);
  const [processing, setProcessing] = useState(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  const startRecording = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : "audio/webm";
      const recorder = new MediaRecorder(stream, { mimeType });

      chunksRef.current = [];
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };

      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }

        const blob = new Blob(chunksRef.current, { type: mimeType });
        if (blob.size < 1000) {
          setRecording(false);
          setDuration(0);
          return;
        }

        setProcessing(true);
        try {
          const rec = await createRecording({ title: `Recording ${new Date().toLocaleString()}`, type: "note", language: "multi" });
          const file = new File([blob], "recording.webm", { type: mimeType });
          const detail = await uploadAudio(rec.id, file);
          onRecordingComplete(detail);
        } catch (error) {
          onError(error instanceof Error ? error.message : "Recording upload failed");
        } finally {
          setProcessing(false);
          setDuration(0);
        }
      };

      mediaRecorderRef.current = recorder;
      recorder.start(1000);
      setRecording(true);
      setDuration(0);
      timerRef.current = setInterval(() => setDuration((d) => d + 1), 1000);
    } catch {
      onError("Microphone access denied. Please allow microphone access in your browser.");
    }
  }, [onRecordingComplete, onError]);

  const stopRecording = useCallback(() => {
    mediaRecorderRef.current?.stop();
    setRecording(false);
  }, []);

  const formatTime = (seconds: number) => {
    const m = Math.floor(seconds / 60);
    const s = seconds % 60;
    return `${m}:${s.toString().padStart(2, "0")}`;
  };

  if (processing) {
    return (
      <div className="recorder-panel recorder-panel--processing">
        <span className="upload-zone__spinner" />
        <span>Uploading and transcribing…</span>
      </div>
    );
  }

  return (
    <div className={`recorder-panel ${recording ? "recorder-panel--recording" : ""}`}>
      {recording ? (
        <>
          <div className="recorder-panel__indicator" />
          <span className="recorder-panel__time">{formatTime(duration)}</span>
          <button className="recorder-panel__stop" onClick={stopRecording}>
            Stop
          </button>
        </>
      ) : (
        <button className="recorder-panel__start" onClick={startRecording}>
          Record in browser
        </button>
      )}
    </div>
  );
}
