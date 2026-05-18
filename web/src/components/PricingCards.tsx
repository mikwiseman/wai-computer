"use client";

import { useState } from "react";
import { createBillingCheckout } from "@/lib/billing";

type Locale = "en" | "ru";

type Currency = "usd" | "rub";

const COPY: Record<
  Locale,
  {
    heading: string;
    sub: string;
    monthly: string;
    yearly: string;
    save: string;
    free: {
      name: string;
      price: string;
      features: string[];
    };
    pro: {
      name: string;
      monthly: (amount: string) => string;
      yearly: (amount: string) => string;
      features: string[];
      cta: string;
      ctaInFlight: string;
      trial: string;
    };
    signInPrompt: string;
  }
> = {
  en: {
    heading: "Simple pricing.",
    sub: "Free for everyday voice notes. Pro when you need it everywhere.",
    monthly: "Monthly",
    yearly: "Yearly",
    save: "Save 20%",
    free: {
      name: "Free",
      price: "$0",
      features: [
        "10,000 transcribed words per week",
        "30-day searchable memory",
        "AI summaries on every recording",
        "Live dictation + meeting capture",
      ],
    },
    pro: {
      name: "Pro",
      monthly: (a) => `${a} / month`,
      yearly: (a) => `${a} / year`,
      features: [
        "Unlimited transcription",
        "Permanent searchable memory",
        "Agents + MCP access",
        "Advanced search across everything",
        "Priority support",
      ],
      cta: "Upgrade to Pro",
      ctaInFlight: "Opening checkout…",
      trial: "14-day trial — no credit card.",
    },
    signInPrompt: "Sign in to upgrade",
  },
  ru: {
    heading: "Простой прайс.",
    sub: "Бесплатно для повседневных голосовых заметок. Pro когда нужен везде.",
    monthly: "Помесячно",
    yearly: "Годовая",
    save: "−20%",
    free: {
      name: "Free",
      price: "0 ₽",
      features: [
        "10 000 транскрибированных слов в неделю",
        "Память с поиском за 30 дней",
        "AI-саммари к каждой записи",
        "Живая диктовка и запись встреч",
      ],
    },
    pro: {
      name: "Pro",
      monthly: (a) => `${a} / мес`,
      yearly: (a) => `${a} / год`,
      features: [
        "Транскрипция без ограничений",
        "Память с поиском навсегда",
        "Агенты + доступ к MCP",
        "Расширенный поиск по всему",
        "Приоритетная поддержка",
      ],
      cta: "Оформить Pro",
      ctaInFlight: "Открываем оплату…",
      trial: "14 дней триал — без карты.",
    },
    signInPrompt: "Войди, чтобы оформить Pro",
  },
};

interface Props {
  locale: Locale;
  currency: Currency;
  signedIn?: boolean;
  loginPath?: string;
}

export function PricingCards({
  locale,
  currency,
  signedIn = false,
  loginPath = "/login",
}: Props) {
  const copy = COPY[locale];
  const [period, setPeriod] = useState<"month" | "year">("month");
  const [inFlight, setInFlight] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The marketing site can render pricing without hitting the API — these are
  // the canonical sandbox-and-launch numbers from the v1.0 billing migration.
  const proMonthly = currency === "rub" ? "999 ₽" : "$12";
  const proYearly = currency === "rub" ? "7 999 ₽" : "$96";

  async function handleUpgrade() {
    setError(null);
    if (!signedIn) {
      window.location.href = loginPath + "?next=/billing";
      return;
    }
    setInFlight(true);
    try {
      const provider = currency === "rub" ? "tinkoff" : "stripe";
      const session = await createBillingCheckout({
        plan: "pro",
        period,
        provider,
      });
      window.location.href = session.checkout_url;
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : locale === "ru"
            ? "Не удалось открыть оплату"
            : "Couldn't open checkout",
      );
      setInFlight(false);
    }
  }

  return (
    <section className="pricing">
      <header>
        <h1>{copy.heading}</h1>
        <p>{copy.sub}</p>
      </header>

      <div className="pricing-toggle" role="tablist">
        <button
          role="tab"
          aria-selected={period === "month"}
          onClick={() => setPeriod("month")}
        >
          {copy.monthly}
        </button>
        <button
          role="tab"
          aria-selected={period === "year"}
          onClick={() => setPeriod("year")}
        >
          {copy.yearly} <span className="pricing-save">{copy.save}</span>
        </button>
      </div>

      <div className="pricing-grid">
        <article className="pricing-card pricing-card--free">
          <h2>{copy.free.name}</h2>
          <p className="pricing-price">{copy.free.price}</p>
          <ul>
            {copy.free.features.map((f) => (
              <li key={f}>{f}</li>
            ))}
          </ul>
        </article>

        <article className="pricing-card pricing-card--pro">
          <h2>{copy.pro.name}</h2>
          <p className="pricing-price">
            {period === "year"
              ? copy.pro.yearly(proYearly)
              : copy.pro.monthly(proMonthly)}
          </p>
          <ul>
            {copy.pro.features.map((f) => (
              <li key={f}>{f}</li>
            ))}
          </ul>
          <button
            className="pricing-cta"
            onClick={handleUpgrade}
            disabled={inFlight}
          >
            {inFlight ? copy.pro.ctaInFlight : copy.pro.cta}
          </button>
          <p className="pricing-trial">{copy.pro.trial}</p>
          {error ? <p className="pricing-error">{error}</p> : null}
        </article>
      </div>
    </section>
  );
}
