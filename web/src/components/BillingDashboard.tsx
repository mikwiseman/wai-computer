"use client";

import { useEffect, useState } from "react";
import {
  cancelBillingSubscription,
  createBillingCheckout,
  getBillingSubscription,
  getBillingUsage,
  type BillingSubscription,
  type BillingUsage,
} from "@/lib/billing";

type Locale = "en" | "ru";

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
    loadError: string;
    loading: string;
  }
> = {
  en: {
    heading: "Billing",
    planLabel: "Plan",
    statusLabel: "Status",
    renewsLabel: "Renews",
    endsLabel: "Ends",
    wordsLabel: "Words this week",
    unlimited: "Unlimited (Pro)",
    resets: "Resets Sunday at 00:00 UTC",
    upgrade: "Upgrade to Pro",
    cancel: "Cancel subscription",
    cancelling: "Cancelling…",
    cancelledNotice: (d) => `Pro is active through ${d}.`,
    loadError: "Couldn't load billing info.",
    loading: "Loading…",
  },
  ru: {
    heading: "Подписка",
    planLabel: "Тариф",
    statusLabel: "Статус",
    renewsLabel: "Продление",
    endsLabel: "Заканчивается",
    wordsLabel: "Слов на этой неделе",
    unlimited: "Без ограничений (Pro)",
    resets: "Сбрасывается в воскресенье в 00:00 UTC",
    upgrade: "Оформить Pro",
    cancel: "Отменить подписку",
    cancelling: "Отменяем…",
    cancelledNotice: (d) => `Pro активен до ${d}.`,
    loadError: "Не удалось загрузить данные подписки.",
    loading: "Загрузка…",
  },
};

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
  const fraction = usage.words_cap
    ? Math.min(1, usage.words_used / usage.words_cap)
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
      const provider = currency === "rub" ? "tinkoff" : "stripe";
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
          <dd>{sub.status}</dd>
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
        {usage.words_cap === null ? (
          <p>{copy.unlimited}</p>
        ) : (
          <>
            <p>
              {usage.words_used.toLocaleString()} /{" "}
              {usage.words_cap.toLocaleString()}
            </p>
            <progress max={1} value={fraction} />
            <p className="billing-caption">{copy.resets}</p>
          </>
        )}
      </div>

      {sub.cancel_at_period_end && periodEnd ? (
        <p className="billing-notice">{copy.cancelledNotice(periodEnd)}</p>
      ) : isPro ? (
        <button
          className="billing-cancel"
          onClick={handleCancel}
          disabled={inFlight}
        >
          {inFlight ? copy.cancelling : copy.cancel}
        </button>
      ) : (
        <button
          className="billing-upgrade"
          onClick={handleUpgrade}
          disabled={inFlight}
        >
          {copy.upgrade}
        </button>
      )}
    </section>
  );
}
