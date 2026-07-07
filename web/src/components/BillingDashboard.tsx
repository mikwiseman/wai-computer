"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  cancelBillingSubscription,
  claimBillingPromoCode,
  createBillingCheckout,
  getBillingInvoices,
  getBillingSubscription,
  getBillingUsage,
  listBillingPlans,
  openBillingPortal,
  switchBillingPlan,
  type BillingInvoice,
  type BillingPlan,
  type BillingSubscription,
  type BillingUsage,
} from "@/lib/billing";

type Locale = "en" | "ru";

type Provider = "tinkoff" | "stripe";

const COPY: Record<
  Locale,
  {
    heading: string;
    backToDashboard: string;
    nextChargeLabel: (amount: string, date: string) => string;
    nextChargeTrial: (date: string) => string;
    nextChargeFree: string;
    cancelledThrough: (date: string) => string;
    canceledHeading: string;
    planLabel: string;
    statusLabel: string;
    renewsLabel: string;
    endsLabel: string;
    switchTo: string;
    switchMonthly: string;
    switchYearly: string;
    switchApply: string;
    switchApplying: string;
    switchAccepted: string;
    switchSameNotice: string;
    paymentMethodHeading: string;
    paymentMethodHint: string;
    paymentMethodUpdate: string;
    paymentMethodUpdating: string;
    paymentMethodFallback: string;
    contactSupport: string;
    invoicesHeading: string;
    invoicesEmpty: string;
    invoiceDate: string;
    invoiceDescription: string;
    invoiceAmount: string;
    invoiceStatus: string;
    invoiceReceipt: string;
    invoiceDefaultDescription: string;
    wordsLabel: string;
    unlimited: string;
    resets: string;
    upgrade: string;
    cancelInline: string;
    cancelling: string;
    confirmHeading: string;
    confirmBody: string;
    confirmYes: string;
    confirmNo: string;
    loadError: string;
    loading: string;
    payWith: string;
    providerTinkoff: string;
    providerStripe: string;
    billingPeriodLabel: string;
    perMonth: string;
    perYear: string;
    vatIncluded: string;
    autoRenew: (amount: string, per: string) => string;
    recurringConsent: (amount: string, per: string) => string;
    agreementLink: string;
    privacyLink: string;
    conversionNotice: string;
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
    promoNotApplicablePeriod: string;
    promoGenericError: string;
    statuses: Record<string, string>;
    invoiceStatuses: Record<string, string>;
  }
