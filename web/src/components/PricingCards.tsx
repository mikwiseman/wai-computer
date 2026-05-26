"use client";

import { useState } from "react";
import Link from "next/link";
import { createBillingCheckout } from "@/lib/billing";

type Locale = "en" | "ru";

type Currency = "usd" | "rub";

type Provider = "tinkoff" | "stripe";

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
      cta: string;
    };
    pro: {
      name: string;
      monthly: (amount: string) => string;
      yearly: (amount: string) => string;
      features: string[];
      cta: string;
      ctaInFlight: string;
      vatNotice?: string;
    };
    signInPrompt: string;
    payWith: string;
    providerTinkoff: string;
    providerStripe: string;
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
        "3,000 transcribed words per week",
        "30-day searchable memory",
        "AI summaries on every recording",
        "Live dictation + meeting capture",
      ],
      cta: "Get started free",
    },
    pro: {
      name: "Pro",
      monthly: (a) => `${a} / month`,
      yearly: (a) => `${a} / year`,
      features: [
        "No weekly word cap",
        "Permanent searchable memory",
        "Agents + MCP access",
        "Advanced search across everything",
        "Priority support",
      ],
      cta: "Upgrade to Pro",
      ctaInFlight: "Opening checkout…",
    },
    signInPrompt: "Sign in to upgrade",
    payWith: "Pay with",
    providerTinkoff: "RUB via T-Bank",
    providerStripe: "USD via Stripe",
  },
  ru: {
    heading: "Простые цены.",
    sub: "Бесплатно для повседневных голосовых заметок. Pro — когда нужен везде.",
    monthly: "Помесячно",
    yearly: "Годовая",
    save: "−20%",
    free: {
      name: "Бесплатный",
      price: "0 ₽",
      features: [
        "3 000 транскрибированных слов в неделю",
        "Память с поиском за 30 дней",
        "AI-сводка к каждой записи",
        "Живая диктовка и запись встреч",
      ],
      cta: "Начать бесплатно",
    },
    pro: {
      name: "Pro",
      monthly: (a) => `${a} / мес`,
      yearly: (a) => `${a} / год`,
      features: [
        "Без недельного лимита на слова",
        "Постоянная память с поиском",
        "Агенты + доступ к MCP",
        "Расширенный поиск по всему",
        "Приоритетная поддержка",
      ],
      cta: "Оформить Pro",
      ctaInFlight: "Открываем оплату…",
      vatNotice: "включая НДС",
    },
    signInPrompt: "Войдите, чтобы оформить Pro",
    payWith: "Оплата через",
    providerTinkoff: "RUB через Т-Банк",
    providerStripe: "USD через Stripe",
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
  // RU UI users can pay with T-Bank (RUB) or Stripe (USD). Other locales always Stripe.
  const [provider, setProvider] = useState<Provider>(
    locale === "ru" && currency === "rub" ? "tinkoff" : "stripe",
  );
  const [inFlight, setInFlight] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The marketing site can render pricing without hitting the API — these are
  // the canonical sandbox-and-launch numbers from the v1.0 billing migration.
  const rubMonthly = "999 ₽";
  const rubYearly = "7 999 ₽";
  const usdMonthly = "$12";
  const usdYearly = "$96";
  const useRub = currency === "rub" && provider === "tinkoff";
  const proMonthly = useRub ? rubMonthly : usdMonthly;
  const proYearly = useRub ? rubYearly : usdYearly;

  async function handleUpgrade() {
    setError(null);
    if (!signedIn) {
      window.location.href = `${loginPath}?returnTo=/billing`;
      return;
    }
    setInFlight(true);
    try {
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
          <Link className="pricing-cta pricing-cta--free" href={signedIn ? "/dashboard" : "/register"}>
            {copy.free.cta}
          </Link>
        </article>

        <article className="pricing-card pricing-card--pro">
          <h2>{copy.pro.name}</h2>
          <p className="pricing-price">
            {period === "year"
              ? copy.pro.yearly(proYearly)
              : copy.pro.monthly(proMonthly)}
          </p>
          {useRub && copy.pro.vatNotice ? (
            <p className="pricing-vat">{copy.pro.vatNotice}</p>
          ) : null}
          <ul>
            {copy.pro.features.map((f) => (
              <li key={f}>{f}</li>
            ))}
          </ul>
          {locale === "ru" && currency === "rub" ? (
            <fieldset className="pricing-provider" aria-label={copy.payWith}>
              <legend>{copy.payWith}</legend>
              <label>
                <input
                  type="radio"
                  name="pricing-provider"
                  value="tinkoff"
                  checked={provider === "tinkoff"}
                  onChange={() => setProvider("tinkoff")}
                />
                <span>{copy.providerTinkoff}</span>
              </label>
              <label>
                <input
                  type="radio"
                  name="pricing-provider"
                  value="stripe"
                  checked={provider === "stripe"}
                  onChange={() => setProvider("stripe")}
                />
                <span>{copy.providerStripe}</span>
              </label>
            </fieldset>
          ) : null}
          <button
            className="pricing-cta"
            onClick={handleUpgrade}
            disabled={inFlight}
          >
            {inFlight ? copy.pro.ctaInFlight : signedIn ? copy.pro.cta : copy.signInPrompt}
          </button>
          {error ? <p className="pricing-error">{error}</p> : null}
        </article>
      </div>
    </section>
  );
}
