"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { verifyMagicLink } from "@/lib/api";
import { ApiError } from "@/lib/http";

interface VerifyMagicLinkClientProps {
  token: string | null;
  locale?: string | null;
}

type Locale = "en" | "ru";

const COPY: Record<
  Locale,
  {
    verifying: string;
    missingToken: string;
    genericFailure: string;
    verified: string;
    title: string;
    backToLogin: string;
  }
> = {
  en: {
    verifying: "Verifying token...",
    missingToken: "Missing token.",
    genericFailure: "Verification failed.",
    verified: "Magic link verified. Redirecting...",
    title: "Magic Link Verification",
    backToLogin: "Back to login",
  },
  ru: {
    verifying: "Проверяем ссылку...",
    missingToken: "Ссылка для входа отсутствует.",
    genericFailure: "Не удалось проверить ссылку.",
    verified: "Ссылка подтверждена. Перенаправляем...",
    title: "Проверка ссылки для входа",
    backToLogin: "Вернуться ко входу",
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

function normalizeLocale(value?: string | null): Locale {
  if (value) {
    return value.toLowerCase().startsWith("ru") ? "ru" : "en";
  }
  return browserLocale();
}

export function VerifyMagicLinkClient({ token, locale: rawLocale }: VerifyMagicLinkClientProps) {
  const router = useRouter();
  const locale = normalizeLocale(rawLocale);
  const copy = COPY[locale];
  const [message, setMessage] = useState(token ? copy.verifying : copy.missingToken);

  useEffect(() => {
    if (!token) return;

    void (async () => {
      try {
        await verifyMagicLink(token, { locale });
      } catch (error: unknown) {
        if (error instanceof ApiError) {
          setMessage(error.message);
          return;
        }
        setMessage(copy.genericFailure);
        return;
      }

      setMessage(copy.verified);
      router.replace(hasCompletedVoiceOnboarding() ? "/dashboard" : "/onboarding");
    })();
  }, [copy.genericFailure, copy.verified, locale, router, token]);

  return (
    <section className="auth-card auth-card--compact">
      <div className="auth-card__brand">
        <div className="brand-mark" aria-hidden="true" />
        <span>WaiComputer</span>
      </div>
      <h1>{copy.title}</h1>
      <p data-testid="verify-message">{message}</p>
      <Link href="/login">{copy.backToLogin}</Link>
    </section>
  );
}

function hasCompletedVoiceOnboarding(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem("voice_onboarding_complete") === "true";
  } catch {
    return false;
  }
}
