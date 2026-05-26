"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  cancelBillingSubscription,
  claimBillingPromoCode,
  createBillingCheckout,
  getBillingSubscription,
  getBillingUsage,
  type BillingSubscription,
  type BillingUsage,
} from "@/lib/billing";

type Locale = "en" | "ru";

type Provider = "tinkoff" | "stripe";

const COPY: Record<
  Locale,
  {
    heading: string;
    planLabel: string;
    statusLabel: string;
    renewsLabel: string;
    endsLabel: string;
    wordsLabel: string;
    unlimited: string;
    resets: string;
    upgrade: string;
    cancel: string;
    cancelling: string;
    cancelledNotice: (date: string) => string;
    confirmHeading: string;
    confirmBody: string;
    confirmYes: string;
    confirmNo: string;
    loadError: string;
    loading: string;
    payWith: string;
    providerTinkoff: string;
    providerStripe: string;
    promoLabel: string;
    promoPlaceholder: string;
    promoApply: string;
    promoApplying: string;
    promoApplied: string;
    promoNotFound: string;
    promoActiveSubscription: string;
    promoExpired: string;
    promoExhausted: string;
    promoAlreadyRedeemed: string;
    invoicesHeading: string;
    invoicesEmpty: string;
    backToDashboard: string;
    statuses: Record<string, string>;
  }
> = {
  en: {
    heading: "Billing",
    planLabel: "Plan",
    statusLabel: "Status",
    renewsLabel: "Renews",
    endsLabel: "Ends",
    wordsLabel: "Words this week",
    unlimited: "No weekly word cap",
    resets: "Resets Sunday at 00:00 UTC",
    upgrade: "Upgrade to Pro",
    cancel: "Cancel subscription",
    cancelling: "Cancelling…",
    cancelledNotice: (d) => `Pro is active through ${d}.`,
    confirmHeading: "Cancel your Pro subscription?",
    confirmBody:
      "You'll keep Pro features until the end of the current billing period. You can resubscribe at any time.",
    confirmYes: "Yes, cancel",
    confirmNo: "Keep Pro",
    loadError: "Couldn't load billing info.",
    loading: "Loading…",
    payWith: "Pay with",
    providerTinkoff: "RUB via T-Bank",
    providerStripe: "USD via Stripe",
    promoLabel: "Promo code",
    promoPlaceholder: "Enter promo code",
    promoApply: "Apply",
    promoApplying: "Applying...",
    promoApplied: "Promo code applied.",
    promoNotFound: "Promo code not found.",
    promoActiveSubscription: "You already have an active subscription.",
    promoExpired: "Promo code expired.",
    promoExhausted: "Promo code has already been fully used.",
    promoAlreadyRedeemed: "You already redeemed this promo code.",
    invoicesHeading: "Invoices",
    invoicesEmpty: "We'll show invoices here as soon as Stripe is wired.",
    backToDashboard: "← Back to dashboard",
    statuses: {
      active: "Active",
      trialing: "Trialing",
      canceled: "Canceled",
      past_due: "Past due",
      incomplete: "Incomplete",
      unpaid: "Unpaid",
    },
  },
  ru: {
    heading: "Подписка",
    planLabel: "Тариф",
    statusLabel: "Статус",
    renewsLabel: "Продление",
    endsLabel: "Заканчивается",
    wordsLabel: "Слов на этой неделе",
    unlimited: "Без недельного лимита",
    resets: "Сбрасывается в воскресенье в 00:00 UTC",
    upgrade: "Оформить Pro",
    cancel: "Отменить подписку",
    cancelling: "Отменяем…",
    cancelledNotice: (d) => `Pro активен до ${d}.`,
    confirmHeading: "Отменить подписку Pro?",
    confirmBody:
      "Возможности Pro останутся до конца оплаченного периода. Вы сможете снова оформить подписку в любое время.",
    confirmYes: "Да, отменить",
    confirmNo: "Оставить Pro",
    loadError: "Не удалось загрузить данные подписки.",
    loading: "Загрузка…",
    payWith: "Оплата через",
    providerTinkoff: "RUB через Т-Банк",
    providerStripe: "USD через Stripe",
    promoLabel: "Промокод",
    promoPlaceholder: "Введи промокод",
    promoApply: "Применить",
    promoApplying: "Применяем...",
    promoApplied: "Промокод применён.",
    promoNotFound: "Промокод не найден.",
    promoActiveSubscription: "У тебя уже есть активная подписка.",
    promoExpired: "Срок действия промокода истёк.",
    promoExhausted: "Промокод уже исчерпан.",
    promoAlreadyRedeemed: "Ты уже использовал этот промокод.",
    invoicesHeading: "Счета",
    invoicesEmpty: "Здесь появятся счета, как только мы подключим выгрузку из Stripe.",
    backToDashboard: "← Назад в кабинет",
    statuses: {
      active: "Активна",
      trialing: "Пробная",
      canceled: "Отменена",
      past_due: "Просрочена",
      incomplete: "Не завершена",
      unpaid: "Не оплачена",
    },
  },
};

