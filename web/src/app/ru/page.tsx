import Image from "next/image";
import Link from "next/link";
import type { Metadata } from "next";
import { LocaleSwitcher } from "@/components/LocaleSwitcher";
import styles from "../page.module.css";

const MAC_DMG_URL = "/releases/macos/WaiComputer-ru-latest.dmg";
const ANDROID_APK_URL = "/releases/android/WaiComputer-latest.apk";
const TESTFLIGHT_URL = "https://testflight.apple.com/join/rtnJQzwk";
const PRIVACY_URL = "/privacy";

export const metadata: Metadata = {
  title: "WaiComputer — AI second brain для голоса",
  description:
    "Записывай, расшифровывай и спрашивай у Wai что угодно про всё, что ты когда-либо сказал.",
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
          <LocaleSwitcher current="ru" />
          <Link href="/login" className={styles.signin}>
            Войти →
          </Link>
        </nav>
      </header>

      <section className={styles.hero}>
        <div className={styles.iconHalo}>
          <Image
            className={styles.icon}
            src="/app-icon.png"
            alt=""
            width={160}
            height={160}
            priority
          />
        </div>
        <h1 className={styles.headline}>
          AI second brain для всего, что ты говоришь.
        </h1>
        <p className={styles.subhead}>
          Запись на Mac, Windows, iPhone или Android. Транскрипция в реальном
          времени. Поиск по всему. Спроси Wai что угодно.
        </p>

        <div className={styles.downloads}>
          <a
            className={styles.downloadPrimary}
            href={MAC_DMG_URL}
            download
            data-testid="download-mac-ru"
          >
            <span className={styles.downloadTitle}>Скачать для Mac</span>
            <span className={styles.downloadMeta}>macOS 14+ · DMG · RU</span>
          </a>
          <span
            className={styles.downloadDisabled}
            aria-disabled="true"
            data-testid="download-windows-ru"
            data-status="coming-soon"
          >
            <span className={styles.downloadTitle}>Windows</span>
            <span className={styles.downloadMeta}>Скоро</span>
          </span>
          <a
            className={styles.downloadGhost}
            href={TESTFLIGHT_URL}
            data-testid="download-ios-ru"
          >
            <span className={styles.downloadTitle}>iPhone и iPad</span>
            <span className={styles.downloadMeta}>TestFlight</span>
          </a>
          <a
            className={styles.downloadGhost}
            href={ANDROID_APK_URL}
            download
            data-testid="download-android-ru"
          >
            <span className={styles.downloadTitle}>Android</span>
            <span className={styles.downloadMeta}>APK · sideload</span>
          </a>
        </div>
      </section>

      <footer className={styles.footer}>
        <span>© WaiWai</span>
        <a href={PRIVACY_URL}>Конфиденциальность</a>
      </footer>
    </main>
  );
}
