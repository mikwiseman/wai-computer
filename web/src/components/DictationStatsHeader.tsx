"use client";

import type { DictationEntry } from "@/lib/types";

type Locale = "en" | "ru";

const COPY: Record<Locale, { totalWords: string; wpm: string; streak: string }> = {
  en: { totalWords: "total words", wpm: "wpm", streak: "day streak" },
  ru: { totalWords: "всего слов", wpm: "слов/мин", streak: "дней подряд" },
};

function dayKey(date: Date): string {
  return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
}

// Mirrors macOS DictationHistoryStore.streakDays: counts consecutive days with
// at least one dictation, anchored at today (or yesterday if nothing today).
function computeStreak(entries: DictationEntry[]): number {
  if (entries.length === 0) return 0;
  const days = new Set(entries.map((entry) => dayKey(new Date(entry.occurred_at))));
  const cursor = new Date();
  cursor.setHours(0, 0, 0, 0);
  let streak = 1;
  if (!days.has(dayKey(cursor))) {
    cursor.setDate(cursor.getDate() - 1);
    if (!days.has(dayKey(cursor))) return 0;
  }
  for (;;) {
    const previous = new Date(cursor);
    previous.setDate(previous.getDate() - 1);
    if (!days.has(dayKey(previous))) break;
    streak += 1;
    cursor.setTime(previous.getTime());
  }
  return streak;
}

export interface DictationStatsHeaderProps {
  entries: DictationEntry[];
  locale?: Locale;
}

export function DictationStatsHeader({ entries, locale = "en" }: DictationStatsHeaderProps) {
  if (entries.length === 0) return null;

  const copy = COPY[locale];
  const totalWords = entries.reduce((sum, entry) => sum + entry.word_count, 0);
  const totalSeconds = entries.reduce((sum, entry) => sum + entry.duration_seconds, 0);
  const wpm = totalSeconds > 0 ? Math.floor(totalWords / (totalSeconds / 60)) : 0;
  const streak = computeStreak(entries);

  return (
    <div className="dictation-stats" data-testid="dictation-stats">
      <div className="dictation-stat">
        <strong>{totalWords.toLocaleString()}</strong>
        <span>{copy.totalWords}</span>
      </div>
      <div className="dictation-stat">
        <strong>{wpm}</strong>
        <span>{copy.wpm}</span>
      </div>
      <div className="dictation-stat">
        <strong>{streak}</strong>
        <span>{copy.streak}</span>
      </div>
    </div>
  );
}
