"use client";

import { FormEvent, useEffect, useState, type ReactNode } from "react";
import Link from "next/link";
import { login, register, requestMagicLink, requestPasswordReset } from "@/lib/api";
import type { AuthLocale } from "@/lib/auth-locale";
import { ApiError } from "@/lib/http";
import { PasswordField } from "@/components/PasswordField";

type Mode = "login" | "register";
type Locale = AuthLocale;
type PendingAction = "magic" | "password" | "forgot";

const COPY: Record<
  Locale,
  {
    title: Record<Mode, string>;
    email: string;
    primarySubmit: string;
    sendMagicLoading: string;
    passwordMode: string;
    password: string;
    passwordSubmit: Record<Mode, string>;
    passwordLoading: string;
    forgotPassword: string;
    forgotTitle: string;
    forgotSubmit: string;
    forgotLoading: string;
    forgotGeneric: string;
    unexpectedError: string;
    invalidCredentials: string;
    registerError: string;
    legalConsent: string;
    terms: string;
    privacy: string;
    switchLink: Record<Mode, string>;
    tagline: string;
  }
> = {
  en: {
    title: {
      login: "Sign in",
      register: "Create account",
    },
    email: "Email",
    primarySubmit: "Email me a sign-in link",
    sendMagicLoading: "Sending…",
    passwordMode: "Use password instead",
    password: "Password",
    passwordSubmit: {
      login: "Sign in with password",
      register: "Create account with password",
    },
    passwordLoading: "Please wait…",
    forgotPassword: "Forgot password?",
    forgotTitle: "Password reset",
    forgotSubmit: "Send password reset link",
    forgotLoading: "Sending…",
    forgotGeneric: "If this email is registered, we sent a password reset link.",
    unexpectedError: "Unexpected error",
    invalidCredentials: "Invalid email or password",
    registerError: "Unable to create account. Try signing in or request a magic link.",
    legalConsent: "I agree to the {terms} and {privacy}.",
    terms: "Terms of Service",
    privacy: "Privacy Policy",
    switchLink: {
      login: "Need an account?",
      register: "Have an account?",
    },
    tagline: "Your second brain",
  },
  ru: {
    title: {
      login: "Войти",
      register: "Создать аккаунт",
    },
    email: "Email",
    primarySubmit: "Отправить ссылку для входа",
    sendMagicLoading: "Отправляем…",
    passwordMode: "Использовать пароль",
    password: "Пароль",
    passwordSubmit: {
      login: "Войти по паролю",
      register: "Создать аккаунт с паролем",
    },
    passwordLoading: "Подождите…",
    forgotPassword: "Забыли пароль?",
    forgotTitle: "Сброс пароля",
    forgotSubmit: "Отправить ссылку для сброса",
    forgotLoading: "Отправляем…",
    forgotGeneric: "Если этот email зарегистрирован, мы отправили ссылку для сброса пароля.",
    unexpectedError: "Неожиданная ошибка",
    invalidCredentials: "Неверный email или пароль",
    registerError: "Не удалось создать аккаунт. Попробуйте войти или запросить ссылку на email.",
    legalConsent: "Я принимаю {terms} и {privacy}.",
    terms: "Условия сервиса",
    privacy: "Политика конфиденциальности",
    switchLink: {
      login: "Нужен аккаунт?",
      register: "Уже есть аккаунт?",
    },
    tagline: "Твой второй мозг",
  },
};

interface AuthFormProps {
  mode: Mode;
  onSuccess: () => void;
  initialLocale?: Locale;
}

function detectLocale(): Locale {
  if (typeof navigator === "undefined") return "en";
  const candidates = [
    ...Array.from(navigator.languages ?? []),
    navigator.language,
  ].filter(Boolean);
  return candidates[0]?.toLowerCase().startsWith("ru") ? "ru" : "en";
}

function authRegion(locale: Locale): "global" | "ru" {
  return locale === "ru" ? "ru" : "global";
}

function renderLegalConsent(
  template: string,
  termsNode: ReactNode,
  privacyNode: ReactNode,
): ReactNode[] {
  const tokenPattern = /\{(terms|privacy)\}/g;
  const segments: ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let key = 0;
  while ((match = tokenPattern.exec(template)) !== null) {
    if (match.index > lastIndex) {
      segments.push(template.slice(lastIndex, match.index));
    }
    segments.push(
      <span key={`token-${key++}`}>
        {match[1] === "terms" ? termsNode : privacyNode}
      </span>,
    );
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < template.length) {
    segments.push(template.slice(lastIndex));
  }
  return segments;
}

function describeError(error: unknown, locale: Locale): string {
  const copy = COPY[locale];
  let message: string;
  if (error instanceof ApiError) {
    message = error.message;
  } else if (error instanceof Error) {
    message = error.message;
  } else {
    return copy.unexpectedError;
  }

  if (locale === "ru") {
    if (message === "Invalid email or password" || message === "Invalid credentials") {
      return copy.invalidCredentials;
    }
    if (message === COPY.en.registerError) {
      return copy.registerError;
    }
  }
  return message;
}

