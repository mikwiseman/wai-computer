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
async function installAuthMocks(
  page: Page,
  options: { enrolledVoice?: boolean } = {},
) {
  // Fresh accounts (default) route to onboarding after auth; pass
  // enrolledVoice: true to model a returning user who lands on /dashboard.
  const enrolledVoice = options.enrolledVoice ?? false;
  let isAuthenticated = false;
  let authenticatedEmail = "test@example.com";
  let lastMagicLinkRequest: unknown = null;
  let lastPasswordResetRequest: unknown = null;
  let lastResetPasswordRequest: unknown = null;

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
        authenticatedEmail = body.email;
        await route.fulfill({
          status: 200,
          headers: { ...headers, ...authCookieHeader },
          body: JSON.stringify({
            access_token: "mock-token",
            refresh_token: "mock-refresh-token",
            token_type: "bearer",
          }),
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
      const body = request.postDataJSON() as { email?: string };
      isAuthenticated = true;
      authenticatedEmail = body?.email || "test@example.com";
      await route.fulfill({
        status: 200,
        headers: { ...headers, ...authCookieHeader },
        body: JSON.stringify({
          access_token: "mock-token",
          refresh_token: "mock-refresh-token",
          token_type: "bearer",
        }),
      });
      return;
    }

    // POST /api/auth/magic-link
    if (path === "/api/auth/magic-link" && method === "POST") {
      lastMagicLinkRequest = request.postDataJSON();
      await route.fulfill({
        status: 200,
        headers,
        body: JSON.stringify({ message: "Magic link sent to your email" }),
      });
      return;
    }

    // POST /api/auth/forgot-password
    if (path === "/api/auth/forgot-password" && method === "POST") {
      lastPasswordResetRequest = request.postDataJSON();
      await route.fulfill({
        status: 200,
        headers,
        body: JSON.stringify({ message: "Detailed server response should not be shown" }),
      });
      return;
    }

    // POST /api/auth/reset-password
    if (path === "/api/auth/reset-password" && method === "POST") {
      lastResetPasswordRequest = request.postDataJSON();
      const body = lastResetPasswordRequest as { token?: string; password?: string };
      if (body?.token === "reset-token" && body?.password === "password123") {
        await route.fulfill({
          status: 200,
          headers,
          body: JSON.stringify({ message: "Password reset successfully" }),
        });
        return;
      }
      await route.fulfill({
        status: 401,
        headers,
        body: JSON.stringify({ detail: "Password reset link expired" }),
      });
      return;
    }

    // POST /api/auth/verify-magic (used by the verify page)
    if (path === "/api/auth/verify-magic" && method === "POST") {
      const body = request.postDataJSON() as { token?: string };
      if (body?.token === "valid-token") {
        isAuthenticated = true;
        authenticatedEmail = "magic@example.com";
        await route.fulfill({
          status: 200,
          headers: { ...headers, ...authCookieHeader },
          body: JSON.stringify({
            access_token: "mock-token",
            refresh_token: "mock-refresh-token",
            token_type: "bearer",
          }),
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
          email: authenticatedEmail,
          created_at: "2026-01-01T00:00:00Z",
          has_password: true,
          has_enrolled_voice: enrolledVoice,
          region: "global",
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
    if (path === "/api/folders" && method === "GET") {
      await route.fulfill({
        status: 200,
        headers,
        body: JSON.stringify([]),
      });
      return;
    }
    if (path === "/api/inbox" && method === "GET") {
      await route.fulfill({
        status: 200,
        headers,
        body: JSON.stringify({ rows: [], next_cursor: null, has_more: false }),
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
  return {
    lastMagicLinkRequest: () => lastMagicLinkRequest,
    lastPasswordResetRequest: () => lastPasswordResetRequest,
    lastResetPasswordRequest: () => lastResetPasswordRequest,
  };
}

async function fillEmailAfterHydration(page: Page, email: string) {
  await page.getByTestId("auth-email").fill(email);
  const legalConsent = page.getByTestId("legal-consent-checkbox");
  if (await legalConsent.count()) {
    await legalConsent.check();
  }
  await expect(page.getByTestId("magic-link-button")).toBeEnabled();
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

test.describe("Auth flow", () => {
  let authRequests: Awaited<ReturnType<typeof installAuthMocks>>;

  test.beforeEach(async ({ page }) => {
    authRequests = await installAuthMocks(page);
  });

  test("login with valid credentials redirects to dashboard", async ({ page }) => {
    // Returning, voice-enrolled user — the fresh-user onboarding path is
    // covered by the register + magic-link tests below.
    await installAuthMocks(page, { enrolledVoice: true });
    await page.goto("/login");

    // Login and registration share one account gateway; password remains a
    // quiet recovery path for returning users.
    await expect(page.locator("h1")).toContainText("Start anywhere. Continue everywhere.");

    // Fill in credentials and submit
    await fillEmailAfterHydration(page, "test@example.com");
    await page.getByTestId("password-mode-button").click();
    await page.getByTestId("auth-password").fill("password123");
    await page.getByTestId("auth-submit").click();

    // Should redirect to the dashboard and display the user email
    await expect(page).toHaveURL(/\/dashboard/);
    await expect(page.getByTestId("user-email")).toContainText("test@example.com");
  });

  test("register route renders the unified passwordless account gateway", async ({ page }) => {
    await page.goto("/register");

    await expect(page.locator("h1")).toContainText("Start anywhere. Continue everywhere.");
    await expect(page.getByTestId("magic-link-button")).toContainText("Continue");
    await expect(page.getByTestId("password-mode-button")).toContainText("Use password");
    await expect(page.getByText(/^Create account$/)).toHaveCount(0);
  });

  test("login with wrong credentials shows error message", async ({ page }) => {
    await page.goto("/login");

    await fillEmailAfterHydration(page, "wrong@example.com");
    await page.getByTestId("password-mode-button").click();
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

    // The unified gateway keeps one primary Continue action visible.
    await expect(page.getByTestId("magic-link-button")).toBeEnabled();
    await expect(page.getByTestId("magic-link-button")).toContainText("Continue");

    // Enter an email, then click the magic link button
    await fillEmailAfterHydration(page, "test@example.com");
    await page.getByTestId("magic-link-button").click();

    // Should swap the form for the "check your email" confirmation state
    await expect(page.getByTestId("magic-link-sent")).toContainText("Check your email");
    await expect(page.getByTestId("magic-link-sent")).toContainText("test@example.com");
    expect(authRequests.lastMagicLinkRequest()).toEqual({
      email: "test@example.com",
      locale: "en",
      region: "global",
      accepted_legal_terms: true,
      legal_terms_version: "2026-05-22",
      legal_privacy_version: "2026-05-22",
    });
  });

  test("new email register primary flow requests a magic link", async ({ page }) => {
    await page.goto("/register");

    await fillEmailAfterHydration(page, "brand-new@example.com");
    await page.getByTestId("magic-link-button").click();

    await expect(page.getByTestId("magic-link-sent")).toContainText("Check your email");
    expect(authRequests.lastMagicLinkRequest()).toEqual({
      email: "brand-new@example.com",
      locale: "en",
      region: "global",
      accepted_legal_terms: true,
      legal_terms_version: "2026-05-22",
      legal_privacy_version: "2026-05-22",
    });
    await expect(page).toHaveURL(/\/register/);
  });

  test("password reset request and reset page use localized non-enumerating copy", async ({ page }) => {
    await page.goto("/login");

    await fillEmailAfterHydration(page, "reset@example.com");
    await page.getByTestId("password-mode-button").click();
    await page.getByTestId("forgot-password-button").click();
    await page.getByTestId("forgot-password-submit").click();

    await expect(page.getByTestId("auth-message")).toContainText(
      "If this email is registered, we sent a password reset link.",
    );
    expect(authRequests.lastPasswordResetRequest()).toEqual({
      email: "reset@example.com",
      locale: "en",
    });

    await page.goto("/auth/reset?token=reset-token&locale=ru");
    await expect(page.locator("h1")).toContainText("Сброс пароля");
    await page.getByTestId("reset-password").fill("password123");
    await page.getByTestId("reset-password-confirm").fill("password123");
    await page.getByTestId("reset-password-submit").click();

    await expect(page.getByTestId("reset-password-message")).toContainText(
      "Пароль обновлён. Войдите ниже.",
    );
    expect(authRequests.lastResetPasswordRequest()).toEqual({
      token: "reset-token",
      password: "password123",
      locale: "ru",
    });
  });

  test("app-open page exposes app link and browser fallback", async ({ page }) => {
    await page.goto("/auth/app?token=valid-token&client=macos&locale=ru");

    await expect(page.locator("h1")).toContainText("Открыть в WaiComputer");
    await expect(page.getByTestId("open-app-link")).toHaveAttribute(
      "href",
      "waicomputer://auth/verify?token=valid-token",
    );
    await expect(page.getByTestId("browser-sign-in-link")).toHaveAttribute(
      "href",
      "/auth/verify?token=valid-token&locale=ru",
    );

    await page.getByTestId("browser-sign-in-link").click();
    await expect(page).toHaveURL(/\/onboarding/);
  });

  test("home page shows download CTAs", async ({ page }) => {
    await page.goto("/");

    await expect(page).toHaveURL(/\/$/);

    const macLink = page.getByTestId("download-mac");
    await expect(macLink).toHaveAttribute(
      "href",
      "/releases/macos/WaiComputer-latest.dmg",
    );
    await expect(macLink).toHaveAttribute("download", "");

    const iosLink = page.getByTestId("download-ios");
    await expect(iosLink).toHaveAttribute(
      "href",
      "https://testflight.apple.com/join/rtnJQzwk",
    );
    await expect(iosLink).toContainText("TestFlight");

    await expect(page.getByRole("link", { name: /sign in/i })).toHaveAttribute(
      "href",
      "/login",
    );
  });

  test("Russian home page shows Web CTA and current RUB pricing", async ({ page }) => {
    await page.goto("/ru");

    const webLink = page.getByTestId("download-web-ru");
    await expect(webLink).toHaveAttribute("href", "/dashboard");
    await expect(webLink).toContainText("Открыть Web");

    await expect(page.getByTestId("platform-web-ru")).toHaveAttribute(
      "href",
      "/dashboard",
    );
    await expect(page.getByText("999 ₽")).toBeVisible();
    await expect(page.getByText("1290 ₽")).toHaveCount(0);
  });

  test("magic link verification with valid token redirects new users to onboarding", async ({ page }) => {
    await page.goto("/auth/verify?token=valid-token");

    await expect(page).toHaveURL(/\/onboarding/);
    await expect(page.getByRole("heading", { name: "Teach Wai your voice" })).toBeVisible();
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

test.describe("Auth flow with Russian browser locale", () => {
  test.use({ locale: "ru-RU" });

  test("login and app-open fallback use Russian browser locale without query params", async ({ page }) => {
    const authRequests = await installAuthMocks(page);
    const runtimeErrors: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "error") {
        runtimeErrors.push(message.text());
      }
    });
    page.on("pageerror", (error) => {
      runtimeErrors.push(error.message);
    });

    await page.goto("/login");
    await expect(page.locator("h1")).toContainText("Начни где удобно. Продолжай везде.");
    await expect(page.getByTestId("magic-link-button")).toContainText("Продолжить");

    await fillEmailAfterHydration(page, "ru@example.com");
    await page.getByTestId("magic-link-button").click();

    await expect(page.getByTestId("magic-link-sent")).toContainText("Проверь почту");
    expect(authRequests.lastMagicLinkRequest()).toEqual({
      email: "ru@example.com",
      locale: "ru",
      region: "ru",
      accepted_legal_terms: true,
      legal_terms_version: "2026-05-22",
      legal_privacy_version: "2026-05-22",
    });

    await page.goto("/auth/app?token=valid-token&client=macos");
    await expect(page.locator("h1")).toContainText("Открыть в WaiComputer");
    await expect(page.getByTestId("browser-sign-in-link")).toHaveAttribute(
      "href",
      "/auth/verify?token=valid-token&locale=ru",
    );
    expect(
      runtimeErrors.filter(
        (message) =>
          message.includes("Hydration failed")
          || message.includes("server rendered text didn't match"),
      ),
    ).toEqual([]);
  });
});
