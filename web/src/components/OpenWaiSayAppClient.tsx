"use client";

import { useEffect, useMemo } from "react";
import Link from "next/link";
import { buildWaiSayAppUrl, type WaiSayAppClient } from "@/lib/app-client";

interface OpenWaiSayAppClientProps {
  token: string | null;
  client: WaiSayAppClient | null;
  autoOpen?: boolean;
}

export function OpenWaiSayAppClient({
  token,
  client,
  autoOpen = true,
}: OpenWaiSayAppClientProps) {
  const appUrl = useMemo(() => {
    if (!token || !client) return null;
    return buildWaiSayAppUrl(token, client);
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
        <span>WaiSay</span>
      </div>
      <h1>Open WaiSay App</h1>
      {appUrl ? (
        <>
          <p data-testid="open-app-message">Opening WaiSay. Keep this page open if macOS asks you to confirm.</p>
          <div className="auth-card__secondary">
            <a data-testid="open-app-link" href={appUrl}>
              Open WaiSay App
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
