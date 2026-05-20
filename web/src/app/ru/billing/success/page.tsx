import type { Metadata } from "next";
import { BillingResultCard } from "@/components/BillingResultCard";

export const metadata: Metadata = {
  title: "Оплата обновлена — WaiComputer",
};

export default function RuBillingSuccessPage() {
  return <BillingResultCard kind="success" locale="ru" />;
}
