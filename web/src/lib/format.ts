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

/**
 * Compact human timestamp for list rows and detail headers:
 * "Сегодня, 10:25" / "Вчера, 18:19", "8 июля, 10:25" within the current year,
 * "8 июля 2025, 10:25" otherwise. Mirrors MacDateFormatting.listTimestamp in
 * the Mac app so both surfaces read identically.
 */
export function formatListTimestamp(value: string, locale: AuthLocale): string {
  const bcp = locale === "ru" ? "ru-RU" : "en-US";
  const date = new Date(value);
  const now = new Date();
  const time = date.toLocaleTimeString(bcp, {
    // Russian convention is 24h with a leading zero ("09:05"); US English is "9:05 AM".
    hour: locale === "ru" ? "2-digit" : "numeric",
    minute: "2-digit",
  });
  if (date.toDateString() === now.toDateString()) {
    return `${locale === "ru" ? "Сегодня" : "Today"}, ${time}`;
  }
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (date.toDateString() === yesterday.toDateString()) {
    return `${locale === "ru" ? "Вчера" : "Yesterday"}, ${time}`;
  }
  const sameYear = date.getFullYear() === now.getFullYear();
  const day = date
    .toLocaleDateString(
      bcp,
      sameYear
        ? { day: "numeric", month: "long" }
        : { day: "numeric", month: "long", year: "numeric" },
    )
    // Russian appends "г." after the year — noise outside formal dates.
    .replace(/\s*г\.$/, "");
  return `${day}, ${time}`;
}

/**
 * Recorded duration as a clock string: "0:53", "28:40", or hours-aware
 * "3:28:40" — never "208:40". Returns "" for absent/zero durations.
 */
export function formatDurationClock(seconds: number | null | undefined): string {
  if (!seconds || seconds <= 0) return "";
  const total = Math.floor(seconds);
  const hours = Math.floor(total / 3600);
  const mins = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (hours > 0) {
    return `${hours}:${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
  }
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}
