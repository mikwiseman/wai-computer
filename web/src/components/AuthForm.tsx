"use client";

import { FormEvent, useEffect, useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import { MonitorDown, Send } from "lucide-react";
import {
  getTelegramAuthStatus,
  login,
  requestMagicLink,
  requestPasswordReset,
  startTelegramAuth,
} from "@/lib/api";
import type { AuthLocale } from "@/lib/auth-locale";
import { ApiError } from "@/lib/http";
import { MAC_DMG_URL } from "@/lib/links";
import type { TelegramAuthStart } from "@/lib/types";
import { PasswordField } from "@/components/PasswordField";

type Mode = "login" | "register";
type Locale = AuthLocale;
type PendingAction = "magic" | "password" | "forgot" | "telegram";

const TELEGRAM_POLL_INTERVAL_MS = 1500;

const COPY = {
  en: {
    title: "Start anywhere. Continue everywhere.",
    subtitle: "One account. Web, Mac, Telegram. Sign in or sign up automatically.",
    email: "Email",
    continue: "Continue",
    continuing: "Sending…",
    or: "or",
    telegram: "Continue with Telegram",
    telegramOpening: "Opening Telegram…",
    telegramWaiting: "Press Start in Telegram. This page will sign you in automatically.",
    passwordMode: "Use password",
    magicMode: "Use email link",
    password: "Password",
    passwordSubmit: "Sign in",
    passwordLoading: "Signing in…",
    forgotPassword: "Forgot password?",
    forgotSubmit: "Send reset link",
    forgotLoading: "Sending…",
    forgotGeneric: "If this email is registered, we sent a password reset link.",
    unexpectedError: "Unexpected error",
    invalidCredentials: "Invalid email or password",
    legalRequired: "Accept the Terms of Service and Privacy Policy to continue.",
    legalConsent: "I agree to the {terms} and {privacy}.",
    terms: "Terms of Service",
    privacy: "Privacy Policy",
    mac: "Get the Mac app",
    sentTitle: "Check your email",
    sentBody: (email: string) => `We sent a secure sign-in link to ${email}.`,
    sentResend: "Use another email",
  },
  ru: {
    title: "Начни где удобно. Продолжай везде.",
    subtitle: "Один аккаунт. Web, Mac, Telegram. Вход или регистрация — автоматически.",
    email: "Email",
    continue: "Продолжить",
    continuing: "Отправляем…",
    or: "или",
    telegram: "Продолжить через Telegram",
    telegramOpening: "Открываем Telegram…",
    telegramWaiting: "Нажми Start в Telegram. Эта страница войдёт в аккаунт автоматически.",
    passwordMode: "Войти по паролю",
    magicMode: "Войти по ссылке",
    password: "Пароль",
    passwordSubmit: "Войти",
    passwordLoading: "Входим…",
    forgotPassword: "Забыли пароль?",
    forgotSubmit: "Отправить ссылку для сброса",
    forgotLoading: "Отправляем…",
    forgotGeneric: "Если этот email зарегистрирован, мы отправили ссылку для сброса пароля.",
    unexpectedError: "Неожиданная ошибка",
    invalidCredentials: "Неверный email или пароль",
    legalRequired: "Прими Условия сервиса и Политику конфиденциальности, чтобы продолжить.",
    legalConsent: "Я принимаю {terms} и {privacy}.",
    terms: "Условия сервиса",
    privacy: "Политику конфиденциальности",
    mac: "Скачать приложение для Mac",
    sentTitle: "Проверь почту",
    sentBody: (email: string) => `Мы отправили безопасную ссылку для входа на ${email}.`,
    sentResend: "Указать другой email",
  },
} satisfies Record<Locale, Record<string, unknown>>;

interface AuthFormProps {
  mode: Mode;
  onSuccess: () => void;
  initialLocale?: Locale;
}

function detectLocale(): Locale {
  if (typeof navigator === "undefined") return "en";
  const candidates = [...Array.from(navigator.languages ?? []), navigator.language].filter(Boolean);
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
    if (match.index > lastIndex) segments.push(template.slice(lastIndex, match.index));
    segments.push(
      <span key={`token-${key++}`}>{match[1] === "terms" ? termsNode : privacyNode}</span>,
    );
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < template.length) segments.push(template.slice(lastIndex));
  return segments;
}

