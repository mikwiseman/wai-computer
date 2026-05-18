import type { Metadata } from "next";

export const metadata: Metadata = {
  alternates: {
    canonical: "https://wai.computer/ru",
    languages: {
      en: "https://wai.computer",
      ru: "https://wai.computer/ru",
    },
  },
};

export default function RuLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  // The root layout already renders <html lang="en"> — we re-tag the inner
  // tree with a Russian language attribute via a data-locale fence so
  // screen readers and search engines pick up the locale shift without
  // requiring a parallel <html> root.
  return <div lang="ru">{children}</div>;
}
