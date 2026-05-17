"use client";

import { useEffect, useMemo } from "react";
import Link from "next/link";
import { buildWaiComputerAppUrl, type WaiComputerAppClient } from "@/lib/app-client";

interface OpenWaiComputerAppClientProps {
  token: string | null;
  client: WaiComputerAppClient | null;
  autoOpen?: boolean;
}

export function OpenWaiComputerAppClient({
  token,
  client,
  autoOpen = true,
}: OpenWaiComputerAppClientProps) {
  const appUrl = useMemo(() => {
    if (!token || !client) return null;
    return buildWaiComputerAppUrl(token, client);
  }, [client, token]);

  const browserUrl = token ? `/auth/verify?token=${encodeURIComponent(token)}` : "/login";

  useEffect(() => {
    if (!autoOpen || !appUrl) return;

    const timer = window.setTimeout(() => {
      window.location.href = appUrl;
    }, 250);

    return () => window.clearTimeout(timer);
  }, [appUrl, autoOpen]);

  return (
    <section className="auth-card auth-card--compact">
      <div className="auth-card__brand">
        <div className="brand-mark" aria-hidden="true" />
        <span>WaiComputer</span>
      </div>
      <h1>Open WaiComputer App</h1>
      {appUrl ? (
        <>
          <p data-testid="open-app-message">Opening WaiComputer. Keep this page open if macOS asks you to confirm.</p>
          <div className="auth-card__secondary">
            <a data-testid="open-app-link" href={appUrl}>
              Open WaiComputer App
            </a>
            <Link data-testid="browser-sign-in-link" href={browserUrl}>
              Use browser instead
            </Link>
          </div>
        </>
      ) : token ? (
        <>
          <p data-testid="open-app-message">This app sign-in link is not valid.</p>
          <Link data-testid="browser-sign-in-link" href={browserUrl}>
            Use browser instead
          </Link>
        </>
      ) : (
        <>
          <p data-testid="open-app-message">Missing token.</p>
          <Link href="/login">Back to login</Link>
        </>
      )}
    </section>
  );
}
