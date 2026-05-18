import type { Metadata } from "next";
import { PricingCards } from "@/components/PricingCards";

export const metadata: Metadata = {
  title: "Цены — WaiComputer",
  description:
    "WaiComputer бесплатно для повседневных голосовых заметок. Pro даёт безлимит транскрипции, постоянную память и доступ к агентам и MCP.",
  alternates: {
    canonical: "https://wai.computer/ru/pricing",
    languages: {
      en: "https://wai.computer/pricing",
      ru: "https://wai.computer/ru/pricing",
    },
  },
};

export default function RuPricingPage() {
  return (
    <main className="container pricing-page">
      <PricingCards locale="ru" currency="rub" />
    </main>
  );
}
