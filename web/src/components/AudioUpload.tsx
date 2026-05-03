"use client";

import { useCallback, useRef, useState } from "react";
import { createRecording, uploadAudio } from "@/lib/api";
import type { RecordingDetail } from "@/lib/types";

interface AudioUploadProps {
  onUploadComplete: (detail: RecordingDetail) => void;
  onError: (message: string) => void;
}

const ACCEPTED_TYPES = [
  "audio/mpeg", "audio/mp3", "audio/mp4", "audio/m4a", "audio/x-m4a",
  "audio/wav", "audio/x-wav", "audio/webm", "audio/ogg", "audio/opus", "audio/flac",
];
const ACCEPTED_FILE_EXTENSIONS = ["mp3", "m4a", "wav", "webm", "ogg", "opus", "flac"] as const;
const ACCEPTED_FILE_INPUT = ".mp3,.m4a,.wav,.webm,.ogg,.opus,.flac";
const UNSUPPORTED_FORMAT_MESSAGE = "Unsupported format. Use MP3, M4A, WAV, WebM, OGG, OPUS, or FLAC.";

export function AudioUpload({ onUploadComplete, onError }: AudioUploadProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFile = useCallback(async (file: File) => {
    const fileNameParts = file.name.toLowerCase().split(".");
    const fileExtension = fileNameParts.length > 1 ? fileNameParts.at(-1) : null;
    const hasAllowedExtension =
      fileExtension !== null &&
      ACCEPTED_FILE_EXTENSIONS.includes(
        fileExtension as (typeof ACCEPTED_FILE_EXTENSIONS)[number],
      );
    const hasAllowedType = ACCEPTED_TYPES.includes(file.type);

    if ((!fileExtension && !hasAllowedType) || (fileExtension !== null && !hasAllowedExtension)) {
      onError(UNSUPPORTED_FORMAT_MESSAGE);
      return;
    }

    setUploading(true);
    setProgress("Creating recording...");

    try {
      const title = file.name.replace(/\.[^.]+$/, "");
      const recording = await createRecording({ title, type: "note", language: "multi" });

      setProgress("Uploading audio...");
      const detail = await uploadAudio(recording.id, file);

      setProgress("");
      onUploadComplete(detail);
    } catch (err) {
      onError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
      setProgress("");
    }
  }, [onUploadComplete, onError]);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  }, [handleFile]);

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleFile(file);
    e.target.value = "";
  }, [handleFile]);

  return (
    <div
      className={`upload-zone ${isDragging ? "upload-zone--dragging" : ""}`}
      onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={handleDrop}
      onClick={() => !uploading && fileInputRef.current?.click()}
    >
      <input
        ref={fileInputRef}
        type="file"
        accept={ACCEPTED_FILE_INPUT}
        onChange={handleFileSelect}
        style={{ display: "none" }}
      />
      {uploading ? (
        <div className="upload-zone__status">
          <span className="upload-zone__spinner" />
          <span>{progress}</span>
        </div>
      ) : (
        <div className="upload-zone__label">
          <span style={{ fontSize: "1.5rem" }}>+</span>
          <span>Drop audio file here or click to upload</span>
          <span className="upload-zone__formats">MP3, M4A, WAV, WebM, OGG, OPUS, FLAC</span>
        </div>
      )}
    </div>
  );
}
