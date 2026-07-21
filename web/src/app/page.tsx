import type { Metadata } from "next";
import { LandingPage } from "@/components/LandingPage";

export const metadata: Metadata = {
  title: "WaiComputer — A second memory for your voice",
  description:
    "Turn meetings, thoughts, and voice notes into clear summaries, actions, and answers.",
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
