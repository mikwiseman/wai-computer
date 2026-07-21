import type { Metadata } from "next";
import { LandingPage } from "@/components/LandingPage";
import { PaymentComplianceSection } from "./PaymentCompliance";

export const metadata: Metadata = {
  title: "WaiComputer — записи, расшифровки и поиск",
  description:
    "Записывайте встречи и голосовые заметки. WaiComputer расшифрует речь, выделит главное и поможет быстро найти нужное.",
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
