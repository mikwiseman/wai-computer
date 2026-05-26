import Link from "next/link";
import { LocaleSwitcher } from "@/components/LocaleSwitcher";
import styles from "./page.module.css";

const MAC_DMG_URL = "/releases/macos/WaiComputer-latest.dmg";
const TESTFLIGHT_URL = "https://testflight.apple.com/join/rtnJQzwk";
const PRIVACY_URL = "/privacy";

export default function Home() {
  return (
    <main className={styles.landing}>
      <header className={styles.nav}>
        <Link href="/" className={styles.brand} aria-label="WaiComputer home">
          <span className={styles.brandMark} aria-hidden="true" />
          <span className={styles.brandWord}>WaiComputer</span>
        </Link>
        <nav className={styles.navLinks}>
          <Link href="/pricing" className={styles.navLink}>
            Pricing
          </Link>
          <Link href="/benchmarks/dictation" className={styles.navLink}>
            Benchmark
          </Link>
          <LocaleSwitcher current="en" />
          <Link href="/login" className={styles.signin}>
            Sign in →
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
          An AI second brain for everything you say.
        </h1>
        <p className={styles.subhead}>
          Record on Mac or iPhone. Transcribed in real time. Search across
          everything. Ask Wai anything.
        </p>

        <div className={styles.downloads}>
          <a
            className={styles.downloadPrimary}
            href={MAC_DMG_URL}
            download
            data-testid="download-mac"
          >
            <span className={styles.downloadTitle}>Download for Mac</span>
            <span className={styles.downloadMeta}>macOS 14+ · DMG</span>
          </a>
          <a
            className={styles.downloadGhost}
            href={TESTFLIGHT_URL}
            data-testid="download-ios"
          >
            <span className={styles.downloadTitle}>iPhone</span>
            <span className={styles.downloadMeta}>TestFlight</span>
          </a>
        </div>
      </section>

      <footer className={styles.footer}>
        <span>© WaiWai</span>
        <a href={PRIVACY_URL}>Privacy</a>
        <a href="/terms">Terms</a>
      </footer>
    </main>
  );
}
