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
    perMonth: string;
    perYear: string;
    autoRenew: (amount: string, per: string) => string;
    recurringConsent: (amount: string, per: string) => string;
    agreementLink: string;
    privacyLink: string;
    conversionNotice: string;
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
        "Wai automation + MCP access",
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
    perMonth: "/ month",
    perYear: "/ year",
    autoRenew: (amount, per) => `Renews automatically: ${amount} ${per} until you cancel.`,
    recurringConsent: (amount, per) =>
      `I agree to recurring automatic charges of ${amount} ${per} until I cancel, ` +
      "and to the processing of my personal data:",
    agreementLink: "Subscription agreement",
    privacyLink: "Privacy Policy",
    conversionNotice: "Charged in RUB; your card issuer may convert at its own rate.",
  },
  ru: {
    heading: "Простые цены.",
    sub: "Бесплатно для повседневных голосовых заметок. Pro — когда WaiComputer нужен везде.",
    monthly: "Помесячно",
    yearly: "Годовая",
    save: "−20%",
    free: {
      name: "Бесплатный",
      price: "0 ₽",
      features: [
        "3 000 транскрибированных слов в неделю",
        "Память с поиском за 30 дней",
        "ИИ-сводка к каждой записи",
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
        "Автоматизация Wai + доступ к MCP",
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
    perMonth: "в месяц",
    perYear: "в год",
    autoRenew: (amount, per) =>
      `Продлевается автоматически: ${amount} ${per}, пока вы не отмените.`,
    recurringConsent: (amount, per) =>
      `Я соглашаюсь на регулярное автоматическое списание ${amount} ${per} ` +
      "до отмены подписки и на обработку персональных данных согласно:",
    agreementLink: "Соглашение о подписке",
    privacyLink: "Политика конфиденциальности",
    conversionNotice:
      "Оплата в рублях; банк-эмитент карты может конвертировать сумму по своему курсу.",
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
  const [acceptedRecurring, setAcceptedRecurring] = useState(false);

  // The marketing site can render pricing without hitting the API — these are
  // the canonical sandbox-and-launch numbers from the v1.0 billing migration.
  const rubMonthly = "999 ₽";
  const rubYearly = "7 999 ₽";
  const usdMonthly = "$12";
  const usdYearly = "$96";
  const useRub = currency === "rub" && provider === "tinkoff";
  const proMonthly = useRub ? rubMonthly : usdMonthly;
  const proYearly = useRub ? rubYearly : usdYearly;
  // The T-Bank rail needs explicit recurrent consent before checkout; Stripe
  // (USD) is exempt and issues its own receipts.
  const requiresRecurringConsent = provider === "tinkoff";
  const consentAmount = period === "year" ? proYearly : proMonthly;
  const consentPer = period === "year" ? copy.perYear : copy.perMonth;

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
        accepted_recurring_terms: provider === "tinkoff" ? acceptedRecurring : false,
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
          {requiresRecurringConsent ? (
            <div className="pricing-consent">
              <p
                style={{
                  margin: 0,
                  fontSize: "0.85rem",
                  color: "var(--ink-soft, #666)",
                }}
              >
                {copy.autoRenew(consentAmount, consentPer)}
              </p>
              <label
                style={{
                  display: "flex",
                  gap: "0.5rem",
                  alignItems: "flex-start",
                  fontSize: "0.85rem",
                  textAlign: "left",
                }}
              >
                <input
                  type="checkbox"
                  checked={acceptedRecurring}
                  onChange={(event) => setAcceptedRecurring(event.target.checked)}
                  style={{ marginTop: "0.2rem" }}
                />
                <span>
                  {copy.recurringConsent(consentAmount, consentPer)}{" "}
                  <Link href="/ru/recurrent" target="_blank" rel="noopener noreferrer">
                    {copy.agreementLink}
                  </Link>
                  {" · "}
                  <Link href="/ru/privacy" target="_blank" rel="noopener noreferrer">
                    {copy.privacyLink}
                  </Link>
                </span>
              </label>
              <p
                style={{
                  margin: 0,
                  fontSize: "0.78rem",
                  color: "var(--ink-soft, #666)",
                }}
              >
                {copy.conversionNotice}
              </p>
            </div>
          ) : null}
          <button
            className="pricing-cta"
            onClick={handleUpgrade}
            disabled={
              inFlight || (signedIn && requiresRecurringConsent && !acceptedRecurring)
            }
          >
            {inFlight ? copy.pro.ctaInFlight : signedIn ? copy.pro.cta : copy.signInPrompt}
          </button>
          {error ? <p className="pricing-error">{error}</p> : null}
        </article>
      </div>
    </section>
  );
}