function localizeBillingError(error: unknown, locale: Locale): string {
  const copy = COPY[locale];
  const message = error instanceof Error ? error.message.trim() : "";
  if (message === "Promo code not found") {
    return copy.promoNotFound;
  }
  if (message === "Active subscription already exists") {
    return copy.promoActiveSubscription;
  }
  if (message === "Promo code expired") {
    return copy.promoExpired;
  }
  if (message === "Promo code exhausted") {
    return copy.promoExhausted;
  }
  if (message === "Promo code already redeemed") {
    return copy.promoAlreadyRedeemed;
  }
  if (message.length > 0) {
    return message;
  }
  return copy.loadError;
}

function localizeStatus(
  status: string,
  copy: (typeof COPY)[Locale],
): string {
  return copy.statuses[status] ?? status;
}

interface Props {
  locale: Locale;
  currency: "usd" | "rub";
}

export function BillingDashboard({ locale, currency }: Props) {
  const copy = COPY[locale];
  const [sub, setSub] = useState<BillingSubscription | null>(null);
  const [usage, setUsage] = useState<BillingUsage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [inFlight, setInFlight] = useState(false);
  const [promoCode, setPromoCode] = useState("");
  const [promoInFlight, setPromoInFlight] = useState(false);
  const [promoMessage, setPromoMessage] = useState<string | null>(null);
  const [promoError, setPromoError] = useState<string | null>(null);
  const [confirmingCancel, setConfirmingCancel] = useState(false);
  // RU UI users choose T-Bank or Stripe; other locales lock to Stripe.
  const [provider, setProvider] = useState<Provider>(
    locale === "ru" && currency === "rub" ? "tinkoff" : "stripe",
  );

  useEffect(() => {
    Promise.all([getBillingSubscription(), getBillingUsage()])
      .then(([s, u]) => {
        setSub(s);
        setUsage(u);
      })
      .catch(() => setError(copy.loadError));
  }, [copy.loadError]);

  if (error) return <p className="billing-error">{error}</p>;
  if (!sub || !usage) return <p>{copy.loading}</p>;

  const isPro = sub.plan.code === "pro" && sub.status !== "canceled";
  const displayCap = isPro ? null : usage.words_cap ?? sub.plan.word_cap_per_week;
  const fraction = displayCap
    ? Math.min(1, usage.words_used / displayCap)
    : 0;
  const periodEnd = sub.current_period_end
    ? new Date(sub.current_period_end).toLocaleDateString(
        locale === "ru" ? "ru-RU" : "en-US",
        { year: "numeric", month: "long", day: "numeric" },
      )
    : null;

  async function handleUpgrade() {
    setInFlight(true);
    try {
      const session = await createBillingCheckout({
        plan: "pro",
        period: "month",
        provider,
      });
      window.location.href = session.checkout_url;
    } catch {
      setInFlight(false);
      setError(copy.loadError);
    }
  }

  async function handleCancel() {
    setInFlight(true);
    setConfirmingCancel(false);
    try {
      await cancelBillingSubscription();
      const fresh = await getBillingSubscription();
      setSub(fresh);
    } catch {
      setError(copy.loadError);
    } finally {
      setInFlight(false);
    }
  }

  async function handlePromoApply() {
    const code = promoCode.trim();
    if (!code) return;
    setPromoInFlight(true);
    setError(null);
    setPromoMessage(null);
    setPromoError(null);
    try {
      const fresh = await claimBillingPromoCode(code);
      setSub(fresh);
      const freshUsage = await getBillingUsage();
      setUsage(freshUsage);
      setPromoCode("");
      setPromoMessage(copy.promoApplied);
    } catch (error: unknown) {
      setPromoError(localizeBillingError(error, locale));
    } finally {
      setPromoInFlight(false);
    }
  }

  return (
    <section className="billing-dashboard">
      <h1>{copy.heading}</h1>

      <dl className="billing-meta">
        <div>
          <dt>{copy.planLabel}</dt>
          <dd>{sub.plan.name}</dd>
        </div>
        <div>
          <dt>{copy.statusLabel}</dt>
          <dd>{localizeStatus(sub.status, copy)}</dd>
        </div>
        {periodEnd ? (
          <div>
            <dt>{sub.cancel_at_period_end ? copy.endsLabel : copy.renewsLabel}</dt>
            <dd>{periodEnd}</dd>
          </div>
        ) : null}
      </dl>

      <div className="billing-usage">
        <h2>{copy.wordsLabel}</h2>
        {displayCap === null ? (
          <p>{copy.unlimited}</p>
        ) : (
          <>
            <p>
              {usage.words_used.toLocaleString()} /{" "}
              {displayCap.toLocaleString()}
            </p>
            <progress max={1} value={fraction} />
            <p className="billing-caption">{copy.resets}</p>
          </>
        )}
      </div>

      {sub.cancel_at_period_end && periodEnd ? (
        <p className="billing-notice">{copy.cancelledNotice(periodEnd)}</p>
      ) : isPro ? (
        confirmingCancel ? (
          <div
            role="alertdialog"
            aria-labelledby="billing-cancel-heading"
            style={{
              border: "1px solid var(--border)",
              borderRadius: "8px",
              padding: "1rem 1.1rem",
              background: "var(--panel-subtle)",
              display: "flex",
              flexDirection: "column",
              gap: "0.6rem",
            }}
          >
            <h3 id="billing-cancel-heading" style={{ margin: 0, fontSize: "1.05rem" }}>
              {copy.confirmHeading}
            </h3>
            <p style={{ margin: 0, color: "var(--ink-soft)" }}>{copy.confirmBody}</p>
            <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap" }}>
              <button
                type="button"
                className="billing-cancel"
                onClick={handleCancel}
                disabled={inFlight}
              >
                {inFlight ? copy.cancelling : copy.confirmYes}
              </button>
              <button
                type="button"
                className="ghost-button"
                onClick={() => setConfirmingCancel(false)}
                disabled={inFlight}
              >
                {copy.confirmNo}
              </button>
            </div>
          </div>
        ) : (
          <button
            type="button"
            className="billing-cancel"
            onClick={() => setConfirmingCancel(true)}
            disabled={inFlight}
          >
            {copy.cancel}
          </button>
        )
      ) : (
        <>
          {locale === "ru" && currency === "rub" ? (
            <fieldset className="billing-provider" aria-label={copy.payWith}>
              <legend>{copy.payWith}</legend>
              <label>
                <input
                  type="radio"
                  name="billing-provider"
                  value="tinkoff"
                  checked={provider === "tinkoff"}
                  onChange={() => setProvider("tinkoff")}
                />
                <span>{copy.providerTinkoff}</span>
              </label>
              <label>
                <input
                  type="radio"
                  name="billing-provider"
                  value="stripe"
                  checked={provider === "stripe"}
                  onChange={() => setProvider("stripe")}
                />
                <span>{copy.providerStripe}</span>
              </label>
            </fieldset>
          ) : null}
          <button
            className="billing-upgrade"
            onClick={handleUpgrade}
            disabled={inFlight || promoInFlight}
          >
            {copy.upgrade}
          </button>
          <form
            className="billing-promo"
            onSubmit={(event) => {
              event.preventDefault();
              void handlePromoApply();
            }}
          >
            <label>
              <span>{copy.promoLabel}</span>
              <input
                value={promoCode}
                onChange={(event) => setPromoCode(event.target.value)}
                placeholder={copy.promoPlaceholder}
                disabled={inFlight || promoInFlight}
              />
            </label>
            <button
              type="submit"
              disabled={inFlight || promoInFlight || promoCode.trim().length === 0}
            >
              {promoInFlight ? copy.promoApplying : copy.promoApply}
            </button>
            {promoMessage ? <p className="billing-notice">{promoMessage}</p> : null}
            {promoError ? <p className="billing-error">{promoError}</p> : null}
          </form>
        </>
      )}

      <section
        aria-labelledby="billing-invoices-heading"
        style={{
          marginTop: "1.4rem",
          paddingTop: "1.4rem",
          borderTop: "1px solid var(--border)",
        }}
      >
        <h2 id="billing-invoices-heading" style={{ margin: 0, fontSize: "1rem" }}>
          {copy.invoicesHeading}
        </h2>
        <p className="billing-caption" style={{ marginTop: "0.4rem" }}>
          {copy.invoicesEmpty}
        </p>
      </section>

      <p style={{ marginTop: "1.4rem" }}>
        <Link href="/dashboard">{copy.backToDashboard}</Link>
      </p>
    </section>
  );
}
