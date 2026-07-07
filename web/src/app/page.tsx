import Link from "next/link";
import Image from "next/image";
import type { Metadata } from "next";
import { LocaleSwitcher } from "@/components/LocaleSwitcher";
import styles from "./page.module.css";

const MAC_DMG_URL = "/releases/macos/WaiComputer-latest.dmg";
const WEB_APP_URL = "/dashboard";
const TESTFLIGHT_URL = "https://testflight.apple.com/join/rtnJQzwk";
const PRIVACY_URL = "/privacy";

const CURRENT_YEAR = new Date().getFullYear();

export const metadata: Metadata = {
  title: "WaiComputer — AI memory for voice",
  description:
    "Save the meetings and voice notes you choose, then transcribe, search, and ask Wai about them.",
  alternates: {
    canonical: "https://wai.computer",
    languages: {
      en: "https://wai.computer",
      ru: "https://wai.computer/ru",
    },
  },
};

function MacIcon() {
  return (
    <svg
      className={styles.platformIcon}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <path
        d="M16.2 4.2c.7-.85 1.2-2 1-3.2-1 .05-2.2.7-2.95 1.5-.65.7-1.25 1.85-1.05 3 1.15.1 2.3-.55 3-1.3Zm2.5 8.05c-.05-2.65 2.15-3.9 2.25-3.95-1.2-1.8-3.1-2.05-3.8-2.1-1.6-.15-3.15.95-3.95.95-.8 0-2.05-.95-3.4-.9-1.75.05-3.35 1.05-4.25 2.65-1.8 3.15-.45 7.8 1.3 10.35.85 1.25 1.85 2.65 3.15 2.6 1.25-.05 1.75-.85 3.3-.85 1.55 0 2 .85 3.35.8 1.4-.05 2.25-1.25 3.1-2.5 1-1.45 1.4-2.85 1.4-2.95-.05-.05-2.7-1.05-2.75-4.1Z"
        fill="currentColor"
      />
    </svg>
  );
}

function WebIcon() {
  return (
    <svg
      className={styles.platformIcon}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <circle
        cx="12"
        cy="12"
        r="9"
        stroke="currentColor"
        strokeWidth="1.7"
        fill="none"
      />
      <path
        d="M3.5 12h17M12 3.5c2 2.2 3.1 5 3.1 8.5S14 18.3 12 20.5M12 3.5c-2 2.2-3.1 5-3.1 8.5S10 18.3 12 20.5"
        stroke="currentColor"
        strokeWidth="1.45"
        strokeLinecap="round"
        fill="none"
      />
    </svg>
  );
}

function IPhoneIcon() {
  return (
    <svg
      className={styles.platformIcon}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <rect
        x="6"
        y="2"
        width="12"
        height="20"
        rx="2.5"
        stroke="currentColor"
        strokeWidth="1.7"
        fill="none"
      />
      <line
        x1="10"
        y1="5"
        x2="14"
        y2="5"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
      />
      <circle cx="12" cy="19" r="0.9" fill="currentColor" />
    </svg>
  );
}

function MicIcon() {
  return (
    <svg
      className={styles.featureIcon}
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden="true"
    >
      <rect
        x="12"
        y="5"
        width="8"
        height="15"
        rx="4"
        stroke="currentColor"
        strokeWidth="1.8"
        fill="none"
      />
      <path
        d="M7 14a9 9 0 0 0 18 0"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        fill="none"
      />
      <line
        x1="16"
        y1="23"
        x2="16"
        y2="27"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </svg>
  );
}

function SearchIcon() {
  return (
    <svg
      className={styles.featureIcon}
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden="true"
    >
      <circle
        cx="14"
        cy="14"
        r="7"
        stroke="currentColor"
        strokeWidth="1.8"
        fill="none"
      />
      <line
        x1="19.5"
        y1="19.5"
        x2="25"
        y2="25"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
      />
    </svg>
  );
}

