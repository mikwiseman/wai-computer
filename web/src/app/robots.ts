import type { MetadataRoute } from "next";

const SITE_URL = "https://wai.computer";

export default function robots(): MetadataRoute.Robots {
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        // Auth + private surfaces are not indexable; share links are
        // link-gated and already opt-out via per-page robots metadata.
        disallow: [
          "/api/",
          "/dashboard",
          "/dashboard/",
          "/billing",
          "/billing/",
          "/login",
          "/register",
          "/onboarding",
          "/auth/",
          "/admin",
          "/admin/",
          "/share/",
        ],
      },
    ],
    sitemap: `${SITE_URL}/sitemap.xml`,
    host: SITE_URL,
  };
}
