import type { Metadata } from "next";
import { BillingDashboard } from "@/components/BillingDashboard";

export const metadata: Metadata = {
  title: "Подписка — WaiComputer",
};

export default function RuBillingPage() {
  return (
    <main className="container">
      <BillingDashboard locale="ru" currency="rub" />
    </main>
  );
}
