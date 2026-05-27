"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiFetch, ApiError } from "@/lib/http";
import styles from "./ThemeAccentPicker.module.css";

export type ThemeChoice = "system" | "light" | "dark";
export type AccentChoice =
  | "teal"
  | "amber"
  | "blue"
  | "green"
  | "violet"
  | "rose"
  | "graphite";

const THEME_STORAGE_KEY = "wai_theme";
const ACCENT_STORAGE_KEY = "wai_accent";

const DEFAULT_THEME: ThemeChoice = "system";
const DEFAULT_ACCENT: AccentChoice = "teal";

const ACCENT_ORDER: AccentChoice[] = [
  "teal",
  "amber",
  "blue",
  "green",
  "violet",
  "rose",
  "graphite",
];

// Inline swatch colors. The real surface tint comes from `[data-accent="…"]`
// in `tokens.css` (Agent G); these values let the swatch itself be visible
// before tokens land and act as a sane preview wherever the picker renders.
const ACCENT_SWATCH: Record<AccentChoice, string> = {
  teal: "#2f756d",
  amber: "#f59e0b",
  blue: "#3b82f6",
  green: "#22c55e",
  violet: "#8b5cf6",
  rose: "#f43f5e",
  graphite: "#6b7280",
};

type Locale = "en" | "ru";

type Copy = {
  appearance: string;
  themeGroupLabel: string;
  accentGroupLabel: string;
  theme: Record<ThemeChoice, string>;
  accent: Record<AccentChoice, string>;
};

const COPY: Record<Locale, Copy> = {
  en: {
    appearance: "Appearance",
    themeGroupLabel: "Theme",
    accentGroupLabel: "Accent color",
    theme: {
      system: "System",
      light: "Light",
      dark: "Dark",
    },
    accent: {
      teal: "Teal",
      amber: "Amber",
      blue: "Blue",
      green: "Green",
      violet: "Violet",
      rose: "Rose",
      graphite: "Graphite",
    },
  },
  ru: {
    appearance: "Внешний вид",
    themeGroupLabel: "Тема",
    accentGroupLabel: "Цвет акцента",
    theme: {
      system: "Системная",
      light: "Светлая",
      dark: "Тёмная",
    },
    accent: {
      teal: "Бирюзовый",
      amber: "Янтарный",
      blue: "Синий",
      green: "Зелёный",
      violet: "Фиолетовый",
      rose: "Розовый",
      graphite: "Графитовый",
    },
  },
};

function isThemeChoice(value: unknown): value is ThemeChoice {
  return value === "system" || value === "light" || value === "dark";
}

function isAccentChoice(value: unknown): value is AccentChoice {
  return typeof value === "string" && ACCENT_ORDER.includes(value as AccentChoice);
}

function applyTheme(theme: ThemeChoice): void {
  if (typeof document === "undefined") return;
  document.documentElement.setAttribute("data-theme", theme);
}

function applyAccent(accent: AccentChoice): void {
  if (typeof document === "undefined") return;
  document.documentElement.setAttribute("data-accent", accent);
}

function readStoredTheme(): ThemeChoice {
  if (typeof window === "undefined") return DEFAULT_THEME;
  try {
    const raw = window.localStorage.getItem(THEME_STORAGE_KEY);
    return isThemeChoice(raw) ? raw : DEFAULT_THEME;
  } catch {
    return DEFAULT_THEME;
  }
}

function readStoredAccent(): AccentChoice {
  if (typeof window === "undefined") return DEFAULT_ACCENT;
  try {
    const raw = window.localStorage.getItem(ACCENT_STORAGE_KEY);
    return isAccentChoice(raw) ? raw : DEFAULT_ACCENT;
  } catch {
    return DEFAULT_ACCENT;
  }
}

function writeStoredTheme(theme: ThemeChoice): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // ignore quota / disabled storage
  }
}

function writeStoredAccent(accent: AccentChoice): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(ACCENT_STORAGE_KEY, accent);
  } catch {
    // ignore quota / disabled storage
  }
}

