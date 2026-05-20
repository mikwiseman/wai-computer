import type { Metadata } from "next";
import {
  BillingResultCard,
  type BillingResultSearchParams,
  resolveBillingResultLocale,
} from "@/components/BillingResultCard";

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

export default async function BillingCancelPage({
  searchParams,
}: BillingResultPageProps = {}) {
  const params = await resolveSearchParams(searchParams);

  return <BillingResultCard kind="cancel" locale={resolveBillingResultLocale(params)} />;
}
