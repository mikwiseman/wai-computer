import { test, expect, Page, Route } from "@playwright/test";

const authCookieHeader = {
  "set-cookie": "wai_access_token=mock-token; Path=/; SameSite=Lax",
};

function jsonHeaders(route: Route) {
  return {
    "access-control-allow-origin": new URL(route.request().url()).origin,
    "access-control-allow-credentials": "true",
    "access-control-allow-methods": "GET,POST,PATCH,DELETE,OPTIONS",
    "access-control-allow-headers": "Content-Type,Authorization",
    "content-type": "application/json",
  };
}

/**
 * Install API route mocks for authentication-related endpoints.
 * Valid credentials: test@example.com / password123
 * Magic link verify: token "valid-token" succeeds, anything else fails.
 */
async function installAuthMocks(page: Page) {
  let isAuthenticated = false;

  const handler = async (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();
    const headers = jsonHeaders(route);

    // Handle CORS preflight
    if (method === "OPTIONS") {
      await route.fulfill({ status: 204, headers, body: "" });
      return;
    }

    // POST /api/auth/login
    if (path === "/api/auth/login" && method === "POST") {
      const body = request.postDataJSON() as { email?: string; password?: string };
      if (body?.email === "test@example.com" && body?.password === "password123") {
        isAuthenticated = true;
        await route.fulfill({
          status: 200,
          headers: { ...headers, ...authCookieHeader },
          body: JSON.stringify({ access_token: "mock-token", token_type: "bearer" }),
        });
        return;
      }
      await route.fulfill({
        status: 401,
        headers,
        body: JSON.stringify({ detail: "Invalid credentials" }),
      });
      return;
    }

    // POST /api/auth/register
    if (path === "/api/auth/register" && method === "POST") {
      isAuthenticated = true;
      await route.fulfill({
        status: 200,
        headers: { ...headers, ...authCookieHeader },
        body: JSON.stringify({ access_token: "mock-token", token_type: "bearer" }),
      });
      return;
    }

    // POST /api/auth/magic-link
    if (path === "/api/auth/magic-link" && method === "POST") {
      await route.fulfill({
        status: 200,
        headers,
        body: JSON.stringify({ message: "Magic link sent to your email" }),
      });
      return;
    }

    // POST /api/auth/verify-magic (used by the verify page)
    if (path === "/api/auth/verify-magic" && method === "POST") {
      const body = request.postDataJSON() as { token?: string };
      if (body?.token === "valid-token") {
        isAuthenticated = true;
        await route.fulfill({
          status: 200,
          headers: { ...headers, ...authCookieHeader },
          body: JSON.stringify({ access_token: "mock-token", token_type: "bearer" }),
        });
        return;
      }
      await route.fulfill({
        status: 401,
        headers,
        body: JSON.stringify({ detail: "Invalid or expired token" }),
      });
      return;
    }

    // POST /api/auth/logout
    if (path === "/api/auth/logout" && method === "POST") {
      isAuthenticated = false;
      await route.fulfill({
        status: 200,
        headers: {
          ...headers,
          "set-cookie": "wai_access_token=; Path=/; Max-Age=0; SameSite=Lax",
        },
        body: JSON.stringify({ message: "Logged out" }),
      });
      return;
    }

    // GET /api/auth/me
    if (path === "/api/auth/me" && method === "GET") {
      if (!isAuthenticated) {
        await route.fulfill({
          status: 401,
          headers,
          body: JSON.stringify({ detail: "Unauthorized" }),
        });
        return;
      }

      await route.fulfill({
        status: 200,
        headers,
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
        headers,
        body: JSON.stringify({ detail: "No refresh token" }),
      });
      return;
    }

    // Dashboard data endpoints (return empty lists so the dashboard renders)
    if (path === "/api/recordings" && method === "GET") {
      await route.fulfill({
        status: 200,
        headers,
        body: JSON.stringify([]),
      });
      return;
    }
    if (path === "/api/action-items" && method === "GET") {
      await route.fulfill({
        status: 200,
        headers,
        body: JSON.stringify([]),
      });
      return;
    }
    if (path === "/api/entities" && method === "GET") {
      await route.fulfill({
        status: 200,
        headers,
        body: JSON.stringify([]),
      });
      return;
    }

    // Unhandled route
    await route.fulfill({
      status: 404,
      headers,
      body: JSON.stringify({ detail: `Unhandled mock route: ${method} ${path}` }),
    });
  };

  await page.route("**/api/**", handler);
}

async function fillEmailAfterHydration(page: Page, email: string) {
  await page.getByTestId("auth-email").fill(email);
  await expect(page.getByTestId("magic-link-button")).toBeEnabled();
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
    await fillEmailAfterHydration(page, "test@example.com");
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
    await fillEmailAfterHydration(page, "newuser@example.com");
    await page.getByTestId("auth-password").fill("securePass1");
    await page.getByTestId("auth-submit").click();

    // Should redirect to dashboard
    await expect(page).toHaveURL(/\/dashboard/);
    await expect(page.getByTestId("user-email")).toContainText("test@example.com");
  });

  test("login with wrong credentials shows error message", async ({ page }) => {
    await page.goto("/login");

    await fillEmailAfterHydration(page, "wrong@example.com");
    await page.getByTestId("auth-password").fill("wrongpassword");
    await page.getByTestId("auth-submit").click();

    // The error message from the mock is "Invalid credentials"
    await expect(page.getByTestId("auth-message")).toContainText("Invalid credentials");

    // Should remain on the login page
    await expect(page).toHaveURL(/\/login/);
  });

  // TODO(web-auth): middleware-based redirect was removed in 4f4b200b
  // ("remove orphaned proxy.ts"). Unauthenticated access to /dashboard is
  // now gated client-side. Re-enable when we reintroduce a Next middleware
  // or rewrite this assertion to drive the client-side gate.
  test.skip("middleware redirects unauthenticated users from /dashboard to /login", async ({ page }) => {
    await page.context().clearCookies();
    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/login/);
  });

  test("magic link request shows success message", async ({ page }) => {
    await page.goto("/login");

    // The magic link button is disabled until an email is entered
    await expect(page.getByTestId("magic-link-button")).toBeDisabled();

    // Enter an email, then click the magic link button
    await fillEmailAfterHydration(page, "test@example.com");
    await page.getByTestId("magic-link-button").click();

    // Should show the success message from the mock
    await expect(page.getByTestId("auth-message")).toContainText("Magic link sent to your email");
  });

  test("home page shows download CTAs", async ({ page }) => {
    await page.goto("/");

    await expect(page).toHaveURL(/\/$/);

    const macLink = page.getByTestId("download-mac");
    await expect(macLink).toHaveAttribute(
      "href",
      "/releases/macos/WaiSay-latest.dmg",
    );
    await expect(macLink).toHaveAttribute("download", "");

    const iosLink = page.getByTestId("download-ios");
    await expect(iosLink).toHaveAttribute(
      "href",
      "https://apps.apple.com/app/waisay/id6761768729",
    );

    await expect(page.getByRole("link", { name: /sign in/i })).toHaveAttribute(
      "href",
      "/login",
    );
  });

  test("magic link verification with valid token redirects to dashboard", async ({ page }) => {
    await page.goto("/auth/verify?token=valid-token");

    await expect(page).toHaveURL(/\/dashboard/);
    await expect(page.getByTestId("user-email")).toContainText("test@example.com");
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