export interface ThemeAccentPickerProps {
  locale: Locale;
  /** Optional override for storage hydration in tests / Storybook. */
  initialTheme?: ThemeChoice;
  initialAccent?: AccentChoice;
}

export function ThemeAccentPicker({
  locale,
  initialTheme,
  initialAccent,
}: ThemeAccentPickerProps) {
  const copy = COPY[locale];

  const [theme, setTheme] = useState<ThemeChoice>(initialTheme ?? DEFAULT_THEME);
  const [accent, setAccent] = useState<AccentChoice>(initialAccent ?? DEFAULT_ACCENT);

  // Hydrate from localStorage on mount and apply attributes.
  useEffect(() => {
    const storedTheme = initialTheme ?? readStoredTheme();
    const storedAccent = initialAccent ?? readStoredAccent();
    setTheme(storedTheme);
    setAccent(storedAccent);
    applyTheme(storedTheme);
    applyAccent(storedAccent);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Debounced PATCH — server may not support this yet; 404 swallowed.
  const patchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const patchPreferences = useCallback(
    (nextTheme: ThemeChoice, nextAccent: AccentChoice) => {
      if (patchTimer.current) clearTimeout(patchTimer.current);
      patchTimer.current = setTimeout(() => {
        void apiFetch("/api/settings/preferences", {
          method: "PATCH",
          body: JSON.stringify({ theme: nextTheme, accent: nextAccent }),
        }).catch((error: unknown) => {
          if (error instanceof ApiError && error.status === 404) {
            // Server has no preferences endpoint yet — localStorage is the source of truth.
            return;
          }
          // Silent on other errors too: persistence is best-effort for v1.
        });
      }, 400);
    },
    [],
  );

  useEffect(() => {
    return () => {
      if (patchTimer.current) clearTimeout(patchTimer.current);
    };
  }, []);

  const handleThemeChange = useCallback(
    (next: ThemeChoice) => {
      setTheme(next);
      applyTheme(next);
      writeStoredTheme(next);
      patchPreferences(next, accent);
    },
    [accent, patchPreferences],
  );

  const handleAccentChange = useCallback(
    (next: AccentChoice) => {
      setAccent(next);
      applyAccent(next);
      writeStoredAccent(next);
      patchPreferences(theme, next);
    },
    [theme, patchPreferences],
  );

  return (
    <div
      className={styles["theme-accent-picker"]}
      data-testid="theme-accent-picker"
      data-theme-current={theme}
      data-accent-current={accent}
    >
      <div
        className={styles["theme-segmented"]}
        role="radiogroup"
        aria-label={copy.themeGroupLabel}
        data-testid="theme-segmented"
      >
        {(["system", "light", "dark"] as ThemeChoice[]).map((option) => {
          const selected = theme === option;
          const classes = [
            styles["theme-segmented__option"],
            selected ? styles["theme-segmented__option--selected"] : null,
          ]
            .filter(Boolean)
            .join(" ");
          return (
            <button
              key={option}
              type="button"
              role="radio"
              aria-checked={selected}
              data-selected={selected}
              data-testid={`theme-option-${option}`}
              className={classes}
              onClick={() => handleThemeChange(option)}
            >
              {copy.theme[option]}
            </button>
          );
        })}
      </div>

      <div
        className={styles["accent-swatch-row"]}
        role="radiogroup"
        aria-label={copy.accentGroupLabel}
        data-testid="accent-swatch-row"
      >
        {ACCENT_ORDER.map((option) => {
          const selected = accent === option;
          const classes = [
            styles["accent-swatch"],
            selected ? styles["accent-swatch--selected"] : null,
          ]
            .filter(Boolean)
            .join(" ");
          return (
            <button
              key={option}
              type="button"
              role="radio"
              aria-checked={selected}
              aria-label={copy.accent[option]}
              title={copy.accent[option]}
              data-selected={selected}
              data-accent-option={option}
              data-testid={`accent-option-${option}`}
              className={classes}
              style={{ backgroundColor: ACCENT_SWATCH[option] }}
              onClick={() => handleAccentChange(option)}
            />
          );
        })}
      </div>
    </div>
  );
}
