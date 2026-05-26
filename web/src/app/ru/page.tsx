import Link from "next/link";
import type { Metadata } from "next";
import { LocaleSwitcher } from "@/components/LocaleSwitcher";
import styles from "../page.module.css";

const MAC_DMG_URL = "/releases/macos/WaiComputer-ru-latest.dmg";
const TESTFLIGHT_URL = "https://testflight.apple.com/join/rtnJQzwk";
const PRIVACY_URL = "/ru/privacy";

export const metadata: Metadata = {
  title: "WaiComputer — AI-память для голоса",
  description:
    "Записывайте, расшифровывайте, ищите, спрашивайте Wai обо всём, что вы когда-либо говорили.",
  alternates: {
    canonical: "https://wai.computer/ru",
    languages: {
      en: "https://wai.computer",
      ru: "https://wai.computer/ru",
    },
  },
};

export default function RuHome() {
  return (
    <main className={styles.landing}>
      <header className={styles.nav}>
        <Link href="/ru" className={styles.brand} aria-label="WaiComputer">
          <span className={styles.brandMark} aria-hidden="true" />
          <span className={styles.brandWord}>WaiComputer</span>
        </Link>
        <nav className={styles.navLinks}>
          <Link href="/ru/pricing" className={styles.navLink}>
            Цены
          </Link>
          <Link href="/ru/benchmarks/dictation" className={styles.navLink}>
            Бенчмарк
          </Link>
          <LocaleSwitcher current="ru" />
          <Link href="/login" className={styles.signin}>
            Войти →
          </Link>
        </nav>
      </header>

      <section className={styles.hero}>
        <div className={styles.iconHalo}>
          <picture>
            <source
              srcSet="/app-icon-dark.png"
              media="(prefers-color-scheme: dark)"
            />
            <img
              className={styles.icon}
              src="/app-icon.png"
              width={160}
              height={160}
              alt=""
              fetchPriority="high"
            />
          </picture>
        </div>
        <h1 className={styles.headline}>
          AI-память для всего, что вы говорите.
        </h1>
        <p className={styles.subhead}>
          Запись на Mac или iPhone. Расшифровка в реальном времени. Поиск по
          всему, что вы говорили. Спросите Wai о чём угодно.
        </p>

        <div className={styles.downloads}>
          <a
            className={styles.downloadPrimary}
            href={MAC_DMG_URL}
            download
            data-testid="download-mac-ru"
          >
            <span className={styles.downloadTitle}>Скачать для Mac</span>
            <span className={styles.downloadMeta}>macOS 14+ · DMG</span>
          </a>
          <a
            className={styles.downloadGhost}
            href={TESTFLIGHT_URL}
            data-testid="download-ios-ru"
          >
            <span className={styles.downloadTitle}>iPhone</span>
            <span className={styles.downloadMeta}>TestFlight · бета</span>
          </a>
        </div>
      </section>

      <footer className={styles.footer}>
        <span>© WaiWai</span>
        <a href={PRIVACY_URL}>Конфиденциальность</a>
        <a href="/ru/terms">Условия</a>
      </footer>
    </main>
  );
}
