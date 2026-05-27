import type { Metadata, Viewport } from "next";
import { headers } from "next/headers";
import { Space_Grotesk } from "next/font/google";
import { resolveAuthLocaleFromAcceptLanguage } from "@/lib/auth-locale";
import "@/styles/tokens.css";
import "./globals.css";

const spaceGrotesk = Space_Grotesk({
  variable: "--font-space-grotesk",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  metadataBase: new URL("https://wai.computer"),
  title: "WaiComputer — AI second brain for voice",
  description:
    "Record, transcribe, search, and ask anything across everything you've ever said.",
  openGraph: {
    type: "website",
    siteName: "WaiComputer",
    title: "WaiComputer — AI second brain for voice",
    description:
      "Record, transcribe, search, and ask anything across everything you've ever said.",
    url: "https://wai.computer",
    images: [
      {
        url: "/og-default.png",
        width: 1200,
        height: 630,
        alt: "WaiComputer — AI second brain for voice",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "WaiComputer — AI second brain for voice",
    description:
      "Record, transcribe, search, and ask anything across everything you've ever said.",
    images: ["/og-default.png"],
  },
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
    <html lang={lang} data-theme="system" data-accent="teal">
      <body className={spaceGrotesk.variable}>
        <script
          dangerouslySetInnerHTML={{
            __html:
              "(function(){try{var t=localStorage.getItem('wai_theme');if(t)document.documentElement.setAttribute('data-theme',t);var a=localStorage.getItem('wai_accent');if(a)document.documentElement.setAttribute('data-accent',a);}catch(e){}})();",
          }}
        />
        {children}
      </body>
    </html>
  );
}
