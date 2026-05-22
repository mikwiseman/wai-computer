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

const copy: Record<
  BillingResultLocale,
  Record<BillingResultKind, { title: string; body: string; eyebrow: string }>
> = {
  en: {
    success: {
      eyebrow: "Billing",
      title: "Billing updated",
      body:
        "Your payment was accepted. You can close this tab and return to WaiComputer.",
    },
    cancel: {
      eyebrow: "Billing",
      title: "Checkout canceled",
      body: "No payment was made. You can close this tab and return to WaiComputer.",
    },
  },
  ru: {
    success: {
      eyebrow: "Подписка",
      title: "Оплата обновлена",
      body: "Платёж принят. Можно закрыть эту вкладку и вернуться в WaiComputer.",
    },
    cancel: {
      eyebrow: "Подписка",
      title: "Оплата не прошла",
      body:
        "Платёж не был подтверждён: карта не подошла, банк отклонил операцию или форма оплаты была закрыта. Для оплаты через Т-Банк нужна карта, которую принимает Т-Банк; 4242 4242 4242 4242 — Stripe test card, а не тестовая карта Т-Банка. Можно закрыть эту вкладку и вернуться в WaiComputer.",
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
  const text = copy[locale][kind];

  return (
    <main className="billing-result-shell">
      <section className={`billing-result-card billing-result-card--${kind}`}>
        <p className="eyebrow">{text.eyebrow}</p>
        <h1>{text.title}</h1>
        <p>{text.body}</p>
      </section>
    </main>
  );
}
