"use client";

import { FormEvent, useState } from "react";
import Link from "next/link";
import { getApiBaseUrl } from "@/lib/http";
import { PasswordField } from "@/components/PasswordField";

type Locale = "en" | "ru";

interface ResetPasswordClientProps {
  token: string | null;
  locale?: string | null;
}

const COPY = {
  en: {
    title: "Reset password",
    missing: "Password reset token is missing.",
    password: "New password",
    confirm: "Confirm new password",
    submit: "Reset password",
    loading: "Resetting...",
    mismatch: "Passwords do not match.",
    short: "Password must be at least 8 characters.",
    success: "Password updated. Sign in below.",
    generic: "Password reset failed.",
    back: "Back to login",
  },
  ru: {
    title: "Сброс пароля",
    missing: "В ссылке нет токена для сброса пароля.",
    password: "Новый пароль",
    confirm: "Подтвердите пароль",
    submit: "Сбросить пароль",
    loading: "Сбрасываем...",
    mismatch: "Пароли не совпадают.",
    short: "Пароль должен быть не короче 8 символов.",
    success: "Пароль обновлён. Войдите ниже.",
    generic: "Не удалось сбросить пароль.",
    back: "Назад ко входу",
  },
};

function normalizeLocale(locale: string | null | undefined): Locale {
  return locale?.toLowerCase().startsWith("ru") ? "ru" : "en";
}

async function readErrorMessage(response: Response, fallback: string): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: unknown };
    return typeof payload.detail === "string" && payload.detail.length > 0
      ? payload.detail
      : fallback;
  } catch {
    return fallback;
  }
}

export function ResetPasswordClient({ token, locale }: ResetPasswordClientProps) {
  const normalizedLocale = normalizeLocale(locale);
  const copy = COPY[normalizedLocale];
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [message, setMessage] = useState(token ? null : copy.missing);
  const [isSuccess, setIsSuccess] = useState(false);
  const [loading, setLoading] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage(null);

    if (!token) {
      setMessage(copy.missing);
      return;
    }
    if (password.length < 8) {
      setMessage(copy.short);
      return;
    }
    if (password !== confirmPassword) {
      setMessage(copy.mismatch);
      return;
    }

    setLoading(true);
    try {
      const response = await fetch(`${getApiBaseUrl()}/api/auth/reset-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        cache: "no-store",
        body: JSON.stringify({ token, password, locale: normalizedLocale }),
      });
      if (!response.ok) {
        setMessage(await readErrorMessage(response, copy.generic));
        return;
      }
      setIsSuccess(true);
      setMessage(copy.success);
      setPassword("");
      setConfirmPassword("");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : copy.generic);
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="auth-card auth-card--compact">
      <div className="auth-card__brand">
        <div className="brand-mark" aria-hidden="true" />
        <span>WaiComputer</span>
      </div>
      <h1>{copy.title}</h1>
      {!isSuccess ? (
        <form onSubmit={onSubmit} className="auth-form">
          <PasswordField
            id="reset-password"
            data-testid="reset-password"
            label={copy.password}
            value={password}
            onChange={setPassword}
            locale={normalizedLocale}
            showStrength
            required
            autoComplete="new-password"
          />
          <PasswordField
            id="reset-password-confirm"
            data-testid="reset-password-confirm"
            label={copy.confirm}
            value={confirmPassword}
            onChange={setConfirmPassword}
            locale={normalizedLocale}
            showStrength={false}
            required
            autoComplete="new-password"
          />
          <button
            className="primary-button"
            data-testid="reset-password-submit"
            type="submit"
            disabled={loading || !token}
          >
            {loading ? copy.loading : copy.submit}
          </button>
        </form>
      ) : null}
      {message ? (
        <p className="auth-card__message" data-testid="reset-password-message" role="status">
          {message}
        </p>
      ) : null}
      <Link href="/login">{copy.back}</Link>
    </section>
  );
}
