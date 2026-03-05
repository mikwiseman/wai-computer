import { test, expect, Page } from "@playwright/test";

const apiBaseUrls = [
  "http://localhost:8000",
  "http://127.0.0.1:8000",
  "https://api.wai.computer",
];

const corsHeaders = {
  "access-control-allow-origin": "http://localhost:3000",
  "access-control-allow-credentials": "true",
  "access-control-allow-methods": "GET,POST,PATCH,DELETE,OPTIONS",
  "access-control-allow-headers": "Content-Type,Authorization",
  "content-type": "application/json",
};

const authCookieHeader = {
  "set-cookie": "wai_access_token=mock-token; Path=/; SameSite=Lax",
};

/**
 * Install API route mocks for authentication-related endpoints.
 * Valid credentials: test@example.com / password123
 * Magic link verify: token "valid-token" succeeds, anything else fails.
 */
async function installAuthMocks(page: Page) {
  const handler = async (route: Parameters<Page["route"]>[1] extends (route: infer T) => unknown ? T : never) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();

    // Handle CORS preflight
    if (method === "OPTIONS") {
      await route.fulfill({ status: 204, headers: corsHeaders, body: "" });
      return;
    }

    // POST /api/auth/login
    if (path === "/api/auth/login" && method === "POST") {
      const body = request.postDataJSON() as { email?: string; password?: string };
      if (body?.email === "test@example.com" && body?.password === "password123") {
        await route.fulfill({
          status: 200,
          headers: { ...corsHeaders, ...authCookieHeader },
          body: JSON.stringify({ access_token: "mock-token", token_type: "bearer" }),
        });
        return;
      }
      await route.fulfill({
        status: 401,
        headers: corsHeaders,
        body: JSON.stringify({ detail: "Invalid credentials" }),
      });
      return;
    }

    // POST /api/auth/register
    if (path === "/api/auth/register" && method === "POST") {
      await route.fulfill({
        status: 200,
        headers: { ...corsHeaders, ...authCookieHeader },
        body: JSON.stringify({ access_token: "mock-token", token_type: "bearer" }),
      });
      return;
    }

    // POST /api/auth/magic-link
    if (path === "/api/auth/magic-link" && method === "POST") {
      await route.fulfill({
        status: 200,
        headers: corsHeaders,
        body: JSON.stringify({ message: "Magic link sent to your email" }),
      });
      return;
    }

    // POST /api/auth/verify-magic (used by the verify page)
    if (path === "/api/auth/verify-magic" && method === "POST") {
      const body = request.postDataJSON() as { token?: string };
      if (body?.token === "valid-token") {
        await route.fulfill({
          status: 200,
          headers: { ...corsHeaders, ...authCookieHeader },
          body: JSON.stringify({ access_token: "mock-token", token_type: "bearer" }),
        });
        return;
      }
      await route.fulfill({
        status: 401,
        headers: corsHeaders,
        body: JSON.stringify({ detail: "Invalid or expired token" }),
      });
      return;
    }

    // POST /api/auth/logout
    if (path === "/api/auth/logout" && method === "POST") {
      await route.fulfill({
        status: 200,
        headers: {
          ...corsHeaders,
          "set-cookie": "wai_access_token=; Path=/; Max-Age=0; SameSite=Lax",
        },
        body: JSON.stringify({ message: "Logged out" }),
      });
      return;
    }

    // GET /api/auth/me
    if (path === "/api/auth/me" && method === "GET") {
      await route.fulfill({
        status: 200,
        headers: corsHeaders,
        body: JSON.stringify({
          id: "user-1",
          email: "test@example.com",
          created_at: "2026-01-01T00:00:00Z",
        }),
      });
      return;
    }

    // POST /api/auth/refresh (always fail -- no real refresh token in tests)
    if (path === "/api/auth/refresh" && method === "POST") {
      await route.fulfill({
        status: 401,
        headers: corsHeaders,
        body: JSON.stringify({ detail: "No refresh token" }),
      });
      return;
    }

    // Dashboard data endpoints (return empty lists so the dashboard renders)
    if (path === "/api/recordings" && method === "GET") {
      await route.fulfill({
        status: 200,
        headers: corsHeaders,
        body: JSON.stringify([]),
      });
      return;
    }
    if (path === "/api/action-items" && method === "GET") {
      await route.fulfill({
        status: 200,
        headers: corsHeaders,
        body: JSON.stringify([]),
      });
      return;
    }
    if (path === "/api/entities" && method === "GET") {
      await route.fulfill({
        status: 200,
        headers: corsHeaders,
        body: JSON.stringify([]),
      });
      return;
    }

    // Unhandled route
    await route.fulfill({
      status: 404,
      headers: corsHeaders,
      body: JSON.stringify({ detail: `Unhandled mock route: ${method} ${path}` }),
    });
  };

  for (const baseUrl of apiBaseUrls) {
    await page.route(`${baseUrl}/**`, handler);
  }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe("Auth flow", () => {
  test.beforeEach(async ({ page }) => {
    await installAuthMocks(page);
  });

  test("login with valid credentials redirects to dashboard", async ({ page }) => {
    await page.goto("/login");

    // Verify the login page renders
    await expect(page.locator("h1")).toContainText("Sign In");

    // Fill in credentials and submit
    await page.getByTestId("auth-email").fill("test@example.com");
    await page.getByTestId("auth-password").fill("password123");
    await page.getByTestId("auth-submit").click();

    // Should redirect to the dashboard and display the user email
    await expect(page).toHaveURL(/\/dashboard/);
    await expect(page.getByTestId("user-email")).toContainText("test@example.com");
  });

  test("register redirects to dashboard", async ({ page }) => {
    await page.goto("/register");

    // Verify the register page renders
    await expect(page.locator("h1")).toContainText("Create Account");

    // Fill in form and submit
    await page.getByTestId("auth-email").fill("newuser@example.com");
    await page.getByTestId("auth-password").fill("securePass1");
    await page.getByTestId("auth-submit").click();

    // Should redirect to dashboard
    await expect(page).toHaveURL(/\/dashboard/);
    await expect(page.getByTestId("user-email")).toContainText("test@example.com");
  });

  test("login with wrong credentials shows error message", async ({ page }) => {
    await page.goto("/login");

    await page.getByTestId("auth-email").fill("wrong@example.com");
    await page.getByTestId("auth-password").fill("wrongpassword");
    await page.getByTestId("auth-submit").click();

    // The error message from the mock is "Invalid credentials"
    await expect(page.getByTestId("auth-message")).toContainText("Invalid credentials");

    // Should remain on the login page
    await expect(page).toHaveURL(/\/login/);
  });

  test("middleware redirects unauthenticated users from /dashboard to /login", async ({ page }) => {
    await page.context().clearCookies();

    // Navigate directly to dashboard without any auth cookie
    await page.goto("/dashboard");

    // Middleware should redirect to /login
    await expect(page).toHaveURL(/\/login/);
  });

  test("magic link request shows success message", async ({ page }) => {
    await page.goto("/login");

    // The magic link button is disabled until an email is entered
    await expect(page.getByTestId("magic-link-button")).toBeDisabled();

    // Enter an email, then click the magic link button
    await page.getByTestId("auth-email").fill("test@example.com");
    await expect(page.getByTestId("magic-link-button")).toBeEnabled();
    await page.getByTestId("magic-link-button").click();

    // Should show the success message from the mock
    await expect(page.getByTestId("auth-message")).toContainText("Magic link sent to your email");
  });

  test("home page redirects to login", async ({ page }) => {
    await page.goto("/");

    // The root page does a server-side redirect to /login
    await expect(page).toHaveURL(/\/login/);
  });

  test("magic link verification with valid token redirects to dashboard", async ({ page }) => {
    await page.goto("/auth/verify?token=valid-token");

    // Should show verifying then redirect to dashboard
    await expect(page.getByTestId("verify-message")).toContainText("Redirecting");
    await expect(page).toHaveURL(/\/dashboard/);
  });

  test("magic link verification with invalid token shows error", async ({ page }) => {
    await page.goto("/auth/verify?token=bad-token");

    // Should display the error message
    await expect(page.getByTestId("verify-message")).toContainText("Invalid or expired token");
  });

  test("magic link verification with missing token shows missing message", async ({ page }) => {
    await page.goto("/auth/verify");

    // The component shows "Missing token." when no token param is provided
    await expect(page.getByTestId("verify-message")).toContainText("Missing token");
  });
});
