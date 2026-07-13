"use client";

import { useRouter } from "next/navigation";
import { AuthForm } from "@/components/AuthForm";
import type { AuthLocale } from "@/lib/auth-locale";

interface RegisterClientProps {
  initialLocale?: AuthLocale;
}

export function RegisterClient({ initialLocale }: RegisterClientProps) {
  const router = useRouter();

  return (
    <main id="main" className="container auth-page">
      <AuthForm
        mode="register"
        initialLocale={initialLocale}
        // Fresh accounts go through onboarding — same as first-time magic-link
        // users in VerifyMagicLinkClient.
        onSuccess={() => router.replace("/onboarding")}
      />
    </main>
  );
}
