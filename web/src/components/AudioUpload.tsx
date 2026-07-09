"use client";

import { useCallback, useRef, useState } from "react";
import { createRecording, uploadAudio } from "@/lib/api";
import type { RecordingDetail } from "@/lib/types";

type Locale = "en" | "ru";

interface AudioUploadProps {
  onUploadComplete: (detail: RecordingDetail) => void;
  onError: (message: string) => void;
  folderId?: string | null;
  locale?: Locale;
}

// Mirrors the backend's media tables (app/core/media_audio.py): any container
// ffmpeg can demux is importable — video audio is extracted server-side.
const ACCEPTED_TYPES = [
  "audio/mpeg", "audio/mp3", "audio/mp4", "audio/m4a", "audio/x-m4a",
  "audio/wav", "audio/x-wav", "audio/webm", "audio/ogg", "audio/opus", "audio/flac",
  "audio/aiff", "audio/x-aiff", "audio/x-ms-wma", "audio/amr", "audio/x-matroska",
  "video/mp4", "video/quicktime", "video/webm", "video/x-matroska",
  "video/x-msvideo", "video/mpeg", "video/x-m4v", "video/x-ms-wmv",
  "video/x-flv", "video/3gpp", "video/mp2t",
];
const ACCEPTED_FILE_EXTENSIONS = [
  "mp3", "m4a", "aac", "wav", "webm", "ogg", "oga", "opus", "flac",
  "aiff", "aif", "wma", "amr", "mka", "caf",
  "mp4", "mov", "m4v", "mkv", "avi", "mpg", "mpeg", "wmv", "flv", "3gp", "3g2", "ts", "mts",
] as const;
const ACCEPTED_FILE_INPUT =
  ".mp3,.m4a,.aac,.wav,.webm,.ogg,.oga,.opus,.flac,.aiff,.aif,.wma,.amr,.mka,.caf," +
  ".mp4,.mov,.m4v,.mkv,.avi,.mpg,.mpeg,.wmv,.flv,.3gp,.3g2,.ts,.mts,audio/*,video/*";

const COPY: Record<Locale, {
  unsupported: string; creating: string; uploading: string; failed: string; drop: string;
}> = {
  en: {
    unsupported: "Unsupported format. Use an audio file (MP3, M4A, WAV…) or a video (MP4, MOV, MKV…).",
    creating: "Creating recording...",
    uploading: "Uploading file...",
    failed: "Upload failed",
    drop: "Drop an audio or video file here or click to upload",
  },
  ru: {
    unsupported: "Неподдерживаемый формат. Используйте аудио (MP3, M4A, WAV…) или видео (MP4, MOV, MKV…).",
    creating: "Создание записи...",
    uploading: "Загрузка файла...",
    failed: "Не удалось загрузить",
    drop: "Перетащите аудио- или видеофайл сюда или нажмите для загрузки",
  },
};

export function AudioUpload({ onUploadComplete, onError, folderId = null, locale = "en" }: AudioUploadProps) {
  const copy = COPY[locale];
  const [isDragging, setIsDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  const validateFile = useCallback((file: File) => {
    const fileNameParts = file.name.toLowerCase().split(".");
    const fileExtension = fileNameParts.length > 1 ? fileNameParts.at(-1) : null;
    const hasAllowedExtension =
      fileExtension !== null &&
      ACCEPTED_FILE_EXTENSIONS.includes(
        fileExtension as (typeof ACCEPTED_FILE_EXTENSIONS)[number],
      );
    const hasAllowedType = ACCEPTED_TYPES.includes(file.type);

    return !((!fileExtension && !hasAllowedType) || (fileExtension !== null && !hasAllowedExtension));
  }, []);

  const handleFiles = useCallback(async (files: File[]) => {
    if (files.length === 0) return;
    if (files.some((file) => !validateFile(file))) {
      onError(copy.unsupported);
      return;
    }

    setUploading(true);

    try {
      for (let index = 0; index < files.length; index += 1) {
        const file = files[index];
        const prefix = files.length > 1 ? `${index + 1}/${files.length}: ` : "";
        setProgress(`${prefix}${copy.creating}`);
        // Pass an empty title so the backend auto-generates one from the
        // transcript content instead of using the filename verbatim.
        const recording = await createRecording({
          title: "",
          type: "note",
          language: "multi",
          ...(folderId ? { folder_id: folderId } : {}),
        });

        setProgress(`${prefix}${copy.uploading}`);
        const detail = await uploadAudio(recording.id, file);
        onUploadComplete(detail);
      }

      setProgress("");
    } catch (err) {
      onError(err instanceof Error ? err.message : copy.failed);
    } finally {
      setUploading(false);
      setProgress("");
    }
  }, [folderId, onUploadComplete, onError, validateFile, copy.creating, copy.uploading, copy.unsupported, copy.failed]);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    void handleFiles(Array.from(e.dataTransfer.files));
  }, [handleFiles]);

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    void handleFiles(Array.from(e.target.files ?? []));
    e.target.value = "";
  }, [handleFiles]);

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
        multiple
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
          <span>{copy.drop}</span>
          <span className="upload-zone__formats">MP3, M4A, WAV, OGG, FLAC · MP4, MOV, MKV, AVI, WebM</span>
        </div>
      )}
    </div>
  );
}
