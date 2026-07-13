"use client";

import Link from "next/link";
import { useState } from "react";

import { ServerDataSection } from "@/components/ServerDataSection";

type Choice = "cloud" | "self_host";

export function SetupClient() {
  const [choice, setChoice] = useState<Choice>("cloud");

  return (
    <main id="main" className="setup-shell">
      <section className="setup-hero">
        <div>
          <h1>Choose where your data lives</h1>
          <p>
            Use Wai Cloud for the fastest setup, or connect your own VPS so
            recordings, transcripts, memories, uploads, and generated data stay
            on your server.
          </p>
        </div>
        <Link href="/dashboard" className="ghost-button compact-button">
          Open dashboard
        </Link>
      </section>

      <section className="setup-choice" aria-label="Hosting choice">
        <button
          type="button"
          className={choice === "cloud" ? "setup-card setup-card--active" : "setup-card"}
          onClick={() => setChoice("cloud")}
        >
          <span>Wai Cloud</span>
          <strong>Managed by Wai</strong>
          <small>
            Fastest start. Billing, updates, backups, and infrastructure are handled for you.
          </small>
        </button>
        <button
          type="button"
          className={choice === "self_host" ? "setup-card setup-card--active" : "setup-card"}
          onClick={() => setChoice("self_host")}
        >
          <span>My own server</span>
          <strong>Your VPS, your data</strong>
          <small>
            Use a guided VPS setup. Your durable data and files live on your server.
          </small>
        </button>
      </section>

      {choice === "cloud" ? (
        <section className="setup-cloud">
          <h2>Start on Wai Cloud</h2>
          <p>
            Wai Cloud is ready now. You can move to your own server later from
            Settings → Server & Data.
          </p>
          <div className="setup-actions">
            <Link href="/register" className="primary-button">
              Create account
            </Link>
            <Link href="/login" className="ghost-button">
              Sign in
            </Link>
          </div>
        </section>
      ) : (
        <ServerDataSection provisioning="account_required" />
      )}
    </main>
  );
}
