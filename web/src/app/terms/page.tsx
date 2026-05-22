import Link from "next/link";
import styles from "../legal.module.css";

export const metadata = {
  title: "Terms of Service — WaiComputer",
  description: "Terms for using WaiComputer apps, website, API, and connected services.",
};

export default function TermsPage() {
  return (
    <main className={styles.legalPage}>
      <div className={styles.legalShell}>
        <Link className={styles.backLink} href="/">
          WaiComputer
        </Link>

        <header className={styles.legalHeader}>
          <h1>Terms of Service</h1>
          <p className={styles.updated}>Last updated: May 22, 2026</p>
        </header>

        <div className={styles.legalContent}>
          <section>
            <h2>Agreement</h2>
            <p>
              By creating an account, signing in, or using WaiComputer, you agree
              to these Terms and to the Privacy Policy. If you do not agree, do
              not use the apps, website, API, Telegram bot, MCP server, or
              connected services.
            </p>
          </section>

          <section>
            <h2>Your content</h2>
            <p>
              You keep ownership of recordings, audio, video, transcripts,
              prompts, files, summaries, and other content you create or upload.
              You are responsible for having the rights and permissions needed to
              record, upload, transcribe, summarize, and process that content.
            </p>
          </section>

          <section>
            <h2>AI outputs</h2>
            <p>
              Transcripts, summaries, search results, action items, and assistant
              answers can be incomplete or inaccurate. Review important output
              before relying on it for legal, medical, financial, safety, or
              other high-impact decisions.
            </p>
          </section>

          <section>
            <h2>Acceptable use</h2>
            <p>
              Do not use WaiComputer to break the law, violate rights, process
              content you are not allowed to process, bypass security controls,
              overload the service, reverse engineer private systems, or upload
              malicious content.
            </p>
          </section>

          <section>
            <h2>Subscriptions and promo codes</h2>
            <p>
              Paid plans renew according to the checkout terms shown at purchase.
              Promo codes are non-transferable unless we say otherwise, may have
              expiration dates and redemption limits, and do not create an
              automatic paid renewal.
            </p>
          </section>

          <section>
            <h2>Service changes</h2>
            <p>
              We may update, suspend, or discontinue parts of WaiComputer when
              needed for reliability, security, product changes, legal
              compliance, or abuse prevention.
            </p>
          </section>

          <section>
            <h2>Termination</h2>
            <p>
              You may stop using WaiComputer at any time. We may suspend or
              terminate access if you violate these Terms, create risk for the
              service or other users, or if required by law.
            </p>
          </section>

          <section>
            <h2>Disclaimers and liability</h2>
            <p>
              WaiComputer is provided as-is and as available. To the maximum
              extent allowed by law, WaiWai is not liable for indirect,
              incidental, special, consequential, or punitive damages, or for
              lost profits, lost data, or service interruption.
            </p>
          </section>

          <section>
            <h2>Contact</h2>
            <p>
              Questions about these Terms can be sent to{" "}
              <a href="mailto:support@waiwai.is">support@waiwai.is</a>.
            </p>
          </section>
        </div>
      </div>
    </main>
  );
}