> = {
  en: {
    heading: "Billing",
    backToDashboard: "← Back to dashboard",
    nextChargeLabel: (amount, date) => `Next charge ${amount} on ${date}`,
    nextChargeTrial: (date) => `Free trial — first charge on ${date}`,
    nextChargeFree: "You're on the Free plan — no charges scheduled.",
    cancelledThrough: (date) => `Pro is active through ${date}, then ends.`,
    canceledHeading: "Subscription canceled",
    planLabel: "Plan",
    statusLabel: "Status",
    renewsLabel: "Renews",
    endsLabel: "Ends",
    switchTo: "Switch plan",
    switchMonthly: "Monthly",
    switchYearly: "Yearly",
    switchApply: "Switch",
    switchApplying: "Switching…",
    switchAccepted:
      "Got it. Our team will switch your plan on the next billing cycle.",
    switchSameNotice: "You're already on this period.",
    paymentMethodHeading: "Payment method",
    paymentMethodHint:
      "Update your card, manage your subscription, or download invoices on Stripe.",
    paymentMethodUpdate: "Manage subscription",
    paymentMethodUpdating: "Opening Stripe…",
    paymentMethodFallback:
      "Couldn't reach Stripe right now — please try again, or contact support.",
    contactSupport: "Contact support",
    invoicesHeading: "Invoices",
    invoicesEmpty: "No invoices yet — your first charge will appear here.",
    invoiceDate: "Date",
    invoiceDescription: "Description",
    invoiceAmount: "Amount",
    invoiceStatus: "Status",
    invoiceReceipt: "Receipt",
    invoiceDefaultDescription: "Pro subscription",
    wordsLabel: "Words this week",
    unlimited: "No weekly word cap",
    resets: "Resets Sunday at 00:00 UTC",
    upgrade: "Upgrade to Pro",
    cancelInline: "Cancel subscription",
    cancelling: "Cancelling…",
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
    billingPeriodLabel: "Billing period",
    perMonth: "/ month",
    perYear: "/ year",
    vatIncluded: "",
    autoRenew: (amount, per) => `Renews automatically: ${amount} ${per} until you cancel.`,
    recurringConsent: (amount, per) =>
      `I agree to recurring automatic charges of ${amount} ${per} until I cancel, ` +
      "and to the processing of my personal data:",
    agreementLink: "Subscription agreement",
    privacyLink: "Privacy Policy",
    conversionNotice: "Charged in RUB; your card issuer may convert at its own rate.",
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
    promoNotApplicablePeriod: "This promo code does not apply to the selected billing period.",
    promoGenericError: "This promo code can't be applied.",
    statuses: {
      active: "Active",
      trialing: "Trialing",
      canceled: "Canceled",
      past_due: "Past due",
      incomplete: "Incomplete",
      unpaid: "Unpaid",
      free: "Free",
      expired: "Expired",
    },
    invoiceStatuses: {
      paid: "Paid",
      open: "Open",
      void: "Void",
      uncollectible: "Uncollectible",
      draft: "Draft",
      failed: "Failed",
    },
  },
  ru: {
    heading: "Подписка",
    backToDashboard: "← Назад в кабинет",
    nextChargeLabel: (amount, date) => `Следующее списание — ${amount}, ${date}`,
    nextChargeTrial: (date) => `Пробный период — первое списание ${date}`,
    nextChargeFree: "Сейчас активен бесплатный тариф — списаний не будет.",
    cancelledThrough: (date) =>
      `Pro активен до ${date}, затем подписка закончится.`,
    canceledHeading: "Подписка отменена",
    planLabel: "Тариф",
    statusLabel: "Статус",
    renewsLabel: "Продление",
    endsLabel: "Заканчивается",
    switchTo: "Сменить тариф",
    switchMonthly: "Помесячно",
    switchYearly: "На год",
    switchApply: "Сменить",
    switchApplying: "Меняем…",
    switchAccepted:
      "Принято. Мы переключим ваш тариф на следующий расчётный период.",
    switchSameNotice: "Этот период уже активен.",
    paymentMethodHeading: "Способ оплаты",
    paymentMethodHint:
      "Обновите карту, управляйте подпиской и скачивайте счета прямо в Stripe.",
    paymentMethodUpdate: "Управлять подпиской",
    paymentMethodUpdating: "Открываем Stripe…",
    paymentMethodFallback:
      "Не удалось открыть Stripe. Попробуйте ещё раз или напишите в поддержку.",
    contactSupport: "Написать в поддержку",
    invoicesHeading: "Счета",
    invoicesEmpty: "Счетов пока нет — первое списание появится здесь.",
    invoiceDate: "Дата",
    invoiceDescription: "Описание",
    invoiceAmount: "Сумма",
    invoiceStatus: "Статус",
    invoiceReceipt: "Чек",
    invoiceDefaultDescription: "Подписка Pro",
    wordsLabel: "Слов на этой неделе",
    unlimited: "Без недельного лимита",
    resets: "Сбрасывается в воскресенье в 00:00 UTC",
    upgrade: "Оформить Pro",
    cancelInline: "Отменить подписку",
    cancelling: "Отменяем…",
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
    billingPeriodLabel: "Период оплаты",
    perMonth: "в месяц",
    perYear: "в год",
    vatIncluded: "включая НДС",
    autoRenew: (amount, per) =>
      `Продлевается автоматически: ${amount} ${per}, пока вы не отмените.`,
    recurringConsent: (amount, per) =>
      `Я соглашаюсь на регулярное автоматическое списание ${amount} ${per} ` +
      "до отмены подписки и на обработку персональных данных согласно:",
    agreementLink: "Соглашение о подписке",
    privacyLink: "Политика конфиденциальности",
    conversionNotice:
      "Оплата в рублях; банк-эмитент карты может конвертировать сумму по своему курсу.",
    promoLabel: "Промокод",
    promoPlaceholder: "Введите промокод",
    promoApply: "Применить",
    promoApplying: "Применяем...",
    promoApplied: "Промокод применён.",
    promoNotFound: "Промокод не найден.",
    promoActiveSubscription: "У вас уже есть активная подписка.",
    promoExpired: "Срок действия промокода истёк.",
    promoExhausted: "Промокод уже исчерпан.",
    promoAlreadyRedeemed: "Вы уже использовали этот промокод.",
    promoNotApplicablePeriod: "Промокод не применим к выбранному периоду оплаты.",
    promoGenericError: "Этот промокод нельзя применить.",
    statuses: {
      active: "Активна",
      trialing: "Пробная",
      canceled: "Отменена",
      past_due: "Просрочена",
      incomplete: "Не завершена",
      unpaid: "Не оплачена",
      free: "Бесплатный",
      expired: "Истекла",
    },
    invoiceStatuses: {
      paid: "Оплачен",
      open: "Открыт",
      void: "Аннулирован",
      uncollectible: "Не оплачен",
      draft: "Черновик",
      failed: "Ошибка",
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
  if (message === "Promo code does not apply to selected period") {
    return copy.promoNotApplicablePeriod;
  }
  // Any other promo-code error (incl. server-side 500s) must not leak raw English
  // into the localized UI — surface a generic localized message instead.
  if (message.startsWith("Promo code")) {
    return copy.promoGenericError;
  }
  if (message.length > 0) {
    return message;
  }
  return copy.loadError;
}

function isCheckoutPromoError(error: unknown): boolean {
  return error instanceof Error && error.message.trim() === "Promo code applies to checkout";
}

function localizeStatus(
  status: string,
  copy: (typeof COPY)[Locale],
): string {
  return copy.statuses[status] ?? status;
}

function localizeInvoiceStatus(
  status: string,
  copy: (typeof COPY)[Locale],
): string {
  return copy.invoiceStatuses[status] ?? status;
}

function formatAmount(
  amount: number | null | undefined,
  currency: string | null | undefined,
  locale: Locale,
): string {
  if (amount == null) {
    return "—";
  }
  const code = (currency ?? "USD").toUpperCase();
  try {
    return new Intl.NumberFormat(locale === "ru" ? "ru-RU" : "en-US", {
      style: "currency",
      currency: code,
      maximumFractionDigits: code === "RUB" ? 0 : 2,
    }).format(amount);
  } catch {
    return `${amount} ${code}`;
  }
}

function formatDate(iso: string | null | undefined, locale: Locale): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleDateString(locale === "ru" ? "ru-RU" : "en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

// Inline-style constants kept at module scope so re-renders don't recreate them.
const BANNER_STYLE: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: "0.25rem",
  padding: "1rem 1.15rem",
  borderRadius: "var(--radius-md)",
  background: "var(--accent-soft)",
  border: "1px solid var(--border)",
  marginBottom: "1.6rem",
};

const BANNER_TITLE_STYLE: React.CSSProperties = {
  margin: 0,
  fontSize: "1.05rem",
  fontWeight: 600,
  color: "var(--ink)",
};

const BANNER_BODY_STYLE: React.CSSProperties = {
  margin: 0,
  color: "var(--ink-soft)",
  fontSize: "0.9rem",
};

const CARD_STYLE: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: "0.85rem",
  padding: "1.15rem 1.2rem",
  borderRadius: "var(--radius-md)",
  background: "var(--panel)",
  border: "1px solid var(--border)",
  marginBottom: "1.2rem",
};

const CARD_HEADER_STYLE: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
  flexWrap: "wrap",
  gap: "0.5rem",
};

