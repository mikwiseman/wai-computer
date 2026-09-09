import type { NextConfig } from "next";
import { withSentryConfig } from "@sentry/nextjs";

const DEFAULT_DEV_API_BASE_URL = "http://127.0.0.1:8000";
const DEFAULT_PROD_API_BASE_URL = "https://wai.computer";

function resolveApiProxyTarget(): string {
  const configured =
    process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL;
  if (configured && configured.length > 0) {
    return configured.replace(/\/$/, "");
  }

  return process.env.NODE_ENV === "development"
    ? DEFAULT_DEV_API_BASE_URL
    : DEFAULT_PROD_API_BASE_URL;
}

export { resolveApiProxyTarget };

export function schoolRewrites() {
  return {
    beforeFiles: [
      { source: "/", destination: "/school-static/index.html" },
      { source: "/school/projects", destination: "/school-static/projects.html" },
      { source: "/projects", destination: "/school-static/projects.html" },
      { source: "/mentors/dima", destination: "/school-static/mentors/dima.html" },
      { source: "/mentors/darya", destination: "/school-static/mentors/darya.html" },
      { source: "/school/contact", destination: "/school-static/contact.html" },
      { source: "/school/projects/:project/app", destination: "/school-static/student-projects/:project/app/index.html" },
      { source: "/school/projects/:project", destination: "/school-static/student-projects/:project/index.html" },
      { source: "/school/projects/:project/:asset*", destination: "/school-static/student-projects/:project/:asset*" },
      { source: "/school-data/multiplayer", destination: "https://wai.school/api/projects/multiplayer" },
      { source: "/legal/offer", destination: "/school-static/offer.html" },
      { source: "/legal/privacy", destination: "/school-static/privacy.html" },
    ],
    afterFiles: [
      { source: "/api/:path*", destination: `${resolveApiProxyTarget()}/api/:path*` },
    ],
    fallback: [],
  };
}

const nextConfig: NextConfig = {
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  async redirects() {
    return [
      { source: "/ru", destination: "/", permanent: true },
      ...["pricing", "privacy", "terms", "benchmarks/dictation"].map((path) => ({
        source: `/ru/${path}`,
        destination: `/${path}`,
        permanent: true,
      })),
    ];
  },
  async rewrites() {
    return schoolRewrites();
  },
};

export default withSentryConfig(nextConfig, {
  org: "waiwai-diy",
  project: "waicomputer-web",
  widenClientFileUpload: true,
  // Source maps (readable stack traces) upload only when SENTRY_AUTH_TOKEN is
  // present at build time; without it the SDK still reports errors.
  authToken: process.env.SENTRY_AUTH_TOKEN,
  silent: !process.env.CI,
});
