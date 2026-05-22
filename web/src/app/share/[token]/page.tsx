import { SharedRecordingClient } from "@/components/SharedRecordingClient";
import { resolveAuthLocaleFromAcceptLanguage } from "@/lib/auth-locale";
import { headers } from "next/headers";

export default async function SharedRecordingPage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;
  const headerStore = await headers();
  const locale = resolveAuthLocaleFromAcceptLanguage(headerStore.get("accept-language"));
  return <SharedRecordingClient token={token} locale={locale} />;
}
