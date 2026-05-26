"use client";

import Link from "next/link";
import { useEffect } from "react";
import { useRouter } from "next/navigation";

export type BillingResultKind = "success" | "cancel";
export type BillingResultLocale = "en" | "ru";
export type BillingResultSearchParams = Record<string, string | string[] | undefined>;
export type BillingResultContext = {
  acceptLanguage?: string | null;
  referer?: string | null;
};

function paramValue(
  params: BillingResultSearchParams,
  key: string,
): string | undefined {
  const value = params[key];
  return Array.isArray(value) ? value[0] : value;
}

export function resolveBillingResultLocale(
  params: BillingResultSearchParams = {},
  context: BillingResultContext = {},
): BillingResultLocale {
  const provider = paramValue(params, "provider")?.toLowerCase();
  const lang = (paramValue(params, "lang") ?? paramValue(params, "locale"))?.toLowerCase();
  const acceptLanguage = context.acceptLanguage?.toLowerCase() ?? "";
  const referer = context.referer?.toLowerCase() ?? "";

  if (provider === "tinkoff" || provider === "tbank" || provider === "t-bank" || lang === "ru") {
    return "ru";
  }
  if (acceptLanguage.split(",")[0]?.trim().startsWith("ru")) {
    return "ru";
  }
  if (
    referer.includes("tinkoff.ru") ||
    referer.includes("tbank.ru") ||
    referer.includes("/ru/")
  ) {
    return "ru";
  }

  return "en";
}

type Copy = {
  eyebrow: string;
  title: string;
  body: string;
  cta: string;
  redirectNotice: string;
};

const COPY: Record<BillingResultLocale, Record<BillingResultKind, Copy>> = {
  en: {
    success: {
      eyebrow: "Billing",
      title: "You're all set",
      body:
        "Your payment was accepted. Your WaiComputer Pro plan is active — open the dashboard to start using it.",
      cta: "Open WaiComputer →",
      redirectNotice: "Redirecting to your dashboard…",
    },
    cancel: {
      eyebrow: "Billing",
      title: "Checkout canceled",
      body:
        "No payment was made. You can return to WaiComputer and try again any time.",
      cta: "Open WaiComputer →",
      redirectNotice: "",
    },
  },
  ru: {
    success: {
      eyebrow: "Подписка",
      title: "Готово",
      body:
        "Платёж принят. Подписка WaiComputer Pro активирована — откройте кабинет, чтобы начать.",
      cta: "Открыть WaiComputer →",
      redirectNotice: "Переходим в кабинет…",
    },
    cancel: {
      eyebrow: "Подписка",
      title: "Оплата не прошла",
      body:
        "Платёж не был подтверждён: карта не подошла, банк отклонил операцию или форма оплаты была закрыта. Для оплаты через Т-Банк нужна карта, которую принимает Т-Банк; 4242 4242 4242 4242 — Stripe test card, а не тестовая карта Т-Банка. Можно вернуться в WaiComputer и попробовать снова.",
      cta: "Открыть WaiComputer →",
      redirectNotice: "",
    },
  },
};

export function BillingResultCard({
  kind,
  locale,
}: {
  kind: BillingResultKind;
  locale: BillingResultLocale;
}) {
  const text = COPY[locale][kind];
  const router = useRouter();

  useEffect(() => {
    if (kind !== "success") return;
    const timer = window.setTimeout(() => {
      router.replace("/dashboard");
    }, 5000);
    return () => window.clearTimeout(timer);
  }, [kind, router]);

  return (
    <main className="billing-result-shell">
      <section className={`billing-result-card billing-result-card--${kind}`}>
        <p className="eyebrow">{text.eyebrow}</p>
        <h1>{text.title}</h1>
        <p>{text.body}</p>
        <Link
          href="/dashboard"
          className="primary-button billing-result-button"
          data-testid="billing-result-cta"
        >
          {text.cta}
        </Link>
        {kind === "success" && text.redirectNotice ? (
          <p
            role="status"
            style={{ fontSize: "0.85rem", color: "var(--ink-soft)", margin: 0 }}
          >
            {text.redirectNotice}
          </p>
        ) : null}
      </section>
    </main>
  );
}
