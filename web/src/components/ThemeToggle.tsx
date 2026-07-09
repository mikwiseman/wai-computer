"use client";

import { useCallback, useEffect, useRef, useSyncExternalStore } from "react";
import { ApiError } from "@/lib/http";
import { updatePreferences } from "@/lib/api";
import {
  DEFAULT_THEME,
  applyTheme,
  readStoredTheme,
  subscribeStoredTheme,
  writeStoredTheme,
  type ThemeChoice,
} from "@/lib/theme";
import styles from "./ThemeToggle.module.css";

type Locale = "en" | "ru";

const OPTIONS: ThemeChoice[] = ["system", "light", "dark"];

type Copy = {
  groupLabel: string;
  theme: Record<ThemeChoice, string>;
};

const COPY: Record<Locale, Copy> = {
  en: {
    groupLabel: "Theme",
    theme: { system: "System", light: "Light", dark: "Dark" },
  },
  ru: {
    groupLabel: "Тема",
    theme: { system: "Системная", light: "Светлая", dark: "Тёмная" },
  },
};

function SystemIcon() {
  return (
    <svg
      className={styles.icon}
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      aria-hidden="true"
    >
      <circle cx="8" cy="8" r="6.25" stroke="currentColor" strokeWidth="1.5" />
      <path d="M8 1.75A6.25 6.25 0 0 1 8 14.25Z" fill="currentColor" />
    </svg>
  );
}

function LightIcon() {
  return (
    <svg
      className={styles.icon}
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      aria-hidden="true"
    >
      <circle cx="8" cy="8" r="3.15" />
      <line x1="8" y1="1" x2="8" y2="2.4" />
      <line x1="8" y1="13.6" x2="8" y2="15" />
      <line x1="1" y1="8" x2="2.4" y2="8" />
      <line x1="13.6" y1="8" x2="15" y2="8" />
      <line x1="3.1" y1="3.1" x2="4.1" y2="4.1" />
      <line x1="11.9" y1="11.9" x2="12.9" y2="12.9" />
      <line x1="3.1" y1="12.9" x2="4.1" y2="11.9" />
      <line x1="11.9" y1="4.1" x2="12.9" y2="3.1" />
    </svg>
  );
}

function DarkIcon() {
  return (
    <svg
      className={styles.icon}
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      aria-hidden="true"
    >
      <path
        d="M13.4 9.7A5.6 5.6 0 0 1 6.3 2.6 5.6 5.6 0 1 0 13.4 9.7Z"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
    </svg>
  );
}

const ICONS: Record<ThemeChoice, () => React.ReactElement> = {
  system: SystemIcon,
  light: LightIcon,
  dark: DarkIcon,
};

export interface ThemeToggleProps {
  locale: Locale;
  className?: string;
}

/**
 * Compact icon-only theme switcher for public headers, the shared-note page,
 * and the dashboard sidebar. Shares its light/dark/system logic with the
 * settings `ThemeAccentPicker` via `@/lib/theme` so both stay in lockstep.
 */
export function ThemeToggle({ locale, className }: ThemeToggleProps) {
  const copy = COPY[locale];
  // Read the choice straight from the shared store: SSR renders the default,
  // the client re-reads localStorage after hydration (no attribute mismatch),
  // and the subscription keeps it fresh across tabs and the settings picker.
  const theme = useSyncExternalStore(
    subscribeStoredTheme,
    readStoredTheme,
    () => DEFAULT_THEME,
  );

  // If the user is unauthenticated (401) or the deployment lacks the
  // preferences endpoint (404), this latches true and PATCHes stop for the
  // rest of the lifetime. Mirrors the ThemeAccentPicker pattern.
  const skipServerWritesRef = useRef(false);
  const patchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Reflect the current choice onto the document (`data-theme` + chrome color)
  // whenever it changes — mount, a local pick, another tab, or the picker.
  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  // While on "system", follow live OS light/dark flips so the browser chrome
  // color stays fresh without a reload.
  useEffect(() => {
    if (theme !== "system") return;
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => applyTheme("system");
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, [theme]);

  useEffect(() => {
    return () => {
      if (patchTimer.current) clearTimeout(patchTimer.current);
    };
  }, []);

  const patchTheme = useCallback((next: ThemeChoice) => {
    if (skipServerWritesRef.current) return;
    if (patchTimer.current) clearTimeout(patchTimer.current);
    patchTimer.current = setTimeout(() => {
      void updatePreferences({ theme: next }).catch((error: unknown) => {
        if (error instanceof ApiError && (error.status === 401 || error.status === 404)) {
          skipServerWritesRef.current = true;
          return;
        }
        // Silent on other errors: persistence is best-effort; localStorage
        // already mirrors the choice.
      });
    }, 400);
  }, []);

  const handleSelect = useCallback(
    (next: ThemeChoice) => {
      // Persisting notifies the store, which re-renders with the new choice and
      // triggers the effect above to apply it to the document.
      writeStoredTheme(next);
      patchTheme(next);
    },
    [patchTheme],
  );

  return (
    <div
      className={[styles.toggle, className].filter(Boolean).join(" ")}
      role="radiogroup"
      aria-label={copy.groupLabel}
      data-testid="theme-toggle"
    >
      {OPTIONS.map((option) => {
        const selected = theme === option;
        const Icon = ICONS[option];
        const label = copy.theme[option];
        return (
          <button
            key={option}
            type="button"
            role="radio"
            aria-checked={selected}
            aria-label={label}
            title={label}
            data-selected={selected}
            data-theme-option={option}
            data-testid={`theme-toggle-${option}`}
            className={[styles.option, selected ? styles.optionSelected : null]
              .filter(Boolean)
              .join(" ")}
            onClick={() => handleSelect(option)}
          >
            <Icon />
          </button>
        );
      })}
    </div>
  );
}
