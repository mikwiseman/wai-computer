import type { MetadataRoute } from "next";

const SITE_URL = "https://wai.computer";

// Bump this string when launching new public surfaces; Next emits it
// verbatim into the <lastmod> tag.
const LAST_MODIFIED = "2026-09-09";

const PUBLIC_PATHS = [
  "/",
  "/school/projects",
  "/school/projects/hallownest",
  "/school/projects/block-modz",
  "/school/projects/rifflegg",
  "/school/projects/qfa-26",
  "/school/projects/bouquet",
  "/school/projects/mathai",
  "/school/projects/escape-room",
  "/school/projects/escape",
  "/school/projects/bug-battle",
  "/school/projects/bunker-zombie",
  "/school/projects/striker",
  "/school/projects/checkmedia",
  "/mentors/dima",
  "/mentors/darya",
  "/school/contact",
  "/legal/offer",
  "/legal/privacy",
  "/pricing",
  "/privacy",
  "/terms",
  "/benchmarks/dictation",
] as const;

export default function sitemap(): MetadataRoute.Sitemap {
  return PUBLIC_PATHS.map((path) => ({
    url: `${SITE_URL}${path === "/" ? "" : path}`,
    lastModified: LAST_MODIFIED,
    changeFrequency: path === "/" ? "weekly" : "monthly",
    priority: path === "/" ? 1.0 : 0.6,
  }));
}
