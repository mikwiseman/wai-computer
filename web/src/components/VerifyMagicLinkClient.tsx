"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { verifyMagicLink } from "@/lib/api";
import { ApiError } from "@/lib/http";

interface VerifyMagicLinkClientProps {
  token: string | null;
}

export function VerifyMagicLinkClient({ token }: VerifyMagicLinkClientProps) {
  const router = useRouter();
  const [message, setMessage] = useState(token ? "Verifying token..." : "Missing token.");

  useEffect(() => {
    if (!token) return;

    void (async () => {
      try {
        await verifyMagicLink(token);
        setMessage("Magic link verified. Redirecting...");
        router.replace("/dashboard");
      } catch (error: unknown) {
        if (error instanceof ApiError) {
          setMessage(error.message);
          return;
        }
        setMessage("Verification failed.");
      }
    })();
  }, [router, token]);

  return (
    <section className="auth-card auth-card--compact">
      <div className="auth-card__brand">
        <div className="brand-mark" aria-hidden="true" />
        <span>WaiSay</span>
      </div>
      <h1>Magic Link Verification</h1>
      <p data-testid="verify-message">{message}</p>
      <Link href="/login">Back to login</Link>
    </section>
  );
}