const CARD_TITLE_STYLE: React.CSSProperties = {
  margin: 0,
  fontSize: "1rem",
  fontWeight: 600,
};

const STATUS_PILL_STYLE: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  padding: "0.18rem 0.6rem",
  borderRadius: "var(--radius-pill)",
  background: "var(--panel-subtle)",
  border: "1px solid var(--border)",
  fontSize: "0.78rem",
  fontWeight: 600,
  color: "var(--ink-soft)",
  letterSpacing: "0.02em",
};

const SWITCH_ROW_STYLE: React.CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  alignItems: "center",
  gap: "0.5rem",
};

const SWITCH_SELECT_STYLE: React.CSSProperties = {
  padding: "0.4rem 0.6rem",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--border)",
  background: "var(--panel-subtle)",
  color: "var(--ink)",
  minHeight: "38px",
};

const SWITCH_BUTTON_STYLE: React.CSSProperties = {
  padding: "0.45rem 0.95rem",
  borderRadius: "var(--radius-sm)",
  border: "1px solid var(--border)",
  background: "var(--panel-subtle)",
  color: "var(--ink)",
  cursor: "pointer",
  minHeight: "38px",
};

const SUBTLE_LINK_STYLE: React.CSSProperties = {
  background: "none",
  border: 0,
  padding: 0,
  color: "var(--ink-soft)",
  fontSize: "0.85rem",
  cursor: "pointer",
  textDecoration: "underline",
};

