import { headers } from "next/headers";
import { OnboardingClient } from "@/components/OnboardingClient";
import { resolveAuthLocaleFromAcceptLanguage } from "@/lib/auth-locale";

import "./onboarding.css";

export const metadata = {
  title: "Welcome — WaiComputer",
};

export const dynamic = "force-dynamic";

export default async function OnboardingPage() {
  const requestHeaders = await headers();
  const initialLocale = resolveAuthLocaleFromAcceptLanguage(
    requestHeaders.get("accept-language"),
  );

  return <OnboardingClient initialLocale={initialLocale} />;
}
