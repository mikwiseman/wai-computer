import Link from "next/link";
import { headers } from "next/headers";
import { resolveAuthLocaleFromAcceptLanguage } from "@/lib/auth-locale";

export const metadata = {
  title: "Page not found — WaiComputer",
};

const COPY = {
  en: {
    eyebrow: "404",
    title: "Page not found",
    body: "We couldn't find what you're looking for.",
    cta: "Back to WaiComputer",
    href: "/",
  },
  ru: {
    eyebrow: "404",
    title: "Страница не найдена",
    body: "Мы не нашли то, что вы ищете.",
    cta: "Вернуться на WaiComputer",
    href: "/ru",
  },
} as const;

export default async function NotFound() {
  const requestHeaders = await headers();
  const locale = resolveAuthLocaleFromAcceptLanguage(
    requestHeaders.get("accept-language"),
  );
  const copy = COPY[locale];

  return (
    <main id="main" className="container auth-page" lang={locale}>
      <section className="auth-card auth-card--compact">
        <div className="auth-card__brand">
          <div className="brand-mark" aria-hidden="true" />
          <span>WaiComputer</span>
        </div>

        <header className="auth-card__header">
          <p
            style={{
              color: "var(--ink-faint)",
              fontSize: "0.78rem",
              fontWeight: 740,
              letterSpacing: "0.08em",
              textTransform: "uppercase",
            }}
          >
            {copy.eyebrow}
          </p>
          <h1>{copy.title}</h1>
        </header>

        <p style={{ color: "var(--ink-soft)", lineHeight: 1.5 }}>{copy.body}</p>

        <Link href={copy.href} className="primary-button">
          {copy.cta}
        </Link>
      </section>
    </main>
  );
}
