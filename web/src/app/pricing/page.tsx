import type { Metadata } from "next";
import Link from "next/link";
import { LocaleSwitcher } from "@/components/LocaleSwitcher";
import { PricingCards } from "@/components/PricingCards";
import styles from "../page.module.css";

export const metadata: Metadata = {
  title: "Pricing — WaiComputer",
  description:
    "WaiComputer is free for everyday voice notes. Upgrade to Pro for no weekly word cap, permanent memory, agents, and MCP.",
  alternates: {
    canonical: "https://wai.computer/pricing",
    languages: {
      en: "https://wai.computer/pricing",
      ru: "https://wai.computer/ru/pricing",
    },
  },
};

export default function PricingPage() {
  return (
    <main className="container pricing-page">
      <header className={styles.nav}>
        <Link href="/" className={styles.brand} aria-label="WaiComputer home">
          <span className={styles.brandMark} aria-hidden="true" />
          <span className={styles.brandWord}>WaiComputer</span>
        </Link>
        <nav className={styles.navLinks}>
          <LocaleSwitcher current="en" />
          <Link href="/login" className={styles.signin}>
            Sign in →
          </Link>
        </nav>
      </header>
      <PricingCards locale="en" currency="usd" />
    </main>
  );
}
