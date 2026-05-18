import type { Metadata } from "next";
import { PricingCards } from "@/components/PricingCards";

export const metadata: Metadata = {
  title: "Pricing — WaiComputer",
  description:
    "WaiComputer is free for everyday voice notes. Upgrade to Pro for unlimited transcription, permanent memory, agents, and MCP.",
  alternates: {
    canonical: "https://wai.computer/pricing",
    languages: {
      en: "https://wai.computer/pricing",
      ru: "https://wai.computer/ru/pricing",
    },
  },
};

export default function PricingPage() {
  return (
    <main className="container pricing-page">
      <PricingCards locale="en" currency="usd" />
    </main>
  );
}
