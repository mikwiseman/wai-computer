"use client";

import { useId, useState } from "react";

type Locale = "en" | "ru";

interface PasswordFieldProps {
  value: string;
  onChange: (v: string) => void;
  label: string;
  id: string;
  locale: Locale;
  showStrength?: boolean;
  required?: boolean;
  "data-testid"?: string;
  autoComplete?: string;
  name?: string;
}

interface StrengthCopy {
  weak: string;
  fair: string;
  good: string;
  strong: string;
  empty: string;
  show: string;
  hide: string;
  minLength: string;
}

// Keep in sync with the backend minimum (RegisterRequest, auth.py).
export const MIN_PASSWORD_LENGTH = 8;

const COPY: Record<Locale, StrengthCopy> = {
  en: {
    weak: "Weak",
    fair: "Fair",
    good: "Good",
    strong: "Strong",
    empty: "Enter a password",
    show: "Show password",
    hide: "Hide password",
    minLength: `At least ${MIN_PASSWORD_LENGTH} characters`,
  },
  ru: {
    weak: "Слабый",
    fair: "Средний",
    good: "Хороший",
    strong: "Надёжный",
    empty: "Введите пароль",
    show: "Показать пароль",
    hide: "Скрыть пароль",
    minLength: `Минимум ${MIN_PASSWORD_LENGTH} символов`,
  },
};

/**
 * Score a password from 0 to 4.
 * Classes: lowercase / uppercase / digits / symbols.
 *   0 — empty
 *   1 — Weak: length < 8 OR only one character class
 *   2 — Fair: length >= 8 AND two classes
 *   3 — Good: length >= 10 AND three classes
 *   4 — Strong: length >= 14 AND all four classes
 */
export function scorePassword(value: string): 0 | 1 | 2 | 3 | 4 {
  if (!value) return 0;
  let classes = 0;
  if (/[a-z]/.test(value)) classes += 1;
  if (/[A-Z]/.test(value)) classes += 1;
  if (/\d/.test(value)) classes += 1;
  if (/[^A-Za-z0-9]/.test(value)) classes += 1;
  const len = value.length;
  if (len >= 14 && classes >= 4) return 4;
  if (len >= 10 && classes >= 3) return 3;
  if (len >= 8 && classes >= 2) return 2;
  return 1;
}

function strengthLabel(score: 0 | 1 | 2 | 3 | 4, copy: StrengthCopy): string {
  switch (score) {
    case 0:
      return copy.empty;
    case 1:
      return copy.weak;
    case 2:
      return copy.fair;
    case 3:
      return copy.good;
    case 4:
      return copy.strong;
  }
}

function segmentColor(
  score: 0 | 1 | 2 | 3 | 4,
  segment: 1 | 2 | 3 | 4,
): string {
  if (score < segment) return "var(--panel-subtle)";
  if (score === 1) return "var(--danger)";
  if (score === 2) return "var(--warm)";
  if (score === 3) return "var(--accent)";
  return "var(--success)";
}

const WRAP_STYLE: React.CSSProperties = {
  position: "relative",
  display: "block",
};

const INPUT_STYLE: React.CSSProperties = {
  paddingRight: "2.6rem",
};

const TOGGLE_STYLE: React.CSSProperties = {
  position: "absolute",
  right: "0.4rem",
  top: "50%",
  transform: "translateY(-50%)",
  width: "2rem",
  height: "2rem",
  minHeight: "2rem",
  display: "inline-flex",
  alignItems: "center",
  justifyContent: "center",
  background: "transparent",
  color: "var(--ink-soft)",
  border: "0",
  borderRadius: "var(--radius-sm)",
  padding: 0,
  cursor: "pointer",
};

const METER_WRAP_STYLE: React.CSSProperties = {
  marginTop: "0.45rem",
  display: "grid",
  gap: "0.3rem",
};

const METER_BAR_STYLE: React.CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(4, 1fr)",
  gap: "0.25rem",
};

const SEGMENT_BASE_STYLE: React.CSSProperties = {
  height: "4px",
  borderRadius: "var(--radius-xs, 2px)",
  transition: "background-color 0.18s ease",
};

const CAPTION_STYLE: React.CSSProperties = {
  color: "var(--ink-soft)",
  fontSize: "var(--font-caption-size)",
  lineHeight: "var(--font-caption-line)",
};

function EyeIcon() {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M1.5 12s4-7 10.5-7 10.5 7 10.5 7-4 7-10.5 7S1.5 12 1.5 12z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

function EyeOffIcon() {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M3 3l18 18" />
      <path d="M10.6 6.2A10.6 10.6 0 0 1 12 6c6.5 0 10.5 6 10.5 6a18.4 18.4 0 0 1-3.4 4.1" />
      <path d="M6.4 7.6A18.4 18.4 0 0 0 1.5 12s4 6 10.5 6c1.7 0 3.3-.4 4.6-1" />
      <path d="M9.6 9.6a3 3 0 0 0 4.2 4.2" />
    </svg>
  );
}

export function PasswordField({
  value,
  onChange,
  label,
  id,
  locale,
  showStrength = false,
  required,
  "data-testid": dataTestId,
  autoComplete,
  name,
}: PasswordFieldProps) {
  const [visible, setVisible] = useState(false);
  const copy = COPY[locale];
  const score = scorePassword(value);
  const meterId = useId();
  const captionLabel = strengthLabel(score, copy);
  const toggleLabel = visible ? copy.hide : copy.show;

  return (
    <label htmlFor={id}>
      <span>{label}</span>
      <span style={WRAP_STYLE}>
        <input
          id={id}
          name={name}
          data-testid={dataTestId}
          type={visible ? "text" : "password"}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          required={required}
          autoComplete={autoComplete}
          aria-describedby={showStrength ? meterId : undefined}
          style={INPUT_STYLE}
        />
        <button
          type="button"
          onClick={() => setVisible((prev) => !prev)}
          aria-pressed={visible}
          aria-label={toggleLabel}
          title={toggleLabel}
          style={TOGGLE_STYLE}
          data-testid={dataTestId ? `${dataTestId}-toggle` : undefined}
        >
          {visible ? <EyeOffIcon /> : <EyeIcon />}
        </button>
      </span>
      {showStrength ? (
        <div style={METER_WRAP_STYLE}>
          <div
            id={meterId}
            role="meter"
            aria-valuemin={0}
            aria-valuemax={4}
            aria-valuenow={score}
            aria-valuetext={captionLabel}
            aria-label={label}
            data-testid={dataTestId ? `${dataTestId}-meter` : undefined}
            data-score={score}
            style={METER_BAR_STYLE}
          >
            <span
              style={{
                ...SEGMENT_BASE_STYLE,
                background: segmentColor(score, 1),
              }}
            />
            <span
              style={{
                ...SEGMENT_BASE_STYLE,
                background: segmentColor(score, 2),
              }}
            />
            <span
              style={{
                ...SEGMENT_BASE_STYLE,
                background: segmentColor(score, 3),
              }}
            />
            <span
              style={{
                ...SEGMENT_BASE_STYLE,
                background: segmentColor(score, 4),
              }}
            />
          </div>
          <span style={CAPTION_STYLE} aria-hidden="true">
            {captionLabel}
          </span>
          <span
            style={{
              ...CAPTION_STYLE,
              color:
                value.length > 0 && value.length < MIN_PASSWORD_LENGTH
                  ? "var(--danger)"
                  : "var(--ink-soft)",
            }}
            data-testid={dataTestId ? `${dataTestId}-min-hint` : undefined}
          >
            {copy.minLength}
          </span>
        </div>
      ) : null}
    </label>
  );
}
