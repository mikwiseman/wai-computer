import type { AuthLocale } from "./auth-locale";

/**
 * Normalises a speaker label for display.
 *
 * Prefers the human-assigned `display_name`, then falls back to a friendly
 * formatted version of the diarisation provider's raw label or speaker id:
 *
 * - "speaker_0" / "speaker_3" → "Speaker 1" / "Speaker 4" (EN) or "Спикер 1" (RU)
 * - "Speaker 0"               → "Speaker 1" (1-based for display)
 * - other strings             → returned as-is
 *
 * Returns "Speaker 1" / "Спикер 1" if all inputs are blank, so the UI never
 * shows the empty raw enum.
 */
export function formatSpeakerLabel(
  speaker: string | null | undefined,
  rawLabel: string | null | undefined,
  displayName: string | null | undefined,
  locale: AuthLocale = "en",
): string {
  if (displayName && displayName.trim()) return displayName;

  const speakerWord = locale === "ru" ? "Спикер" : "Speaker";

  const source = (rawLabel ?? speaker ?? "").trim();
  if (!source) return `${speakerWord} 1`;

  const lowerMatch = /^speaker_(\d+)$/i.exec(source);
  if (lowerMatch) {
    const n = Number(lowerMatch[1]);
    if (Number.isFinite(n)) return `${speakerWord} ${n + 1}`;
  }

  const spacedMatch = /^Speaker\s+(\d+)$/i.exec(source);
  if (spacedMatch) {
    const n = Number(spacedMatch[1]);
    if (Number.isFinite(n)) return `${speakerWord} ${n + 1}`;
  }

  return source;
}

/**
 * Formats a millisecond offset as `M:SS` (e.g. 75000 → "1:15"), or "" when absent.
 *
 * Mirrors the backend `_format_timestamp_short` so copied/exported transcripts read
 * identically across surfaces.
 */
export function formatTimestamp(ms: number | null | undefined): string {
  if (ms == null) return "";
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const secs = totalSeconds % 60;
  return `${minutes}:${secs.toString().padStart(2, "0")}`;
}

/**
 * Strips inline-code markdown backticks (e.g. `Minecraft` → Minecraft) so
 * read-only views render the transcript as plain prose rather than as a
 * code dump. Triple backtick code fences are not used in transcripts and
 * are left untouched.
 */
export function stripInlineCodeMarkdown(text: string): string {
  if (!text) return text;
  return text.replace(/`([^`]+)`/g, "$1");
}
