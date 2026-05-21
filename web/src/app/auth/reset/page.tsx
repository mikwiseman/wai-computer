import { headers } from "next/headers";
import { resolveAuthLocaleFromAcceptLanguage } from "@/lib/auth-locale";
import { ResetPasswordClient } from "./ResetPasswordClient";

export const metadata = {
  referrer: "no-referrer",
};

interface ResetPasswordPageProps {
  searchParams: Promise<{ token?: string; locale?: string }>;
}

export default async function ResetPasswordPage({ searchParams }: ResetPasswordPageProps) {
  const params = await searchParams;
  const requestHeaders = await headers();
  const initialLocale =
    params.locale
    ?? resolveAuthLocaleFromAcceptLanguage(requestHeaders.get("accept-language"));

  return (
    <main className="container auth-page">
      <ResetPasswordClient token={params.token ?? null} locale={initialLocale} />
    </main>
  );
}
