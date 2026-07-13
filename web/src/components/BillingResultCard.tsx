"use client";

import Link from "next/link";
import { useEffect } from "react";
import { useRouter } from "next/navigation";

import type { BillingResultLocale } from "@/lib/billing-result-locale";

export type { BillingResultLocale, BillingResultSearchParams } from "@/lib/billing-result-locale";
export type BillingResultKind = "success" | "cancel";

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
      title: "Оплата отменена",
      body:
        "Платёж не был выполнен — деньги не списаны. Вы можете вернуться в WaiComputer и попробовать снова в любой момент.",
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
