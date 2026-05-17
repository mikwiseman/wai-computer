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

  async function registerThroughWeb(page: Page, email: string) {
    await page.goto("/register", { waitUntil: "networkidle" });
    await expect(page.locator("h1")).toContainText("Create Account");

    await page.getByTestId("auth-email").fill(email);
    await page.getByTestId("auth-password").fill("TestPassword123!");
    await page.getByTestId("auth-submit").click();

    await expect(page).toHaveURL(/\/dashboard/, { timeout: 30_000 });
    await expect(page.getByTestId("user-email")).toContainText(email);
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
    const email = uniqueEmail();

    await registerThroughWeb(page, email);
    await page.getByTestId("tab-library").click();

    // Create a new recording
    await page.getByTestId("recording-title").fill("Live test recording");
    await page.getByTestId("create-recording").click();

    // Verify success message and the recording appears in the list
    await expect(page.getByTestId("dashboard-message")).toContainText("Recording created");
    await expect(page.getByTestId("recording-list")).toContainText("Live test recording");
  });

  test("create entity through dashboard UI", async ({ page }) => {
    const email = uniqueEmail();

    await registerThroughWeb(page, email);
    await page.getByTestId("tab-library").click();

    // Create a new entity
    await page.getByTestId("entity-name").fill("Live test entity");
    await page.getByTestId("create-entity").click();

    // Verify success message and the entity appears in the list
    await expect(page.getByTestId("dashboard-message")).toContainText("Entity created");
    await expect(page.getByTestId("entity-list")).toContainText("Live test entity");
  });

  test("logout redirects to login", async ({ page }) => {
    const email = uniqueEmail();

    await registerThroughWeb(page, email);

    // Click logout
    await page.getByTestId("logout-button").click();

    // Should redirect to login
    await expect(page).toHaveURL(/\/login/);
  });
});
