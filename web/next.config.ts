import type { NextConfig } from "next";

const DEFAULT_DEV_API_BASE_URL = "http://127.0.0.1:8000";
const DEFAULT_PROD_API_BASE_URL = "https://api.wai.computer";

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

const nextConfig: NextConfig = {
  allowedDevOrigins: ["127.0.0.1", "localhost"],
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${resolveApiProxyTarget()}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