export function AuthForm({ mode, onSuccess, initialLocale }: AuthFormProps) {
  const [locale, setLocale] = useState<Locale>(initialLocale ?? "en");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [passwordMode, setPasswordMode] = useState(false);
  const [forgotPasswordMode, setForgotPasswordMode] = useState(false);
  const [acceptedLegalTerms, setAcceptedLegalTerms] = useState(false);
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null);
  const copy = COPY[locale];
  const loading = pendingAction !== null;

  useEffect(() => {
    setLocale(initialLocale ?? detectLocale());
  }, [initialLocale]);

  async function onPasswordSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (mode === "register" && !acceptedLegalTerms) return;
    setMessage(null);
    setPendingAction("password");

    try {
      const trimmedEmail = email.trim();
      if (mode === "login") {
        await login(trimmedEmail, password, { locale, region: authRegion(locale) });
      } else {
        await register(trimmedEmail, password, {
          locale,
          region: authRegion(locale),
          acceptedLegalTerms,
        });
      }
      onSuccess();
    } catch (error: unknown) {
      setMessage(describeError(error, locale));
    } finally {
      setPendingAction(null);
    }
  }

  async function onSendMagicLink(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (mode === "register" && !acceptedLegalTerms) return;
    setMessage(null);
    setPendingAction("magic");
    try {
      const response = await requestMagicLink(email.trim(), {
        locale,
        region: authRegion(locale),
        ...(mode === "register" ? { acceptedLegalTerms } : {}),
      });
      setMessage(response.message);
    } catch (error: unknown) {
      setMessage(describeError(error, locale));
    } finally {
      setPendingAction(null);
    }
  }

  async function onForgotPasswordSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage(null);
    setPendingAction("forgot");
    try {
      await requestPasswordReset(email.trim(), locale);
      setMessage(copy.forgotGeneric);
    } catch (error: unknown) {
      setMessage(describeError(error, locale));
    } finally {
      setPendingAction(null);
    }
  }

  return (
    <section className="auth-card">
      <header className="auth-card__hero" aria-label="WaiComputer">
        <picture>
          <source srcSet="/app-icon-dark-320.png" media="(prefers-color-scheme: dark)" />
          <img
            className="auth-card__icon"
            src="/app-icon-320.png"
            width={64}
            height={64}
            alt=""
            aria-hidden="true"
          />
        </picture>
        <span className="auth-card__wordmark">WaiComputer</span>
        <span className="auth-card__tagline">{copy.tagline}</span>
      </header>

      <header className="auth-card__header">
        <h1>{copy.title[mode]}</h1>
      </header>

      <form onSubmit={onSendMagicLink} className="auth-form">
        <label htmlFor="email">
          <span>{copy.email}</span>
          <input
            id="email"
            data-testid="auth-email"
            name="email"
            type="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
        </label>

        {mode === "register" ? (
          <label className="auth-legal-consent">
            <input
              data-testid="legal-consent-checkbox"
              type="checkbox"
              checked={acceptedLegalTerms}
              onChange={(event) => setAcceptedLegalTerms(event.target.checked)}
              disabled={loading}
            />
            <span>
              {renderLegalConsent(
                copy.legalConsent,
                <Link href={locale === "ru" ? "/ru/terms" : "/terms"}>{copy.terms}</Link>,
                <Link href={locale === "ru" ? "/ru/privacy" : "/privacy"}>{copy.privacy}</Link>,
              )}
            </span>
          </label>
        ) : null}

        <button
          className="primary-button"
          data-testid="magic-link-button"
          type="submit"
          disabled={
            loading
            || email.trim().length === 0
            || (mode === "register" && !acceptedLegalTerms)
          }
        >
          {pendingAction === "magic" ? copy.sendMagicLoading : copy.primarySubmit}
        </button>
      </form>

      {passwordMode ? (
        <form onSubmit={onPasswordSubmit} className="auth-form">
          <PasswordField
            id="password"
            name="password"
            data-testid="auth-password"
            label={copy.password}
            value={password}
            onChange={setPassword}
            locale={locale}
            showStrength={mode === "register"}
            required
            autoComplete={mode === "register" ? "new-password" : "current-password"}
          />

          <button
            className="primary-button"
            data-testid="auth-submit"
            type="submit"
            disabled={loading || (mode === "register" && !acceptedLegalTerms)}
          >
            {pendingAction === "password" ? copy.passwordLoading : copy.passwordSubmit[mode]}
          </button>

          {mode === "login" ? (
            <button
              className="ghost-button"
              data-testid="forgot-password-button"
              type="button"
              onClick={() => setForgotPasswordMode(true)}
              disabled={loading}
            >
              {copy.forgotPassword}
            </button>
          ) : null}
        </form>
      ) : (
        <button
          className="ghost-button"
          data-testid="password-mode-button"
          type="button"
          onClick={() => setPasswordMode(true)}
          disabled={loading}
        >
          {copy.passwordMode}
        </button>
      )}

      {forgotPasswordMode && mode === "login" ? (
        <form
          className="auth-form"
          data-testid="forgot-password-panel"
          onSubmit={onForgotPasswordSubmit}
        >
          <strong>{copy.forgotTitle}</strong>
          <button
            className="ghost-button"
            data-testid="forgot-password-submit"
            type="submit"
            disabled={loading || email.trim().length === 0}
          >
            {pendingAction === "forgot" ? copy.forgotLoading : copy.forgotSubmit}
          </button>
        </form>
      ) : null}

      <div className="auth-card__secondary">
        <Link href={mode === "login" ? "/register" : "/login"}>
          {copy.switchLink[mode]}
        </Link>
      </div>

      {message ? (
        <p className="auth-card__message" data-testid="auth-message" role="status">
          {message}
        </p>
      ) : null}
    </section>
  );
}
