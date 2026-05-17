import Image from "next/image";
import Link from "next/link";
import styles from "./page.module.css";

const MAC_DMG_URL = "/releases/macos/WaiComputer-latest.dmg";
const APP_STORE_URL = "https://apps.apple.com/app/waicomputer/id6761768729";
const PRIVACY_URL = "/privacy";

export default function Home() {
  return (
    <main className={styles.landing}>
      <header className={styles.nav}>
        <Link href="/" className={styles.brand} aria-label="WaiComputer home">
          <span className={styles.brandMark} aria-hidden="true" />
          <span className={styles.brandWord}>WaiComputer</span>
        </Link>
        <Link href="/login" className={styles.signin}>
          Sign in →
        </Link>
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
            href={APP_STORE_URL}
            data-testid="download-ios"
          >
            <span className={styles.downloadTitle}>iPhone &amp; iPad</span>
            <span className={styles.downloadMeta}>App Store</span>
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
