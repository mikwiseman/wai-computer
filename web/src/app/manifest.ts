import type { MetadataRoute } from "next";

// PWA manifest — makes WaiComputer installable (the closest web analog to the
// Mac app's persistent presence). Next serves this at /manifest.webmanifest and
// auto-injects the <link rel="manifest">.
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "WaiComputer",
    short_name: "WaiComputer",
    description:
      "AI second brain for voice — recordings, realtime transcription, search, and summaries.",
    start_url: "/dashboard",
    display: "standalone",
    background_color: "#f9f7f2",
    theme_color: "#f9f7f2",
    icons: [
      {
        src: "/app-icon.png",
        sizes: "192x192 512x512 1024x1024",
        type: "image/png",
        purpose: "any",
      },
    ],
  };
}
