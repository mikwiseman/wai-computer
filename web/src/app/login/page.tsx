import { Suspense } from "react";
import { headers } from "next/headers";
import { resolveAuthLocaleFromAcceptLanguage } from "@/lib/auth-locale";
import { LoginClient, resolveLoginRedirect } from "./LoginClient";

export { resolveLoginRedirect };

export const metadata = {
  title: "Sign in — WaiComputer",
  referrer: "no-referrer",
} as const;

export default async function LoginPage() {
  const requestHeaders = await headers();
  const initialLocale = resolveAuthLocaleFromAcceptLanguage(
    requestHeaders.get("accept-language"),
  );

  return (
    <Suspense fallback={null}>
      <LoginClient initialLocale={initialLocale} />
    </Suspense>
  );
}
