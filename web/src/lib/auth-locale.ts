export type AuthLocale = "en" | "ru";

export function normalizeAuthLocale(value: string | null | undefined): AuthLocale {
  return value?.trim().toLowerCase().startsWith("ru") ? "ru" : "en";
}

export function resolveAuthLocaleFromAcceptLanguage(
  acceptLanguage: string | null | undefined,
): AuthLocale {
  if (!acceptLanguage) return "en";

  const candidates = acceptLanguage
    .split(",")
    .map((entry, index) => {
      const [rawLanguage, ...params] = entry.trim().split(";");
      const qParam = params.find((param) => param.trim().startsWith("q="));
      const q = qParam ? Number(qParam.trim().slice(2)) : 1;
      return {
        index,
        language: rawLanguage.trim().toLowerCase(),
        q: Number.isFinite(q) ? q : 0,
      };
    })
    .filter((entry) => entry.language.length > 0 && entry.q > 0)
    .sort((a, b) => b.q - a.q || a.index - b.index);

  return normalizeAuthLocale(candidates[0]?.language);
}
