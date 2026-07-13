"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { AuthForm } from "@/components/AuthForm";
import { getCurrentUser } from "@/lib/api";
import type { AuthLocale } from "@/lib/auth-locale";

export function resolveLoginRedirect(
  searchParams: URLSearchParams | { get: (name: string) => string | null },
  origin?: string,
): string {
  const rawReturnTo = searchParams.get("returnTo")?.trim();
  if (!rawReturnTo) return "/dashboard";

  if (rawReturnTo.startsWith("/") && !rawReturnTo.startsWith("//")) {
    return rawReturnTo;
  }

  try {
    const currentOrigin =
      origin ?? (typeof window === "undefined" ? "" : window.location.origin);
    const target = new URL(rawReturnTo);
    if (currentOrigin && target.origin === currentOrigin) {
      return `${target.pathname}${target.search}${target.hash}`;
    }
  } catch {
    return "/dashboard";
  }

  return "/dashboard";
}

interface LoginClientProps {
  initialLocale?: AuthLocale;
}

function hasCompletedVoiceOnboarding(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem("voice_onboarding_complete") === "true";
  } catch {
    return false;
  }
}

export function LoginClient({ initialLocale }: LoginClientProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const redirectTo = resolveLoginRedirect(searchParams);

  // Mirror VerifyMagicLinkClient: users who never enrolled a voice land on
  // onboarding after password login too, unless they deep-linked somewhere
  // specific via returnTo. Server-side enrollment wins over the local flag.
  const handleSuccess = async () => {
    if (redirectTo !== "/dashboard") {
      router.replace(redirectTo);
      return;
    }
    let enrolled = false;
    try {
      enrolled = (await getCurrentUser()).has_enrolled_voice === true;
    } catch {
      enrolled = false;
    }
    const onboarded = enrolled || hasCompletedVoiceOnboarding();
    router.replace(onboarded ? "/dashboard" : "/onboarding");
  };

  return (
    <main id="main" className="container auth-page">
      <AuthForm
        mode="login"
        initialLocale={initialLocale}
        onSuccess={() => void handleSuccess()}
      />
    </main>
  );
}
