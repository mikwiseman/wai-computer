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
          <p className={styles.updated}>Last updated: May 17, 2026</p>
        </header>

        <div className={styles.legalContent}>
          <section>
            <h2>Agreement</h2>
            <p>
              By using WaiComputer, you agree to these terms. If you do not
              agree, do not use the apps, website, API, or connected services.
            </p>
          </section>

          <section>
            <h2>Your content</h2>
            <p>
              You are responsible for the recordings, transcripts, prompts,
              files, and other content you create or upload. You must have the
              rights and permissions needed to process that content with
              WaiComputer.
            </p>
          </section>

          <section>
            <h2>Acceptable use</h2>
            <p>
              Do not use WaiComputer to break the law, violate others&apos;
              rights, interfere with the service, bypass security controls, or
              process content you are not allowed to process.
            </p>
          </section>

          <section>
            <h2>Service changes</h2>
            <p>
              We may update, suspend, or discontinue parts of the service as
              needed for reliability, security, product changes, or legal
              reasons.
            </p>
          </section>

          <section>
            <h2>Disclaimers</h2>
            <p>
              WaiComputer is provided as-is. Transcriptions, summaries, and AI
              outputs can be incomplete or inaccurate, so review important
              information before relying on it.
            </p>
          </section>

          <section>
            <h2>Contact</h2>
            <p>
              Questions about these terms can be sent to{" "}
              <a href="mailto:support@waiwai.is">support@waiwai.is</a>.
            </p>
          </section>
        </div>
      </div>
    </main>
  );
}
