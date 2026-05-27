import type { MetadataRoute } from "next";

const SITE_URL = "https://wai.computer";

// Bump this string when launching new public surfaces; Next emits it
// verbatim into the <lastmod> tag.
const LAST_MODIFIED = "2026-05-27";

const PUBLIC_PATHS = [
  "/",
  "/ru",
  "/pricing",
  "/ru/pricing",
  "/privacy",
  "/ru/privacy",
  "/terms",
  "/ru/terms",
  "/benchmarks/dictation",
  "/ru/benchmarks/dictation",
] as const;

export default function sitemap(): MetadataRoute.Sitemap {
  return PUBLIC_PATHS.map((path) => ({
    url: `${SITE_URL}${path === "/" ? "" : path}`,
    lastModified: LAST_MODIFIED,
    changeFrequency: path === "/" || path === "/ru" ? "weekly" : "monthly",
    priority: path === "/" || path === "/ru" ? 1.0 : 0.6,
  }));
}