const CARD_INVOICES_HEADER_STYLE: React.CSSProperties = {
  margin: "0 0 0.6rem",
  fontSize: "1rem",
  fontWeight: 600,
};

const INVOICE_TABLE_STYLE: React.CSSProperties = {
  width: "100%",
  borderCollapse: "collapse",
};

const INVOICE_TH_STYLE: React.CSSProperties = {
  textAlign: "left",
  fontSize: "0.78rem",
  textTransform: "uppercase",
  letterSpacing: "0.04em",
  color: "var(--ink-soft)",
  fontWeight: 600,
  padding: "0.5rem 0.6rem",
  borderBottom: "1px solid var(--border)",
};

const INVOICE_TD_STYLE: React.CSSProperties = {
  padding: "0.55rem 0.6rem",
  borderBottom: "1px solid var(--border)",
  fontSize: "0.92rem",
  verticalAlign: "top",
};

interface Props {
  locale: Locale;
  currency: "usd" | "rub";
}

export function BillingDashboard({ locale, currency }: Props) {
  const copy = COPY[locale];
  const [sub, setSub] = useState<BillingSubscription | null>(null);
  const [usage, setUsage] = useState<BillingUsage | null>(null);
  const [invoices, setInvoices] = useState<BillingInvoice[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [inFlight, setInFlight] = useState(false);
  const [promoCode, setPromoCode] = useState("");
  const [promoInFlight, setPromoInFlight] = useState(false);
  const [promoMessage, setPromoMessage] = useState<string | null>(null);
  const [promoError, setPromoError] = useState<string | null>(null);
  const [confirmingCancel, setConfirmingCancel] = useState(false);
  const [switchPeriod, setSwitchPeriod] = useState<"monthly" | "yearly">(
    "monthly",
  );
  const [switchInFlight, setSwitchInFlight] = useState(false);
  const [switchMessage, setSwitchMessage] = useState<string | null>(null);
  const [portalInFlight, setPortalInFlight] = useState(false);
  const [portalError, setPortalError] = useState<string | null>(null);
  // RU UI users choose T-Bank or Stripe; other locales lock to Stripe.
  const [provider, setProvider] = useState<Provider>(
    locale === "ru" && currency === "rub" ? "tinkoff" : "stripe",
  );
  const [proPlan, setProPlan] = useState<BillingPlan | null>(null);
  const [upgradePeriod, setUpgradePeriod] = useState<"month" | "year">("month");
  const [acceptedRecurring, setAcceptedRecurring] = useState(false);

  useEffect(() => {
    Promise.all([
      getBillingSubscription(),
      getBillingUsage(),
      getBillingInvoices(),
      listBillingPlans(),
    ])
      .then(([s, u, inv, plans]) => {
        setSub(s);
        setUsage(u);
        setInvoices(inv);
        setProPlan(plans.find((p) => p.code === "pro") ?? null);
        const initialPeriod: "monthly" | "yearly" =
          s.billing_period === "year" ? "yearly" : "monthly";
        setSwitchPeriod(initialPeriod);
      })
      .catch(() => setError(copy.loadError));
  }, [copy.loadError]);

  if (error) {
    return (
      <section className="billing-dashboard">
        <p style={{ marginBottom: "1rem" }}>
          <Link href="/dashboard">{copy.backToDashboard}</Link>
        </p>
        <p className="billing-error">{error}</p>
      </section>
    );
  }
  if (!sub || !usage) {
    return (
      <section className="billing-dashboard">
        <p>{copy.loading}</p>
      </section>
    );
  }

  const isPro = sub.plan.code === "pro" && sub.status !== "canceled";
  const displayCap = isPro ? null : usage.words_cap ?? sub.plan.word_cap_per_week;
  const fraction = displayCap
    ? Math.min(1, usage.words_used / displayCap)
    : 0;
  const periodEndLabel = formatDate(sub.current_period_end, locale);
  const trialEndDate = formatDate(sub.trial_end, locale);

  const currentPeriod: "monthly" | "yearly" =
    sub.billing_period === "year" ? "yearly" : "monthly";

  // Upgrade pricing shown BEFORE the pay button, sourced from /billing/plans so
  // it can never drift from the amount actually charged.
  const useRubUpgrade = provider === "tinkoff";
  const upgradeAmountNum = useRubUpgrade
    ? upgradePeriod === "year"
      ? proPlan?.rub_amount_yearly ?? 7999
      : proPlan?.rub_amount_monthly ?? 999
    : upgradePeriod === "year"
      ? proPlan?.usd_amount_yearly ?? 96
      : proPlan?.usd_amount_monthly ?? 12;
  const upgradeAmountStr = formatAmount(
    upgradeAmountNum,
    useRubUpgrade ? "RUB" : "USD",
    locale,
  );
  const upgradePer = upgradePeriod === "year" ? copy.perYear : copy.perMonth;
  // The T-Bank rail requires explicit recurrent consent; Stripe is exempt.
  const requiresRecurringConsent = provider === "tinkoff";

  async function handleUpgrade() {
    setInFlight(true);
    try {
      const session = await createBillingCheckout({
        plan: "pro",
        period: upgradePeriod,
        provider,
        accepted_recurring_terms: provider === "tinkoff" ? acceptedRecurring : false,
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
      if (isCheckoutPromoError(error)) {
        try {
          const session = await createBillingCheckout({
            plan: "pro",
            period: upgradePeriod,
            provider,
            promo_code: code,
            accepted_recurring_terms: provider === "tinkoff" ? acceptedRecurring : false,
          });
          window.location.href = session.checkout_url;
          return;
        } catch (checkoutError: unknown) {
          setPromoError(localizeBillingError(checkoutError, locale));
          return;
        }
      }
      setPromoError(localizeBillingError(error, locale));
    } finally {
      setPromoInFlight(false);
    }
  }

  async function handleOpenPortal() {
    setPortalInFlight(true);
    setPortalError(null);
    try {
      const session = await openBillingPortal();
      window.location.href = session.url;
    } catch {
      setPortalError(copy.paymentMethodFallback);
      setPortalInFlight(false);
    }
  }

  async function handleSwitchPlan() {
    if (switchPeriod === currentPeriod) {
      setSwitchMessage(copy.switchSameNotice);
      return;
    }
    setSwitchInFlight(true);
    setSwitchMessage(null);
    try {
      await switchBillingPlan(switchPeriod);
      setSwitchMessage(copy.switchAccepted);
    } catch {
      setError(copy.loadError);
    } finally {
      setSwitchInFlight(false);
    }
  }

  // ----- Next-charge banner -----
  let bannerNode: React.ReactNode = null;
  if (!isPro) {
    bannerNode = (
      <section aria-labelledby="billing-banner" style={BANNER_STYLE}>
        <h2 id="billing-banner" style={BANNER_TITLE_STYLE}>
          {copy.nextChargeFree}
        </h2>
      </section>
    );
  } else if (sub.cancel_at_period_end && periodEndLabel) {
    bannerNode = (
      <section aria-labelledby="billing-banner" style={BANNER_STYLE}>
        <h2 id="billing-banner" style={BANNER_TITLE_STYLE}>
          {copy.canceledHeading}
        </h2>
        <p style={BANNER_BODY_STYLE}>{copy.cancelledThrough(periodEndLabel)}</p>
      </section>
    );
  } else if (sub.status === "trialing" && trialEndDate) {
    bannerNode = (
      <section aria-labelledby="billing-banner" style={BANNER_STYLE}>
        <h2 id="billing-banner" style={BANNER_TITLE_STYLE}>
          {copy.nextChargeTrial(trialEndDate)}
        </h2>
      </section>
    );
  } else if (sub.next_charge_at && sub.next_charge_amount != null) {
    const amount = formatAmount(
      sub.next_charge_amount,
      sub.next_charge_currency,
      locale,
    );
    const date = formatDate(sub.next_charge_at, locale) ?? "";
    bannerNode = (
      <section aria-labelledby="billing-banner" style={BANNER_STYLE}>
        <h2 id="billing-banner" style={BANNER_TITLE_STYLE}>
          {copy.nextChargeLabel(amount, date)}
        </h2>
      </section>
    );
  }

  return (
    <section className="billing-dashboard">
      <p style={{ marginBottom: "1rem" }}>
        <Link href="/dashboard">{copy.backToDashboard}</Link>
      </p>
      <h1
        style={{
          fontFamily: "var(--font-family-serif)",
          fontWeight: 600,
          fontSize: "clamp(1.75rem, 4vw, 2.25rem)",
          letterSpacing: "-0.012em",
          lineHeight: 1.05,
          color: "var(--ink)",
        }}
      >
        {copy.heading}
      </h1>

      {bannerNode}

      {/* ----- Plan card ----- */}
      <article style={CARD_STYLE} aria-labelledby="billing-plan-card">
        <header style={CARD_HEADER_STYLE}>
          <div>
            <h2 id="billing-plan-card" style={CARD_TITLE_STYLE}>
              {sub.plan.name}
            </h2>
            <p style={{ margin: "0.15rem 0 0", color: "var(--ink-soft)", fontSize: "0.85rem" }}>
              {copy.planLabel}
            </p>
          </div>
          <span style={STATUS_PILL_STYLE}>{localizeStatus(sub.status, copy)}</span>
        </header>

        {periodEndLabel ? (
          <p style={{ margin: 0, color: "var(--ink-soft)", fontSize: "0.9rem" }}>
            {sub.cancel_at_period_end ? copy.endsLabel : copy.renewsLabel}: {periodEndLabel}
          </p>
        ) : null}

        {isPro && !sub.cancel_at_period_end ? (
          <>
            <div style={SWITCH_ROW_STYLE}>
              <label htmlFor="billing-switch-period" style={{ color: "var(--ink-soft)", fontSize: "0.9rem" }}>
                {copy.switchTo}:
              </label>
              <select
                id="billing-switch-period"
                value={switchPeriod}
                onChange={(event) =>
                  setSwitchPeriod(event.target.value as "monthly" | "yearly")
                }
                style={SWITCH_SELECT_STYLE}
                disabled={switchInFlight}
              >
                <option value="monthly">{copy.switchMonthly}</option>
                <option value="yearly">{copy.switchYearly}</option>
              </select>
              <button
                type="button"
                onClick={handleSwitchPlan}
                disabled={switchInFlight || switchPeriod === currentPeriod}
                style={SWITCH_BUTTON_STYLE}
              >
                {switchInFlight ? copy.switchApplying : copy.switchApply}
              </button>
            </div>
            {switchMessage ? (
              <p className="billing-notice" style={{ marginTop: 0 }}>
                {switchMessage}
              </p>
            ) : null}
            {confirmingCancel ? (
              <div
                role="alertdialog"
                aria-labelledby="billing-cancel-heading"
                style={{
                  borderTop: "1px solid var(--border)",
                  paddingTop: "0.9rem",
                  marginTop: "0.4rem",
                  display: "flex",
                  flexDirection: "column",
                  gap: "0.6rem",
                }}
              >
                <h3 id="billing-cancel-heading" style={{ margin: 0, fontSize: "1rem" }}>
                  {copy.confirmHeading}
                </h3>
                <p style={{ margin: 0, color: "var(--ink-soft)", fontSize: "0.9rem" }}>
                  {copy.confirmBody}
                </p>
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
                onClick={() => setConfirmingCancel(true)}
                disabled={inFlight}
                style={SUBTLE_LINK_STYLE}
              >
                {copy.cancelInline}
              </button>
            )}
          </>
        ) : null}

        {!isPro ? (
          <>
            {/* Offer clarity: price + billing period shown before the pay button. */}
            <p style={{ margin: 0, fontSize: "1.1rem", fontWeight: 600 }}>
              Pro — {upgradeAmountStr} {upgradePer}
              {useRubUpgrade && copy.vatIncluded ? (
                <span
                  style={{
                    color: "var(--ink-soft)",
                    fontWeight: 400,
                    fontSize: "0.85rem",
                  }}
                >
                  {" "}
                  ({copy.vatIncluded})
                </span>
              ) : null}
            </p>
            <div
              style={SWITCH_ROW_STYLE}
              role="group"
              aria-label={copy.billingPeriodLabel}
            >
              <button
                type="button"
                onClick={() => setUpgradePeriod("month")}
                aria-pressed={upgradePeriod === "month"}
                style={SWITCH_BUTTON_STYLE}
                disabled={inFlight}
              >
                {copy.switchMonthly}
              </button>
              <button
                type="button"
                onClick={() => setUpgradePeriod("year")}
                aria-pressed={upgradePeriod === "year"}
                style={SWITCH_BUTTON_STYLE}
                disabled={inFlight}
              >
                {copy.switchYearly}
              </button>
            </div>

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

            {requiresRecurringConsent ? (
              <>
                <p style={{ margin: 0, color: "var(--ink-soft)", fontSize: "0.85rem" }}>
                  {copy.autoRenew(upgradeAmountStr, upgradePer)}
                </p>
                <label
                  style={{
                    display: "flex",
                    gap: "0.5rem",
                    alignItems: "flex-start",
                    fontSize: "0.85rem",
                    color: "var(--ink-soft)",
                  }}
                >
                  <input
                    type="checkbox"
                    checked={acceptedRecurring}
                    onChange={(event) => setAcceptedRecurring(event.target.checked)}
                    style={{ marginTop: "0.2rem" }}
                  />
                  <span>
                    {copy.recurringConsent(upgradeAmountStr, upgradePer)}{" "}
                    <Link href="/ru/recurrent" target="_blank" rel="noopener noreferrer">
                      {copy.agreementLink}
                    </Link>
                    {" · "}
                    <Link href="/ru/privacy" target="_blank" rel="noopener noreferrer">
                      {copy.privacyLink}
                    </Link>
                  </span>
                </label>
                <p style={{ margin: 0, color: "var(--ink-soft)", fontSize: "0.8rem" }}>
                  {copy.conversionNotice}
                </p>
              </>
            ) : null}

            <button
              className="billing-upgrade"
              onClick={handleUpgrade}
              disabled={
                inFlight ||
                promoInFlight ||
                (requiresRecurringConsent && !acceptedRecurring)
              }
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
        ) : null}
      </article>

      {/* ----- Payment method card ----- */}
      {isPro ? (
        <article style={CARD_STYLE} aria-labelledby="billing-payment-card">
          <header style={CARD_HEADER_STYLE}>
            <h2 id="billing-payment-card" style={CARD_TITLE_STYLE}>
              {copy.paymentMethodHeading}
            </h2>
          </header>
          <p style={{ margin: 0, color: "var(--ink-soft)", fontSize: "0.9rem" }}>
            {copy.paymentMethodHint}
          </p>
          <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap", alignItems: "center" }}>
            <button
              type="button"
              onClick={handleOpenPortal}
              disabled={portalInFlight}
              className="billing-portal"
              style={{
                padding: "0.45rem 1rem",
                borderRadius: "var(--radius-sm)",
                border: "1px solid var(--border)",
                background: "var(--accent)",
                color: "var(--accent-contrast)",
                cursor: portalInFlight ? "wait" : "pointer",
                minHeight: "38px",
                fontWeight: 600,
              }}
            >
              {portalInFlight ? copy.paymentMethodUpdating : copy.paymentMethodUpdate}
            </button>
            {portalError ? (
              <a
                href="mailto:hi@wai.computer?subject=Billing%20update"
                style={{ color: "var(--accent)", textDecoration: "underline", fontSize: "0.9rem" }}
              >
                {copy.contactSupport}
              </a>
            ) : null}
          </div>
          {portalError ? (
            <p className="billing-error" style={{ margin: 0 }}>
              {portalError}
            </p>
          ) : null}
        </article>
      ) : null}

      {/* ----- Usage block (free tier only) ----- */}
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

      {/* ----- Invoices ----- */}
      <article style={CARD_STYLE} aria-labelledby="billing-invoices-heading">
        <h2 id="billing-invoices-heading" style={CARD_INVOICES_HEADER_STYLE}>
          {copy.invoicesHeading}
        </h2>
        {invoices.length === 0 ? (
          <p style={{ margin: 0, color: "var(--ink-soft)", fontSize: "0.9rem" }}>
            {copy.invoicesEmpty}
          </p>
        ) : (
          <div style={{ overflowX: "auto" }}>
            <table style={INVOICE_TABLE_STYLE}>
              <thead>
                <tr>
                  <th style={INVOICE_TH_STYLE}>{copy.invoiceDate}</th>
                  <th style={INVOICE_TH_STYLE}>{copy.invoiceDescription}</th>
                  <th style={INVOICE_TH_STYLE}>{copy.invoiceAmount}</th>
                  <th style={INVOICE_TH_STYLE}>{copy.invoiceStatus}</th>
                  <th style={INVOICE_TH_STYLE}>{copy.invoiceReceipt}</th>
                </tr>
              </thead>
              <tbody>
                {invoices.map((inv) => (
                  <tr key={inv.id}>
                    <td style={INVOICE_TD_STYLE}>
                      {formatDate(inv.paid_at ?? inv.created_at, locale) ?? "—"}
                    </td>
                    <td style={INVOICE_TD_STYLE}>
                      {inv.description ?? copy.invoiceDefaultDescription}
                    </td>
                    <td style={INVOICE_TD_STYLE}>
                      {formatAmount(inv.amount, inv.currency, locale)}
                    </td>
                    <td style={INVOICE_TD_STYLE}>
                      {localizeInvoiceStatus(inv.status, copy)}
                    </td>
                    <td style={INVOICE_TD_STYLE}>
                      {inv.hosted_invoice_url || inv.receipt_url ? (
                        <a
                          href={inv.hosted_invoice_url ?? inv.receipt_url ?? "#"}
                          target="_blank"
                          rel="noopener noreferrer"
                          style={{
                            color: "var(--accent)",
                            textDecoration: "underline",
                          }}
                        >
                          {copy.invoiceReceipt}
                        </a>
                      ) : (
                        "—"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </article>
    </section>
  );
}
