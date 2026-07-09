import type { Metadata, Viewport } from "next";
import { headers } from "next/headers";
import { resolveAuthLocaleFromAcceptLanguage } from "@/lib/auth-locale";
import { ToastProvider } from "@/components/Toast";
import "@/styles/tokens.css";
import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL("https://wai.computer"),
  title: "WaiComputer — AI second brain for voice",
  description:
    "Save the meetings and voice notes you choose, then transcribe, search, and ask Wai about them.",
  openGraph: {
    type: "website",
    siteName: "WaiComputer",
    title: "WaiComputer — AI second brain for voice",
    description:
      "Save the meetings and voice notes you choose, then transcribe, search, and ask Wai about them.",
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
      "Save the meetings and voice notes you choose, then transcribe, search, and ask Wai about them.",
    images: ["/og-default.png"],
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f9f7f2" },
    { media: "(prefers-color-scheme: dark)", color: "#131211" },
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
    // suppressHydrationWarning: the inline no-FOUC script below mutates
    // data-theme/data-accent before React hydrates; the mismatch is expected.
    <html lang={lang} data-theme="system" data-accent="amber" suppressHydrationWarning>
      <body>
        <script
          dangerouslySetInnerHTML={{
            __html:
              "(function(){try{var t=localStorage.getItem('wai_theme');if(t)document.documentElement.setAttribute('data-theme',t);var a=localStorage.getItem('wai_accent');if(a)document.documentElement.setAttribute('data-accent',a);}catch(e){}})();",
          }}
        />
        <a className="skip-link" href="#main">
          {lang === "ru" ? "Перейти к содержимому" : "Skip to content"}
        </a>
        <ToastProvider>{children}</ToastProvider>
      </body>
    </html>
  );
}