function BrainIcon() {
  return (
    <svg
      className={styles.featureIcon}
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden="true"
    >
      <path
        d="M11 7a4 4 0 0 0-4 4v1a3.5 3.5 0 0 0-1 6.5 4 4 0 0 0 5 3 4 4 0 0 0 5 0 4 4 0 0 0 5-3 3.5 3.5 0 0 0-1-6.5v-1a4 4 0 0 0-4-4 4 4 0 0 0-2.5.9A4 4 0 0 0 11 7Z"
        stroke="currentColor"
        strokeWidth="1.7"
        fill="none"
      />
      <line
        x1="16"
        y1="9"
        x2="16"
        y2="22"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinecap="round"
        strokeDasharray="2 2"
      />
    </svg>
  );
}

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
              srcSet="/app-icon-dark-320.png"
              media="(prefers-color-scheme: dark)"
            />
            <img
              className={styles.icon}
              src="/app-icon-320.png"
              width={160}
              height={160}
              alt=""
              fetchPriority="high"
            />
          </picture>
        </div>
        <h1 className={styles.headline}>
          Private AI memory for what you choose to record.
        </h1>
        <p className={styles.subhead}>
          Start recording on Mac, iPhone, or right here in your browser when you
          need it. Search saved transcripts and ask Wai about the moments you
          captured.
        </p>

        <div className={`${styles.downloads} ${styles.downloadsWide}`}>
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
            href={WEB_APP_URL}
            data-testid="download-web"
          >
            <span className={styles.downloadTitle}>Open in browser</span>
            <span className={styles.downloadMeta}>Web · no install</span>
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

      <section className={styles.section} aria-labelledby="platforms-title">
        <header className={styles.sectionHeader}>
          <p className={styles.eyebrow}>Available where you choose to record</p>
          <h2 id="platforms-title" className={styles.sectionTitle}>
            Three ways into one memory.
          </h2>
        </header>
        <ul className={styles.platformGrid} role="list">
          <li>
            <a
              className={`${styles.platformCard} ${styles.platformCardLive}`}
              href={MAC_DMG_URL}
              download
            >
              <MacIcon />
              <span className={styles.platformTitle}>Mac</span>
              <span className={`${styles.statusPill} ${styles.statusLive}`}>
                Available now
              </span>
              <span className={styles.platformSubtitle}>
                Native app, signed DMG, macOS 14+.
              </span>
            </a>
          </li>
          <li>
            <a
              className={`${styles.platformCard} ${styles.platformCardLive}`}
              href={WEB_APP_URL}
              data-testid="platform-web"
            >
              <WebIcon />
              <span className={styles.platformTitle}>Web</span>
              <span className={`${styles.statusPill} ${styles.statusLive}`}>
                Available now
              </span>
              <span className={styles.platformSubtitle}>
                Works in any modern browser — no install needed.
              </span>
            </a>
          </li>
          <li>
            <a
              className={styles.platformCard}
              href={TESTFLIGHT_URL}
              target="_blank"
              rel="noopener noreferrer"
            >
              <IPhoneIcon />
              <span className={styles.platformTitle}>iPhone</span>
              <span className={`${styles.statusPill} ${styles.statusBeta}`}>
                Beta
              </span>
              <span className={styles.platformSubtitle}>
                TestFlight build, ships weekly.
              </span>
            </a>
          </li>
        </ul>
      </section>

      <section className={styles.section} aria-labelledby="features-title">
        <header className={styles.sectionHeader}>
          <p className={styles.eyebrow}>What WaiComputer does</p>
          <h2 id="features-title" className={styles.sectionTitle}>
            Record. Search. Ask.
          </h2>
        </header>
        <ul className={styles.featureGrid} role="list">
          <li className={styles.featureCard}>
            <MicIcon />
            <h3 className={styles.featureTitle}>Record when you press start</h3>
            <p className={styles.featureBody}>
              Mac, iPhone, browser, and voice memos imported from your library.
              Live transcription runs only for active recordings.
            </p>
          </li>
          <li className={styles.featureCard}>
            <SearchIcon />
            <h3 className={styles.featureTitle}>Search saved transcripts</h3>
            <p className={styles.featureBody}>
              Hybrid full-text and semantic search across the recordings and
              imports you saved.
            </p>
          </li>
          <li className={styles.featureCard}>
            <BrainIcon />
            <h3 className={styles.featureTitle}>Ask Wai anything</h3>
            <p className={styles.featureBody}>
              An AI second brain that remembers what you saved and answers from
              your own recordings.
            </p>
          </li>
        </ul>
      </section>

      <section className={styles.section} aria-labelledby="screens-title">
        <header className={styles.sectionHeader}>
          <p className={styles.eyebrow}>See it in motion</p>
          <h2 id="screens-title" className={styles.sectionTitle}>
            WaiComputer on the web.
          </h2>
        </header>
        <div className={styles.screensStrip}>
          <figure className={styles.screenFrame}>
            <Image
              src="/screenshots/dashboard-library.png"
              alt="WaiComputer library view on the web"
              width={1400}
              height={875}
              sizes="(max-width: 960px) 100vw, 50vw"
            />
          </figure>
          <figure className={styles.screenFrame}>
            <Image
              src="/screenshots/recording-detail.png"
              alt="WaiComputer recording detail with full transcript"
              width={1400}
              height={875}
              sizes="(max-width: 960px) 100vw, 50vw"
            />
          </figure>
        </div>
        <p className={styles.screensCaption}>
          WaiComputer on the web — Mac, iPhone, and any browser.
        </p>
      </section>

      <section
        className={`${styles.section} ${styles.benchmarkTeaserSection}`}
        aria-labelledby="benchmark-teaser-title"
      >
        <div className={styles.benchmarkCard}>
          <p className={styles.benchmarkEyebrow}>Benchmark</p>
          <h2 id="benchmark-teaser-title" className={styles.benchmarkTitle}>
            We tested every leading dictation model. WaiComputer ships the one
            that won.
          </h2>
          <p className={styles.benchmarkBody}>
            Synthetic fixtures and a blind live arena across five providers —
            measured for word-error rate, latency, and finalization speed. The
            full report is open.
          </p>
          <Link
            href="/benchmarks/dictation"
            className={styles.benchmarkCta}
            data-testid="benchmark-cta"
          >
            See the benchmark →
          </Link>
        </div>
      </section>

      <section className={styles.section} aria-labelledby="pricing-teaser-title">
        <header className={styles.sectionHeader}>
          <p className={styles.eyebrow}>Pricing</p>
          <h2 id="pricing-teaser-title" className={styles.sectionTitle}>
            Free for daily notes. Pro when you need it everywhere.
          </h2>
        </header>
        <div className={styles.pricingTeaserGrid}>
          <article className={styles.pricingTeaserCard}>
            <h3 className={styles.pricingTeaserPlan}>Free</h3>
            <p className={styles.pricingTeaserPrice}>$0</p>
            <ul className={styles.pricingTeaserBullets} role="list">
              <li>3,000 transcribed words per week</li>
              <li>Realtime dictation</li>
              <li>Search your library</li>
            </ul>
          </article>
          <article
            className={`${styles.pricingTeaserCard} ${styles.pricingTeaserCardPro}`}
          >
            <h3 className={styles.pricingTeaserPlan}>Pro</h3>
            <p className={styles.pricingTeaserPrice}>
              $12<span className={styles.pricingTeaserUnit}>/mo</span>
            </p>
            <ul className={styles.pricingTeaserBullets} role="list">
              <li>Unlimited recordings</li>
              <li>Ask Wai across your whole memory</li>
              <li>Priority transcription models</li>
            </ul>
          </article>
        </div>
        <p className={styles.pricingTeaserLink}>
          <Link
            href="/pricing"
            className={styles.textLink}
            data-testid="pricing-link"
          >
            See full pricing →
          </Link>
        </p>
      </section>

      <section className={styles.section} aria-labelledby="faq-title">
        <header className={styles.sectionHeader}>
          <p className={styles.eyebrow}>Questions</p>
          <h2 id="faq-title" className={styles.sectionTitle}>
            Frequently asked.
          </h2>
        </header>
        <dl className={styles.faqList}>
          <div className={styles.faqItem}>
            <dt className={styles.faqQuestion}>What does WaiComputer record?</dt>
            <dd className={styles.faqAnswer}>
              Only audio you explicitly start recording — meetings, calls,
              voice memos, thoughts on a walk. WaiComputer does not listen in
              the background. Mac can record system audio plus your mic while a
              recording is active; iPhone and Web use the microphone.
            </dd>
          </div>
          <div className={styles.faqItem}>
            <dt className={styles.faqQuestion}>Is my audio private?</dt>
            <dd className={styles.faqAnswer}>
              Yes. Recordings are encrypted in transit and at rest, stored only
              for you, never trained on, never sold. Delete a recording and it
              is removed from our servers. Full policy at /privacy.
            </dd>
          </div>
          <div className={styles.faqItem}>
            <dt className={styles.faqQuestion}>
              Which models power transcription?
            </dt>
            <dd className={styles.faqAnswer}>
              Realtime dictation and live recording use Deepgram Nova-3.
              Full-session transcription uses ElevenLabs Scribe v2.
              See the current stack check at /benchmarks/dictation.
            </dd>
          </div>
          <div className={styles.faqItem}>
            <dt className={styles.faqQuestion}>Can I export my data?</dt>
            <dd className={styles.faqAnswer}>
              Yes. Every recording can be exported as Markdown today; PDF and
              audio downloads are next. Shared notes get a public link you
              control.
            </dd>
          </div>
          <div className={styles.faqItem}>
            <dt className={styles.faqQuestion}>Does it work offline?</dt>
            <dd className={styles.faqAnswer}>
              Recording works offline on Mac and iPhone — audio is queued
              locally and uploaded when you reconnect. Transcription and Ask Wai
              need a connection.
            </dd>
          </div>
        </dl>
      </section>

      <footer className={styles.footer}>
        <span>© {CURRENT_YEAR} WaiWai</span>
        <a href={PRIVACY_URL}>Privacy</a>
        <a href="/terms">Terms</a>
      </footer>
    </main>
  );
}
