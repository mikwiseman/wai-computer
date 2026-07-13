import { headers } from "next/headers";
import { VerifyMagicLinkClient } from "@/components/VerifyMagicLinkClient";
import { resolveAuthLocaleFromAcceptLanguage } from "@/lib/auth-locale";

export const metadata = {
  referrer: "no-referrer",
};

interface VerifyPageProps {
  searchParams: Promise<{ token?: string; locale?: string; lang?: string }>;
}

export default async function VerifyMagicLinkPage({ searchParams }: VerifyPageProps) {
  const params = await searchParams;
  const requestHeaders = await headers();
  const initialLocale =
    params.locale
    ?? params.lang
    ?? resolveAuthLocaleFromAcceptLanguage(requestHeaders.get("accept-language"));

  return (
    <main id="main" className="container auth-page">
      <VerifyMagicLinkClient
        token={params.token ?? null}
        locale={initialLocale}
      />
    </main>
  );
}