function describeError(error: unknown, locale: Locale): string {
  const copy = COPY[locale];
  if (error instanceof ApiError || error instanceof Error) {
    if (
      locale === "ru"
      && (error.message === "Invalid email or password" || error.message === "Invalid credentials")
    ) {
      return copy.invalidCredentials;
    }
    return error.message;
  }
  return copy.unexpectedError;
}

export function AuthForm({ mode, onSuccess, initialLocale }: AuthFormProps) {
  void mode;
  const [locale, setLocale] = useState<Locale>(initialLocale ?? "en");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [acceptedLegalTerms, setAcceptedLegalTerms] = useState(false);
  const [magicLinkSent, setMagicLinkSent] = useState(false);
  const [sentEmail, setSentEmail] = useState("");
  const [passwordMode, setPasswordMode] = useState(false);
  const [forgotPasswordMode, setForgotPasswordMode] = useState(false);
  const [telegramSession, setTelegramSession] = useState<TelegramAuthStart | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null);
  const onSuccessRef = useRef(onSuccess);
  const copy = COPY[locale];
  const loading = pendingAction !== null;

  useEffect(() => {
    onSuccessRef.current = onSuccess;
  }, [onSuccess]);

  useEffect(() => {
    setLocale(initialLocale ?? detectLocale());
  }, [initialLocale]);

  useEffect(() => {
    if (!telegramSession) return;
    const ticket = telegramSession.ticket;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    async function poll() {
      try {
        const status = await getTelegramAuthStatus(ticket);
        if (cancelled) return;
        if (status.status === "approved") {
          setTelegramSession(null);
          setPendingAction(null);
          onSuccessRef.current();
          return;
        }
        timer = setTimeout(() => void poll(), TELEGRAM_POLL_INTERVAL_MS);
      } catch (error: unknown) {
        if (cancelled) return;
        setTelegramSession(null);
        setPendingAction(null);
        setMessage(describeError(error, locale));
      }
    }

    timer = setTimeout(() => void poll(), TELEGRAM_POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [locale, telegramSession]);

  async function onSendMagicLink(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!acceptedLegalTerms) {
      setMessage(copy.legalRequired);
      return;
    }
    setMessage(null);
    setPendingAction("magic");
    const trimmedEmail = email.trim();
    try {
      await requestMagicLink(trimmedEmail, {
        locale,
        region: authRegion(locale),
        acceptedLegalTerms,
      });
      setSentEmail(trimmedEmail);
      setMagicLinkSent(true);
    } catch (error: unknown) {
      setMessage(describeError(error, locale));
    } finally {
      setPendingAction(null);
    }
  }

  async function onPasswordSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage(null);
    setPendingAction("password");
    try {
      await login(email.trim(), password, { locale, region: authRegion(locale) });
      onSuccessRef.current();
    } catch (error: unknown) {
      setMessage(describeError(error, locale));
    } finally {
      setPendingAction(null);
    }
  }

  async function onForgotPasswordSubmit() {
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

  async function onTelegramStart() {
    setMessage(null);
    setPendingAction("telegram");
    try {
      const session = await startTelegramAuth({ client: "web", locale });
      setTelegramSession(session);
      window.open(session.web_link, "_blank", "noopener,noreferrer");
    } catch (error: unknown) {
      setPendingAction(null);
      setMessage(describeError(error, locale));
    }
  }

  const legalConsent = (
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
  );

  return (
    <section className="auth-gateway">
      <header className="auth-gateway__brand" aria-label="WaiComputer">
        <picture>
          <source srcSet="/app-icon-dark-320.png" media="(prefers-color-scheme: dark)" />
          <img src="/app-icon-320.png" width={64} height={64} alt="" aria-hidden="true" />
        </picture>
        <span className="auth-gateway__wordmark">WaiComputer</span>
      </header>

      <div className="auth-gateway__intro">
        <h1>{copy.title}</h1>
        <p>{copy.subtitle}</p>
      </div>

      {magicLinkSent ? (
        <div className="auth-sent" data-testid="magic-link-sent">
          <h2>{copy.sentTitle}</h2>
          <p className="auth-sent__body">{copy.sentBody(sentEmail)}</p>
          <button
            className="auth-text-button"
            data-testid="magic-link-resend"
            type="button"
            onClick={() => {
              setMagicLinkSent(false);
              setMessage(null);
            }}
          >
            {copy.sentResend}
          </button>
        </div>
      ) : passwordMode ? (
        <form onSubmit={onPasswordSubmit} className="auth-gateway__form">
          <label className="auth-gateway__field-label" htmlFor="email"><span>{copy.email}</span></label>
          <input
            id="email"
            data-testid="auth-email"
            name="email"
            type="email"
            autoComplete="email"
            placeholder={copy.email}
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
          <PasswordField
            id="password"
            name="password"
            data-testid="auth-password"
            label={copy.password}
            value={password}
            onChange={setPassword}
            locale={locale}
            required
            autoComplete="current-password"
          />
          <button data-testid="auth-submit" type="submit" disabled={loading || !email || !password}>
            {pendingAction === "password" ? copy.passwordLoading : copy.passwordSubmit}
          </button>
          <div className="auth-gateway__quiet-actions">
            <button type="button" className="auth-text-button" onClick={() => setPasswordMode(false)}>
              {copy.magicMode}
            </button>
            <button
              data-testid="forgot-password-button"
              type="button"
              className="auth-text-button"
              onClick={() => setForgotPasswordMode(true)}
            >
              {copy.forgotPassword}
            </button>
          </div>
          {forgotPasswordMode ? (
            <button
              data-testid="forgot-password-submit"
              type="button"
              className="auth-secondary-button"
              disabled={loading || !email.trim()}
              onClick={() => void onForgotPasswordSubmit()}
            >
              {pendingAction === "forgot" ? copy.forgotLoading : copy.forgotSubmit}
            </button>
          ) : null}
        </form>
      ) : (
        <>
          <form onSubmit={onSendMagicLink} className="auth-gateway__form">
            <label className="auth-gateway__field-label" htmlFor="email"><span>{copy.email}</span></label>
            <input
              id="email"
              data-testid="auth-email"
              name="email"
              type="email"
              autoComplete="email"
              placeholder={copy.email}
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
            {legalConsent}
            <button
              data-testid="magic-link-button"
              type="submit"
              disabled={loading}
            >
              {pendingAction === "magic" ? copy.continuing : copy.continue}
            </button>
          </form>
          <div className="auth-gateway__separator"><span>{copy.or}</span></div>
          <button
            className="auth-secondary-button"
            data-testid="telegram-auth-button"
            type="button"
            disabled={loading}
            onClick={() => void onTelegramStart()}
          >
            <Send className="auth-gateway__telegram-icon" aria-hidden="true" size={18} />
            {pendingAction === "telegram" ? copy.telegramOpening : copy.telegram}
          </button>
          {telegramSession ? (
            <p className="auth-gateway__status" data-testid="telegram-auth-status" role="status">
              {copy.telegramWaiting}
            </p>
          ) : null}
          <button
            className="auth-text-button auth-gateway__password-link"
            data-testid="password-mode-button"
            type="button"
            onClick={() => setPasswordMode(true)}
          >
            {copy.passwordMode}
          </button>
        </>
      )}

      <nav className="auth-gateway__download" aria-label="WaiComputer apps">
        <a href={MAC_DMG_URL} download>
          <MonitorDown aria-hidden="true" size={17} />
          {copy.mac}
        </a>
      </nav>

      {message ? (
        <p className="auth-card__message" data-testid="auth-message" role="status">{message}</p>
      ) : null}
    </section>
  );
}
