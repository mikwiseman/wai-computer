import type { Metadata, Viewport } from "next";
import { headers } from "next/headers";
import { Space_Grotesk } from "next/font/google";
import { resolveAuthLocaleFromAcceptLanguage } from "@/lib/auth-locale";
import "./globals.css";

const spaceGrotesk = Space_Grotesk({
  variable: "--font-space-grotesk",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "WaiComputer — AI second brain for voice",
  description:
    "Record, transcribe, search, and ask anything across everything you've ever said.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f7f7f5" },
    { media: "(prefers-color-scheme: dark)", color: "#101214" },
  ],
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const requestHeaders = await headers();
  const lang = resolveAuthLocaleFromAcceptLanguage(
    requestHeaders.get("accept-language"),
  );
  return (
    <html lang={lang}>
      <body className={spaceGrotesk.variable}>{children}</body>
    </html>
  );
}
