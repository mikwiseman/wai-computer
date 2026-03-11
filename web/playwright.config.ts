import { defineConfig, devices } from "@playwright/test";

const host = "localhost";
const port = 3000;
const liveApiUrl = process.env.E2E_API_URL || "https://api.wai.computer";
const isLiveApiRun = process.env.E2E_LIVE_API === "1";

function buildWebServerEnv(): Record<string, string> {
  const env = Object.fromEntries(
    Object.entries(process.env).filter((entry): entry is [string, string] => typeof entry[1] === "string"),
  );

  if (isLiveApiRun) {
    env.API_BASE_URL = liveApiUrl;
    env.NEXT_PUBLIC_API_BASE_URL = "";
  }

  return env;
}

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  retries: 1,
  workers: process.env.CI ? 1 : undefined,
  use: {
    baseURL: `http://${host}:${port}`,
    trace: "on-first-retry",
  },
  webServer: {
    command: "pnpm build && pnpm start --port 3000",
    env: buildWebServerEnv(),
    url: `http://${host}:${port}`,
    reuseExistingServer: !process.env.CI,
    timeout: 240_000,
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "firefox", use: { ...devices["Desktop Firefox"] } },
    { name: "webkit", use: { ...devices["Desktop Safari"] } },
  ],
});
