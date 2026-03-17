import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiFetch, getApiBaseUrl, syncLocalhostAuthCookie } from "./http";

const originalEnv = process.env.NEXT_PUBLIC_API_BASE_URL;

afterEach(() => {
  process.env.NEXT_PUBLIC_API_BASE_URL = originalEnv;
  vi.restoreAllMocks();
});

describe("getApiBaseUrl", () => {
  it("returns configured API base URL", () => {
    process.env.NEXT_PUBLIC_API_BASE_URL = "https://example.com";
    expect(getApiBaseUrl()).toBe("https://example.com");
  });

  it("returns default API base URL", () => {
    delete process.env.NEXT_PUBLIC_API_BASE_URL;
    expect(getApiBaseUrl()).toBe("");
  });

  it("preserves empty API base URL for same-origin proxy mode", () => {
    process.env.NEXT_PUBLIC_API_BASE_URL = "";
    expect(getApiBaseUrl()).toBe("");
  });
});

describe("apiFetch", () => {
  it("returns JSON payload for successful JSON response", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(apiFetch<{ ok: boolean }>("/ok")).resolves.toEqual({ ok: true });
  });

  it("returns null for empty JSON response body", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response("", {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(apiFetch<null>("/empty-json")).resolves.toBeNull();
  });

  it("returns raw text for invalid JSON body with JSON content-type", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response("not-json", {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(apiFetch<string>("/invalid-json")).resolves.toBe("not-json");
  });

  it("parses text payload as JSON when possible", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response('{"ok":true}', {
        status: 200,
        headers: { "Content-Type": "text/plain" },
      }),
    );

    await expect(apiFetch<{ ok: boolean }>("/text-json")).resolves.toEqual({ ok: true });
  });

  it("returns raw text payload when non-json body is not JSON", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response("plain text", {
        status: 200,
        headers: { "Content-Type": "text/plain" },
      }),
    );

    await expect(apiFetch<string>("/text-raw")).resolves.toBe("plain text");
  });

  it("returns null for empty successful non-json response", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response("", {
        status: 200,
        headers: { "Content-Type": "text/plain" },
      }),
    );

    await expect(apiFetch<null>("/empty")).resolves.toBeNull();
  });

  it("handles explicit empty content-type header", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response("plain text", {
        status: 200,
        headers: { "Content-Type": "" },
      }),
    );

    await expect(apiFetch<string>("/empty-content-type")).resolves.toBe("plain text");
  });

  it("throws ApiError with detail message from JSON error payload", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Bad request" }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(apiFetch("/bad")).rejects.toMatchObject({
      name: "ApiError",
      status: 400,
      message: "Bad request",
    });
  });

  it("throws ApiError with fallback message when payload has no detail", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ error: "x" }), {
        status: 500,
        headers: { "Content-Type": "application/json" },
      }),
    );

    try {
      await apiFetch("/fallback");
    } catch (error: unknown) {
      expect(error).toBeInstanceOf(ApiError);
      const apiError = error as ApiError;
      expect(apiError.status).toBe(500);
      expect(apiError.message).toBe("API request failed");
      expect(apiError.payload).toEqual({ error: "x" });
    }
  });

  it("throws ApiError with fallback message when payload is null", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response("", {
        status: 500,
      }),
    );

    await expect(apiFetch("/null-error")).rejects.toMatchObject({
      name: "ApiError",
      status: 500,
      message: "API request failed",
      payload: null,
    });
  });

  it("retries original request after successful 401 token refresh", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");

    // First call: 401
    fetchSpy.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Unauthorized" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      }),
    );

    // Refresh call: 200
    fetchSpy.mockResolvedValueOnce(
      new Response("", { status: 200 }),
    );

    // Retry of original call: 200 with data
    fetchSpy.mockResolvedValueOnce(
      new Response(JSON.stringify({ data: "refreshed" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    const result = await apiFetch<{ data: string }>("/protected");
    expect(result).toEqual({ data: "refreshed" });
    expect(fetchSpy).toHaveBeenCalledTimes(3);
  });

  it("throws original 401 error when token refresh fails", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");

    // First call: 401
    fetchSpy.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Unauthorized" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      }),
    );

    // Refresh call: 403
    fetchSpy.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Forbidden" }), {
        status: 403,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(apiFetch("/protected")).rejects.toMatchObject({
      name: "ApiError",
      status: 401,
      message: "Unauthorized",
    });
    expect(fetchSpy).toHaveBeenCalledTimes(2);
  });

  it("throws retry error when refresh succeeds but retry fails", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");

    // First call: 401
    fetchSpy.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Unauthorized" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      }),
    );

    // Refresh call: 200
    fetchSpy.mockResolvedValueOnce(
      new Response("", { status: 200 }),
    );

    // Retry of original call: 500
    fetchSpy.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Internal Server Error" }), {
        status: 500,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(apiFetch("/protected")).rejects.toMatchObject({
      name: "ApiError",
      status: 500,
      message: "Internal Server Error",
    });
    expect(fetchSpy).toHaveBeenCalledTimes(3);
  });

  it("falls through to original 401 when token refresh throws network error", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");

    // First call: 401
    fetchSpy.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Token expired" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      }),
    );

    // Refresh call: network error (throws)
    fetchSpy.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    await expect(apiFetch("/protected")).rejects.toMatchObject({
      name: "ApiError",
      status: 401,
      message: "Token expired",
    });
    expect(fetchSpy).toHaveBeenCalledTimes(2);
  });

  it("throws ApiError for network error on initial request", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(
      new TypeError("Network unavailable"),
    );

    await expect(apiFetch("/fail")).rejects.toMatchObject({
      name: "ApiError",
      status: 0,
      message: "Network error — check your connection",
    });
  });

  it("syncs localhost auth cookie after successful token refresh", async () => {
    // Simulate localhost environment
    const originalHostname = window.location.hostname;
    Object.defineProperty(window, "location", {
      value: { ...window.location, hostname: "localhost" },
      writable: true,
    });

    // Clear any existing cookie
    document.cookie = "wai_access_token=; Path=/; Max-Age=0; SameSite=Lax";

    const fetchSpy = vi.spyOn(globalThis, "fetch");

    // First call: 401
    fetchSpy.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Unauthorized" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      }),
    );

    // Refresh call: 200 with new token
    fetchSpy.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ access_token: "fresh-token-123", token_type: "bearer" }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    // Retry of original call: 200 with data
    fetchSpy.mockResolvedValueOnce(
      new Response(JSON.stringify({ data: "ok" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    const result = await apiFetch<{ data: string }>("/protected");
    expect(result).toEqual({ data: "ok" });
    expect(fetchSpy).toHaveBeenCalledTimes(3);

    // Verify the cookie was set with the new token
    expect(document.cookie).toContain("wai_access_token=fresh-token-123");

    // Restore
    Object.defineProperty(window, "location", {
      value: { ...window.location, hostname: originalHostname },
      writable: true,
    });
  });

  it("does not set cookie after refresh when not on localhost", async () => {
    // Ensure not on localhost (default jsdom hostname is "localhost", override it)
    const originalHostname = window.location.hostname;
    Object.defineProperty(window, "location", {
      value: { ...window.location, hostname: "wai.computer" },
      writable: true,
    });

    document.cookie = "wai_access_token=; Path=/; Max-Age=0; SameSite=Lax";

    const fetchSpy = vi.spyOn(globalThis, "fetch");

    // First call: 401
    fetchSpy.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Unauthorized" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      }),
    );

    // Refresh call: 200 with new token
    fetchSpy.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ access_token: "fresh-token-456", token_type: "bearer" }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    // Retry of original call: 200 with data
    fetchSpy.mockResolvedValueOnce(
      new Response(JSON.stringify({ data: "ok" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await apiFetch<{ data: string }>("/protected");

    // Cookie should NOT be set since we're not on localhost
    expect(document.cookie).not.toContain("wai_access_token=fresh-token-456");

    // Restore
    Object.defineProperty(window, "location", {
      value: { ...window.location, hostname: originalHostname },
      writable: true,
    });
  });

  it("handles refresh response without access_token gracefully", async () => {
    const originalHostname = window.location.hostname;
    Object.defineProperty(window, "location", {
      value: { ...window.location, hostname: "localhost" },
      writable: true,
    });

    document.cookie = "wai_access_token=; Path=/; Max-Age=0; SameSite=Lax";

    const fetchSpy = vi.spyOn(globalThis, "fetch");

    // First call: 401
    fetchSpy.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Unauthorized" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      }),
    );

    // Refresh call: 200 but empty body (no access_token)
    fetchSpy.mockResolvedValueOnce(
      new Response("", { status: 200 }),
    );

    // Retry of original call: 200 with data
    fetchSpy.mockResolvedValueOnce(
      new Response(JSON.stringify({ data: "ok" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    const result = await apiFetch<{ data: string }>("/protected");
    expect(result).toEqual({ data: "ok" });
    expect(fetchSpy).toHaveBeenCalledTimes(3);

    // Cookie should NOT be set since refresh had no token
    expect(document.cookie).not.toContain("wai_access_token=");

    Object.defineProperty(window, "location", {
      value: { ...window.location, hostname: originalHostname },
      writable: true,
    });
  });
});

describe("syncLocalhostAuthCookie", () => {
  beforeEach(() => {
    document.cookie = "wai_access_token=; Path=/; Max-Age=0; SameSite=Lax";
  });

  it("sets cookie on localhost", () => {
    const originalHostname = window.location.hostname;
    Object.defineProperty(window, "location", {
      value: { ...window.location, hostname: "localhost" },
      writable: true,
    });

    syncLocalhostAuthCookie("test-token");
    expect(document.cookie).toContain("wai_access_token=test-token");

    Object.defineProperty(window, "location", {
      value: { ...window.location, hostname: originalHostname },
      writable: true,
    });
  });

  it("clears cookie on localhost when token is null", () => {
    const originalHostname = window.location.hostname;
    Object.defineProperty(window, "location", {
      value: { ...window.location, hostname: "localhost" },
      writable: true,
    });

    syncLocalhostAuthCookie("test-token");
    expect(document.cookie).toContain("wai_access_token=test-token");

    syncLocalhostAuthCookie(null);
    expect(document.cookie).not.toContain("wai_access_token=test-token");

    Object.defineProperty(window, "location", {
      value: { ...window.location, hostname: originalHostname },
      writable: true,
    });
  });

  it("does nothing when not on localhost", () => {
    const originalHostname = window.location.hostname;
    Object.defineProperty(window, "location", {
      value: { ...window.location, hostname: "wai.computer" },
      writable: true,
    });

    syncLocalhostAuthCookie("test-token");
    expect(document.cookie).not.toContain("wai_access_token=test-token");

    Object.defineProperty(window, "location", {
      value: { ...window.location, hostname: originalHostname },
      writable: true,
    });
  });
});
