import type { Metadata } from "next";
import { LandingPage } from "@/components/LandingPage";

export const metadata: Metadata = {
  title: "WaiComputer | A second memory for your voice",
  description:
    "WaiComputer for Mac records meetings, turns dictation into text, and keeps every voice searchable.",
  alternates: {
    canonical: "https://wai.computer",
    languages: {
      en: "https://wai.computer",
      ru: "https://wai.computer/ru",
    },
  },
};

export default function Home() {
  return <LandingPage locale="en" />;
}
