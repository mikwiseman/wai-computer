import { defineConfig, devices } from "@playwright/test";

const port = 3000;

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  retries: 1,
  workers: process.env.CI ? 1 : undefined,
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    trace: "on-first-retry",
  },
  webServer: {
    command: "pnpm build && pnpm start --port 3000",
    url: `http://127.0.0.1:${port}`,
    reuseExistingServer: !process.env.CI,
    timeout: 240_000,
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "firefox", use: { ...devices["Desktop Firefox"] } },
    { name: "webkit", use: { ...devices["Desktop Safari"] } },
  ],
});
