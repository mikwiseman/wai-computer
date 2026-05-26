import type { Metadata } from "next";
import { headers } from "next/headers";
import { BillingResultCard } from "@/components/BillingResultCard";
import {
  type BillingResultSearchParams,
  resolveBillingResultLocale,
} from "@/lib/billing-result-locale";

export const metadata: Metadata = {
  title: "Payment status — WaiComputer",
};

type BillingResultPageProps = {
  searchParams?: Promise<BillingResultSearchParams> | BillingResultSearchParams;
};

async function resolveSearchParams(
  searchParams: BillingResultPageProps["searchParams"],
): Promise<BillingResultSearchParams> {
  return searchParams ? await searchParams : {};
}

export default async function BillingSuccessPage({
  searchParams,
}: BillingResultPageProps = {}) {
  const params = await resolveSearchParams(searchParams);
  const requestHeaders = await headers();

  return (
    <BillingResultCard
      kind="success"
      locale={resolveBillingResultLocale(params, {
        acceptLanguage: requestHeaders.get("accept-language"),
        referer: requestHeaders.get("referer"),
      })}
    />
  );
}
