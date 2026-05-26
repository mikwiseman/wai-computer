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
