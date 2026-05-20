import type { Metadata } from "next";
import { BillingResultCard } from "@/components/BillingResultCard";

export const metadata: Metadata = {
  title: "Оплата не прошла — WaiComputer",
};

export default function RuBillingCancelPage() {
  return <BillingResultCard kind="cancel" locale="ru" />;
}
