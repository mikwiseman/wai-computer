import Link from "next/link";
import styles from "../legal.module.css";

export const metadata = {
  title: "Privacy Policy — WaiComputer",
  description: "How WaiComputer handles account, recording, transcript, and diagnostics data.",
};

export default function PrivacyPage() {
  return (
    <main className={styles.legalPage}>
      <div className={styles.legalShell}>
        <Link className={styles.backLink} href="/">
          WaiComputer
        </Link>

        <header className={styles.legalHeader}>
          <h1>Privacy Policy</h1>
          <p className={styles.updated}>Last updated: May 28, 2026</p>
        </header>

        <div className={styles.legalContent}>
          <section>
            <h2>Who we are</h2>
            <p>
              WaiComputer is operated by WaiWai. This Policy explains how we
              process data when you use the WaiComputer apps, website, API,
              Telegram bot, MCP server, and connected services.
            </p>
          </section>

          <section>
            <h2>Data we process</h2>
            <ul>
              <li>Account details such as email address, authentication state, billing region, and legal acceptance records.</li>
              <li>Recordings, audio, video, transcripts, summaries, search indexes, action items, and related metadata you create or upload.</li>
              <li>Telegram account identifiers and messages sent to the WaiComputer bot when you connect Telegram.</li>
              <li>Billing events, plan status, promo code redemptions, and payment provider references.</li>
              <li>Device, app, server, and diagnostic events needed for reliability, security, and abuse prevention.</li>
            </ul>
          </section>

          <section>
            <h2>How data is used</h2>
            <p>
              We use data to provide transcription, summaries, search, Wai
              answers, synchronization, Telegram processing, billing, account
              access, support, security, diagnostics, and service improvement.
              We do not sell your recordings or transcripts.
            </p>
          </section>

          <section>
            <h2>Service providers</h2>
            <p>
              WaiComputer may use infrastructure, transcription, AI, payment,
              email, analytics, and crash-reporting providers. Providers are
              used only to operate, secure, support, and improve the service.
            </p>
          </section>

          <section>
            <h2>Retention and deletion</h2>
            <p>
              Account and service records are kept while needed to provide the
              product, meet legal obligations, resolve disputes, prevent abuse,
              and maintain security. You can delete local app data from your
              device and request account or server-side data deletion by
              contacting support.
            </p>
          </section>

          <section>
            <h2>Voice sharing directory</h2>
            <p>
              WaiComputer offers an optional voice-sharing directory. Sharing
              is off by default. If you turn it on in Settings, your first
              name, last name, and a derived voice fingerprint are stored in
              a global match index so other users&apos; recordings can display
              your name when your voice is detected. We do not share your
              audio, transcripts, summaries, or recording metadata through
              this directory. You can turn sharing off at any time, which
              immediately deletes your entry from the directory.
            </p>
          </section>

          <section>
            <h2>Your choices</h2>
            <p>
              You can choose what to record or upload, disconnect Telegram,
              delete recordings where supported, cancel subscriptions, and
              request access, correction, export, or deletion of your data by
              contacting{" "}
              <a href="mailto:support@waiwai.is">support@waiwai.is</a>.
            </p>
          </section>

          <section>
            <h2>Contact</h2>
            <p>
              Questions about privacy can be sent to{" "}
              <a href="mailto:support@waiwai.is">support@waiwai.is</a>.
            </p>
          </section>
        </div>
      </div>
    </main>
  );
}
