"use client";

import { useEffect, useMemo } from "react";
import Link from "next/link";
import { buildWaiComputerAppUrl, type WaiComputerAppClient } from "@/lib/app-client";

type Locale = "en" | "ru";

interface OpenWaiComputerAppClientProps {
  token: string | null;
  client: WaiComputerAppClient | null;
  autoOpen?: boolean;
  locale?: Locale | null;
}

const COPY: Record<
  Locale,
  {
    title: string;
    opening: string;
    invalid: string;
    missing: string;
    openApp: string;
    browser: string;
    back: string;
  }
> = {
  en: {
    title: "Open in WaiComputer",
    opening: "Opening WaiComputer. Keep this page open if macOS asks you to confirm.",
    invalid: "This app sign-in link is not valid.",
    missing: "Missing token.",
    openApp: "Open in WaiComputer",
    browser: "Use browser instead",
    back: "Back to login",
  },
  ru: {
    title: "Открыть в WaiComputer",
    opening: "Открываем WaiComputer. Оставьте страницу открытой, если macOS попросит подтверждение.",
    invalid: "Эта ссылка для входа в приложение недействительна.",
    missing: "В ссылке нет токена.",
    openApp: "Открыть в WaiComputer",
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
  return candidates.some((language) => language.toLowerCase().startsWith("ru")) ? "ru" : "en";
}

function resolveLocale(locale: Locale | null | undefined): Locale {
  if (locale === "ru" || locale === "en") return locale;
  return browserLocale();
}

export function OpenWaiComputerAppClient({
  token,
  client,
  autoOpen = true,
  locale,
}: OpenWaiComputerAppClientProps) {
  const resolvedLocale = resolveLocale(locale);
  const copy = COPY[resolvedLocale];
  const appUrl = useMemo(() => {
    if (!token || !client) return null;
    return buildWaiComputerAppUrl(token, client);
  }, [client, token]);

  const browserUrl = token ? `/auth/verify?token=${encodeURIComponent(token)}` : "/login";

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
