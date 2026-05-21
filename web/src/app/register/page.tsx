import { headers } from "next/headers";
import { resolveAuthLocaleFromAcceptLanguage } from "@/lib/auth-locale";
import { RegisterClient } from "./RegisterClient";

export default async function RegisterPage() {
  const requestHeaders = await headers();
  const initialLocale = resolveAuthLocaleFromAcceptLanguage(
    requestHeaders.get("accept-language"),
  );

  return <RegisterClient initialLocale={initialLocale} />;
}
