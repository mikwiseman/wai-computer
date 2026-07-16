"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { MonitorCog, Moon, SunMedium } from "lucide-react";
import { ApiError } from "@/lib/http";
import { getPreferences, updatePreferences } from "@/lib/api";
import {
  DEFAULT_THEME,
  applyTheme,
  isThemeChoice,
  readStoredTheme,
  subscribeStoredTheme,
  writeStoredTheme,
  type ThemeChoice,
} from "@/lib/theme";
import styles from "./ThemeAccentPicker.module.css";

export type { ThemeChoice };
export type AccentChoice =
  | "teal"
  | "amber"
  | "blue"
  | "green"
  | "violet"
  | "rose"
  | "graphite";

const ACCENT_STORAGE_KEY = "wai_accent";

const DEFAULT_ACCENT: AccentChoice = "amber";
let accentSnapshot: AccentChoice = DEFAULT_ACCENT;
let accentSnapshotIsAuthoritative = false;

const ACCENT_ORDER: AccentChoice[] = [
  "teal",
  "amber",
  "blue",
  "green",
  "violet",
  "rose",
  "graphite",
];

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
      light: "Pearl",
      dark: "Midnight",
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
      light: "Жемчужная",
      dark: "Полночь",
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

const THEME_ICONS: Record<ThemeChoice, typeof MonitorCog> = {
  system: MonitorCog,
  light: SunMedium,
  dark: Moon,
};

function isAccentChoice(value: unknown): value is AccentChoice {
  return typeof value === "string" && ACCENT_ORDER.includes(value as AccentChoice);
}

function applyAccent(accent: AccentChoice): void {
  if (typeof document === "undefined") return;
  document.documentElement.setAttribute("data-accent", accent);
}

function readStoredAccent(): AccentChoice {
  if (typeof window === "undefined") return DEFAULT_ACCENT;
  if (accentSnapshotIsAuthoritative) return accentSnapshot;
  try {
    const raw = window.localStorage.getItem(ACCENT_STORAGE_KEY);
    accentSnapshot = isAccentChoice(raw) ? raw : DEFAULT_ACCENT;
    return accentSnapshot;
  } catch {
    return accentSnapshot;
  }
}

const accentListeners = new Set<() => void>();

function subscribeStoredAccent(callback: () => void): () => void {
  accentListeners.add(callback);
  const onStorage = (event: StorageEvent) => {
    if (event.key === ACCENT_STORAGE_KEY) {
      accentSnapshot = isAccentChoice(event.newValue) ? event.newValue : DEFAULT_ACCENT;
      accentSnapshotIsAuthoritative = false;
      callback();
    }
  };
  if (typeof window !== "undefined") {
    window.addEventListener("storage", onStorage);
  }
  return () => {
    accentListeners.delete(callback);
    if (typeof window !== "undefined") {
      window.removeEventListener("storage", onStorage);
    }
  };
}

function writeStoredAccent(accent: AccentChoice): void {
  if (typeof window === "undefined") return;
  accentSnapshot = accent;
  try {
    window.localStorage.setItem(ACCENT_STORAGE_KEY, accent);
    accentSnapshotIsAuthoritative = false;
  } catch {
    accentSnapshotIsAuthoritative = true;
  }
  for (const listener of accentListeners) listener();
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

  // True until the server reply (or localStorage fallback) has been applied.
  // While true, we skip writing to the server — those state changes are hydration,
  // not user intent. Mirrors the pattern Mac uses: hydrate before subscribe.
  const hydratingRef = useRef(true);
  // If the user is unauthenticated (401) or the server has no preferences endpoint
  // (404), this stays true and PATCHes are skipped for the rest of the lifetime.
  const skipServerWritesRef = useRef(false);

  // Hydrate from localStorage immediately, then race a server fetch.
  // Server wins if it answers; localStorage is the fallback for anonymous users.
  useEffect(() => {
    const storedTheme = initialTheme ?? readStoredTheme();
    const storedAccent = initialAccent ?? readStoredAccent();
    setTheme(storedTheme);
    setAccent(storedAccent);
    applyTheme(storedTheme);
    applyAccent(storedAccent);

    // Test/Storybook overrides bypass the server fetch entirely.
    if (initialTheme !== undefined || initialAccent !== undefined) {
      hydratingRef.current = false;
      return;
    }

    let cancelled = false;
    void getPreferences()
      .then((prefs) => {
        if (cancelled) return;
        if (isThemeChoice(prefs.theme)) {
          setTheme(prefs.theme);
          applyTheme(prefs.theme);
          writeStoredTheme(prefs.theme);
        }
        if (isAccentChoice(prefs.accent)) {
          setAccent(prefs.accent);
          applyAccent(prefs.accent);
          writeStoredAccent(prefs.accent);
        }
      })
      .catch((error: unknown) => {
        if (error instanceof ApiError && (error.status === 401 || error.status === 404)) {
          // Unauthenticated or older deployment — stay on localStorage forever.
          skipServerWritesRef.current = true;
        }
        // Other errors are best-effort silent; localStorage remains the source of truth.
      })
      .finally(() => {
        if (!cancelled) hydratingRef.current = false;
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (initialTheme !== undefined || initialAccent !== undefined) return undefined;

    const syncTheme = () => {
      const storedTheme = readStoredTheme();
      setTheme(storedTheme);
      applyTheme(storedTheme);
    };
    const syncAccent = () => {
      const storedAccent = readStoredAccent();
      setAccent(storedAccent);
      applyAccent(storedAccent);
    };
    const unsubscribeTheme = subscribeStoredTheme(syncTheme);
    const unsubscribeAccent = subscribeStoredAccent(syncAccent);
    return () => {
      unsubscribeTheme();
      unsubscribeAccent();
    };
  }, [initialAccent, initialTheme]);

  // Debounced PATCH — silent on auth/404 errors; localStorage already mirrors state.
  const patchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const patchPreferences = useCallback(
    (nextTheme: ThemeChoice, nextAccent: AccentChoice) => {
      if (hydratingRef.current || skipServerWritesRef.current) return;
      if (patchTimer.current) clearTimeout(patchTimer.current);
      patchTimer.current = setTimeout(() => {
        void updatePreferences({ theme: nextTheme, accent: nextAccent }).catch(
          (error: unknown) => {
            if (error instanceof ApiError && (error.status === 401 || error.status === 404)) {
              skipServerWritesRef.current = true;
              return;
            }
            // Silent on other errors too: persistence is best-effort for v1.
          },
        );
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
      <section className={styles.section}>
        <span className={styles.sectionLabel}>{copy.themeGroupLabel}</span>
        <div
          className={styles["theme-segmented"]}
          role="radiogroup"
          aria-label={copy.themeGroupLabel}
          data-testid="theme-segmented"
        >
          {(["system", "light", "dark"] as ThemeChoice[]).map((option) => {
            const selected = theme === option;
            const Icon = THEME_ICONS[option];
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
                <Icon size={17} strokeWidth={1.8} aria-hidden="true" />
                <span>{copy.theme[option]}</span>
              </button>
            );
          })}
        </div>
      </section>

      <section className={styles.section}>
        <span className={styles.sectionLabel}>{copy.accentGroupLabel}</span>
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
                onClick={() => handleAccentChange(option)}
              />
            );
          })}
        </div>
      </section>
    </div>
  );
}
