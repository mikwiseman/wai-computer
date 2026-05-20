import type { Metadata } from "next";
import Link from "next/link";
import { LocaleSwitcher } from "@/components/LocaleSwitcher";
import { PricingCards } from "@/components/PricingCards";
import styles from "../../page.module.css";

export const metadata: Metadata = {
  title: "Цены — WaiComputer",
  description:
    "WaiComputer бесплатно для повседневных голосовых заметок. Pro даёт 50 000 слов транскрипции в неделю, постоянную память и доступ к агентам и MCP.",
  alternates: {
    canonical: "https://wai.computer/ru/pricing",
    languages: {
      en: "https://wai.computer/pricing",
      ru: "https://wai.computer/ru/pricing",
    },
  },
};

export default function RuPricingPage() {
  return (
    <main className="container pricing-page">
      <header className={styles.nav}>
        <Link href="/ru" className={styles.brand} aria-label="WaiComputer">
          <span className={styles.brandMark} aria-hidden="true" />
          <span className={styles.brandWord}>WaiComputer</span>
        </Link>
        <nav className={styles.navLinks}>
          <LocaleSwitcher current="ru" />
          <Link href="/login" className={styles.signin}>
            Войти →
          </Link>
        </nav>
      </header>
      <PricingCards locale="ru" currency="rub" />
    </main>
  );
}
