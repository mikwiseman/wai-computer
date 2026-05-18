import type { Metadata } from "next";
import { BillingDashboard } from "@/components/BillingDashboard";

export const metadata: Metadata = {
  title: "Billing — WaiComputer",
};

export default function BillingPage() {
  return (
    <main className="container">
      <BillingDashboard locale="en" currency="usd" />
    </main>
  );
}
