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
          <p className={styles.updated}>Last updated: May 17, 2026</p>
        </header>

        <div className={styles.legalContent}>
          <section>
            <h2>Who we are</h2>
            <p>
              WaiComputer is operated by WaiWai. This policy explains what data
              we process when you use the WaiComputer apps, website, API, and
              connected services.
            </p>
          </section>

          <section>
            <h2>Data we process</h2>
            <ul>
              <li>Account details such as your email address and authentication state.</li>
              <li>Recordings, transcripts, summaries, search indexes, and related metadata you create.</li>
              <li>Device, app, and diagnostic events needed to keep the service reliable and secure.</li>
            </ul>
          </section>

          <section>
            <h2>How data is used</h2>
            <p>
              We use your data to provide transcription, search, summaries,
              synchronization, account access, support, abuse prevention, and
              service diagnostics. We do not sell your recordings or transcripts.
            </p>
          </section>

          <section>
            <h2>Service providers</h2>
            <p>
              WaiComputer may use infrastructure, transcription, AI, email,
              analytics, and crash-reporting providers to operate the product.
              Providers are used only for service delivery, security, support,
              and reliability.
            </p>
          </section>

          <section>
            <h2>Your choices</h2>
            <p>
              You can delete local app data from your device and request account
              or server-side data deletion by contacting{" "}
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
