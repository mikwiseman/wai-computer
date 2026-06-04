import { test, expect, type Page } from "@playwright/test";

// ---------------------------------------------------------------------------
// These tests hit the REAL API server. They are skipped unless E2E_LIVE_API
// is set in the environment (e.g. E2E_LIVE_API=1 npx playwright test).
//
// The API base URL defaults to https://wai.computer but can be overridden
// with E2E_API_URL.
// ---------------------------------------------------------------------------

const LIVE = process.env.E2E_LIVE_API === "1";
const API_URL = process.env.E2E_API_URL || "https://wai.computer";
const LEGAL_ACCEPTANCE = {
  accepted_legal_terms: true,
  legal_terms_version: "2026-05-22",
  legal_privacy_version: "2026-05-22",
};

/** Generate a unique email for each test run to avoid collisions. */
function uniqueEmail(): string {
  const ts = Date.now();
  const rand = Math.random().toString(36).slice(2, 8);
  return `e2e-${ts}-${rand}@test.wai.computer`;
}

const describeOrSkip = LIVE ? test.describe : test.describe.skip;

describeOrSkip("Live API", () => {
  // Increase timeout for live tests -- network calls take longer than mocks
  test.setTimeout(60_000);
  test.describe.configure({ mode: "serial" });

  const sharedPassword = "TestPassword123!";
  let sharedEmail = "";

  async function openPasswordModeIfNeeded(page: Page) {
    const passwordModeButton = page.getByTestId("password-mode-button");
    if (await passwordModeButton.isVisible()) {
      await passwordModeButton.click();
    }
  }

  test.beforeAll(async ({ request }) => {
    sharedEmail = uniqueEmail();
    const response = await request.post(`${API_URL}/api/auth/register`, {
      data: { email: sharedEmail, password: sharedPassword, ...LEGAL_ACCEPTANCE },
    });
    expect(response.status()).toBe(200);
  });

  async function registerThroughWeb(page: Page, email: string) {
    await page.goto("/register", { waitUntil: "networkidle" });
    await expect(page.locator("h1")).toContainText(/Create Account|Create account/);

    await page.getByTestId("auth-email").fill(email);
    await openPasswordModeIfNeeded(page);
    await page.getByTestId("auth-password").fill(sharedPassword);
    const legalConsent = page.getByTestId("legal-consent-checkbox");
    if (await legalConsent.count()) {
      await legalConsent.check();
    }
    await page.getByTestId("auth-submit").click();

    await expect(page).toHaveURL(/\/dashboard/, { timeout: 30_000 });
    await expect(page.getByTestId("user-email")).toContainText(email);
  }

  async function loginThroughWeb(page: Page) {
    await page.goto("/login", { waitUntil: "networkidle" });
    await expect(page.locator("h1")).toContainText(/Sign In|Sign in/);

    await page.getByTestId("auth-email").fill(sharedEmail);
    await openPasswordModeIfNeeded(page);
    await page.getByTestId("auth-password").fill(sharedPassword);
    await page.getByTestId("auth-submit").click();

    await expect(page).toHaveURL(/\/dashboard/, { timeout: 30_000 });
    await expect(page.getByTestId("user-email")).toContainText(sharedEmail);
  }

  test("health check returns 200", async ({ request }) => {
    const response = await request.get(`${API_URL}/health`);
    expect(response.status()).toBe(200);
  });

  test("register through web form and reach dashboard", async ({ page }) => {
    const email = uniqueEmail();
    await registerThroughWeb(page, email);
  });

  test("create recording through dashboard UI", async ({ page }) => {
    await loginThroughWeb(page);
    await page.getByTestId("tab-inbox").click();
    await page.getByRole("button", { name: "+ Add" }).click();
    await page.getByText("Create empty recording").click();

    await page.getByTestId("recording-title").fill("Live test recording");
    await page.getByTestId("create-recording").click();

    await expect(page.getByTestId("dashboard-message")).toContainText("Recording created");
    await expect(page.getByTestId("workspace-title")).toContainText("Inbox");
    await expect(page.getByText("Live test recording")).toBeVisible();
  });

  test("search and brain surfaces load through dashboard UI", async ({ page }) => {
    await loginThroughWeb(page);
    await page.getByTestId("tab-search").click();
    await expect(page.getByTestId("search-query")).toBeVisible();
    await page.getByTestId("tab-brain").click();
    await expect(page.getByTestId("workspace-title")).toContainText(/Brain|Память/);
  });

  test("logout redirects to login", async ({ page }) => {
    await loginThroughWeb(page);

    // Click logout
    await page.getByTestId("logout-button").click();

    // Should redirect to login
    await expect(page).toHaveURL(/\/login/);
  });
});
