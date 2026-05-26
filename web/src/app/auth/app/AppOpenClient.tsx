"use client";

import { useEffect, useMemo } from "react";
import Link from "next/link";
import { buildWaiComputerAppUrl, type WaiComputerAppClient } from "@/lib/app-client";

type Locale = "en" | "ru";

interface AppOpenClientProps {
  token: string | null;
  client: WaiComputerAppClient | null;
  locale?: string | null;
  autoOpen?: boolean;
}

const COPY = {
  en: {
    title: "Open WaiComputer App",
    opening: "Opening WaiComputer. Keep this page open if macOS asks you to confirm.",
    invalid: "This app sign-in link is not valid.",
    missing: "Missing token.",
    openApp: "Open WaiComputer App",
    browser: "Use browser instead",
    back: "Back to login",
  },
  ru: {
    title: "Открыть приложение WaiComputer",
    opening: "Открываем WaiComputer. Оставь страницу открытой, если macOS попросит подтверждение.",
    invalid: "Эта ссылка для входа в приложение недействительна.",
    missing: "В ссылке нет токена.",
    openApp: "Открыть WaiComputer",
    browser: "Войти в браузере",
    back: "Назад ко входу",
  },
};

function browserLocale(): Locale {
  if (typeof navigator === "undefined") return "en";
  const candidates = [
    ...Array.from(navigator.languages ?? []),
    navigator.language,
  ].filter(Boolean);
  return candidates[0]?.toLowerCase().startsWith("ru") ? "ru" : "en";
}

function normalizeLocale(locale: string | null | undefined): Locale {
  if (locale) {
    return locale.toLowerCase().startsWith("ru") ? "ru" : "en";
  }
  return browserLocale();
}

function browserSignInUrl(token: string, locale: Locale): string {
  const query = new URLSearchParams({ token });
  if (locale !== "en") {
    query.set("locale", locale);
  }
  return `/auth/verify?${query.toString()}`;
}

export function AppOpenClient({
  token,
  client,
  locale,
  autoOpen = true,
}: AppOpenClientProps) {
  const normalizedLocale = normalizeLocale(locale);
  const copy = COPY[normalizedLocale];
  const appUrl = useMemo(() => {
    if (!token || !client) return null;
    return buildWaiComputerAppUrl(token, client);
  }, [client, token]);
  const browserUrl = token ? browserSignInUrl(token, normalizedLocale) : "/login";

  useEffect(() => {
    if (!autoOpen || !appUrl) return;

    const timer = window.setTimeout(() => {
      window.location.href = appUrl;
    }, 250);

    return () => window.clearTimeout(timer);
  }, [appUrl, autoOpen]);

  return (
    <section className="auth-card auth-card--compact">
      <div className="auth-card__brand">
        <div className="brand-mark" aria-hidden="true" />
        <span>WaiComputer</span>
      </div>
      <h1>{copy.title}</h1>
      {appUrl ? (
        <>
          <p data-testid="open-app-message">{copy.opening}</p>
          <div className="auth-card__secondary">
            <a data-testid="open-app-link" href={appUrl}>
              {copy.openApp}
            </a>
            <Link data-testid="browser-sign-in-link" href={browserUrl}>
              {copy.browser}
            </Link>
          </div>
        </>
      ) : token ? (
        <>
          <p data-testid="open-app-message">{copy.invalid}</p>
          <Link data-testid="browser-sign-in-link" href={browserUrl}>
            {copy.browser}
          </Link>
        </>
      ) : (
        <>
          <p data-testid="open-app-message">{copy.missing}</p>
          <Link href="/login">{copy.back}</Link>
        </>
      )}
    </section>
  );
}
