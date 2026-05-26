import type { Metadata } from "next";
import { headers } from "next/headers";
import { SharedRecordingClient } from "@/components/SharedRecordingClient";
import { resolveAuthLocaleFromAcceptLanguage } from "@/lib/auth-locale";

const SHARE_OG_IMAGE = "/og-share.png";
const SITE_URL = "https://wai.computer";

export async function generateMetadata(props: {
  params: Promise<{ token: string }>;
}): Promise<Metadata> {
  const { token } = await props.params;
  const headerStore = await headers();
  const locale = resolveAuthLocaleFromAcceptLanguage(headerStore.get("accept-language"));

  const title =
    locale === "ru"
      ? "Общая запись — WaiComputer"
      : "Shared recording — WaiComputer";
  const description =
    locale === "ru"
      ? "Запись, расшифровка и саммари, опубликованные через WaiComputer — AI-память для голоса."
      : "A recording, transcript and summary shared from WaiComputer — your AI second brain for voice.";
  const canonicalUrl = `${SITE_URL}/share/${token}`;

  return {
    title,
    description,
    alternates: {
      canonical: canonicalUrl,
    },
    openGraph: {
      type: "article",
      url: canonicalUrl,
      title,
      description,
      siteName: "WaiComputer",
      locale: locale === "ru" ? "ru_RU" : "en_US",
      images: [
        {
          url: SHARE_OG_IMAGE,
          width: 1200,
          height: 630,
          alt: "WaiComputer",
        },
      ],
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
      site: "@waicomputer",
      images: [SHARE_OG_IMAGE],
    },
    robots: {
      // Shared notes are link-gated; don't index them.
      index: false,
      follow: false,
    },
  };
}

export default async function SharedRecordingPage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;
  const headerStore = await headers();
  const locale = resolveAuthLocaleFromAcceptLanguage(headerStore.get("accept-language"));
  return <SharedRecordingClient token={token} locale={locale} />;
}
