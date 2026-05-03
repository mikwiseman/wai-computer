import { defineConfig, devices } from "@playwright/test";

const host = "127.0.0.1";
const port = Number(process.env.E2E_WEB_SERVER_PORT || 3100);
const localBaseUrl = `http://${host}:${port}`;
const liveApiUrl = process.env.E2E_API_URL || "https://say.waiwai.is";
const liveWebUrl = process.env.E2E_WEB_URL || liveApiUrl;
const isLiveApiRun = process.env.E2E_LIVE_API === "1";

function buildWebServerEnv(): Record<string, string> {
  const env = Object.fromEntries(
    Object.entries(process.env).filter((entry): entry is [string, string] => typeof entry[1] === "string"),
  );

  if (isLiveApiRun) {
    env.API_BASE_URL = liveApiUrl;
  } else {
    env.API_BASE_URL = "http://127.0.0.1:65535";
  }

  env.NEXT_PUBLIC_API_BASE_URL = "";
  return env;
}

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: false,
  retries: 1,
  workers: 1,
  use: {
    baseURL: isLiveApiRun ? liveWebUrl : localBaseUrl,
    trace: "on-first-retry",
  },
  webServer: isLiveApiRun
    ? undefined
    : {
        command: `pnpm build && pnpm start --hostname ${host} --port ${port}`,
        env: buildWebServerEnv(),
        name: "waisay-web-e2e",
        url: localBaseUrl,
        reuseExistingServer: false,
        stdout: "ignore",
        stderr: "pipe",
        timeout: 240_000,
      },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "firefox", use: { ...devices["Desktop Firefox"] } },
    { name: "webkit", use: { ...devices["Desktop Safari"] } },
  ],
});
