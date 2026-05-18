import Image from "next/image";
import Link from "next/link";
import styles from "./page.module.css";

const MAC_DMG_URL = "/releases/macos/WaiComputer-latest.dmg";
const WINDOWS_EXE_URL = "/releases/windows/WaiComputer-Setup.exe";
const TESTFLIGHT_URL = "https://testflight.apple.com/join/rtnJQzwk";
const PRIVACY_URL = "/privacy";

// Flip to `true` once the first signed Windows build lands at WINDOWS_EXE_URL.
// Until then, render a disabled "Coming soon" placeholder so the homepage
// shows the supported platforms even when the file isn't live yet.
const WINDOWS_AVAILABLE = false as boolean;

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
          <Link href="/login" className={styles.signin}>
            Sign in →
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
          An AI second brain for everything you say.
        </h1>
        <p className={styles.subhead}>
          Record on Mac, Windows, or iPhone. Transcribed in real time. Search
          across everything. Ask Wai anything.
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
          {WINDOWS_AVAILABLE ? (
            <a
              className={styles.downloadPrimary}
              href={WINDOWS_EXE_URL}
              download
              data-testid="download-windows"
            >
              <span className={styles.downloadTitle}>Download for Windows</span>
              <span className={styles.downloadMeta}>Windows 10/11 · Setup.exe</span>
            </a>
          ) : (
            <span
              className={styles.downloadDisabled}
              aria-disabled="true"
              data-testid="download-windows"
              data-status="coming-soon"
            >
              <span className={styles.downloadTitle}>Windows</span>
              <span className={styles.downloadMeta}>Coming soon</span>
            </span>
          )}
          <a
            className={styles.downloadGhost}
            href={TESTFLIGHT_URL}
            data-testid="download-ios"
          >
            <span className={styles.downloadTitle}>iPhone &amp; iPad</span>
            <span className={styles.downloadMeta}>TestFlight</span>
          </a>
        </div>
      </section>

      <footer className={styles.footer}>
        <span>© WaiWai</span>
        <a href={PRIVACY_URL}>Privacy</a>
      </footer>
    </main>
  );
}
