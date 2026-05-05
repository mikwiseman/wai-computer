"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { AuthForm } from "@/components/AuthForm";

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

export function LoginClient() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const redirectTo = resolveLoginRedirect(searchParams);

  return (
    <main className="container auth-page">
      <AuthForm mode="login" onSuccess={() => router.replace(redirectTo)} />
    </main>
  );
}
