import type { Metadata } from "next";
import { LandingPage } from "@/components/LandingPage";
import { PaymentComplianceSection } from "./PaymentCompliance";

export const metadata: Metadata = {
  title: "WaiComputer | записи, расшифровки и поиск",
  description:
    "WaiComputer для Mac записывает встречи, превращает диктовку в текст и помогает быстро найти важное.",
  alternates: {
    canonical: "https://wai.computer/ru",
    languages: {
      en: "https://wai.computer",
      ru: "https://wai.computer/ru",
    },
  },
};

export default function RuHome() {
  return (
    <LandingPage
      locale="ru"
      legal={<PaymentComplianceSection eyebrow="Подписка Pro" title="Оплата и документы" />}
    />
  );
}
