import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  apiFetch,
  apiFetchResponse,
  apiUpload,
  getApiBaseUrl,
  syncLocalhostAuthCookie,
  syncLocalhostRefreshCookie,
} from "./http";

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
      expect(apiError.message).toBe("Something went wrong. Please try again in a moment.");
      expect(apiError.payload).toEqual({ error: "x" });
    }
  });

  it("hides raw 500 detail messages from the backend", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          detail:
            "Connection lost after retrying. /Users/test/Library/Application Support/WaiSay/PendingTranscripts/example Failed to reconnect after 10 attempts.",
        }),
        {
          status: 500,
          headers: { "Content-Type": "application/json" },
        },
      ),
    );

    await expect(apiFetch("/server-error")).rejects.toMatchObject({
      name: "ApiError",
      status: 500,
      message: "Something went wrong. Please try again in a moment.",
    });
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
      message: "Something went wrong. Please try again in a moment.",
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
      message: "Something went wrong. Please try again in a moment.",
    });
    expect(fetchSpy).toHaveBeenCalledTimes(3);
  });

  it("hides raw provider configuration messages from users", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "ELEVENLABS_API_KEY not configured" }), {
        status: 500,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(apiFetch("/voice")).rejects.toMatchObject({
      name: "ApiError",
      status: 500,
      message: "Something went wrong. Please try again in a moment.",
    });
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
        JSON.stringify({
          access_token: "fresh-token-123",
          refresh_token: "fresh-refresh-123",
          token_type: "bearer",
        }),
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
    expect(document.cookie).toContain("wai_refresh_token=fresh-refresh-123");

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
      value: { ...window.location, hostname: "say.waiwai.is" },
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
    document.cookie = "wai_refresh_token=; Path=/; Max-Age=0; SameSite=Lax";
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
      value: { ...window.location, hostname: "say.waiwai.is" },
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

describe("syncLocalhostRefreshCookie", () => {
  beforeEach(() => {
    document.cookie = "wai_refresh_token=; Path=/; Max-Age=0; SameSite=Lax";
  });

  it("sets refresh cookie on localhost", () => {
    const originalHostname = window.location.hostname;
    Object.defineProperty(window, "location", {
      value: { ...window.location, hostname: "localhost" },
      writable: true,
    });

    syncLocalhostRefreshCookie("refresh-token");
    expect(document.cookie).toContain("wai_refresh_token=refresh-token");

    Object.defineProperty(window, "location", {
      value: { ...window.location, hostname: originalHostname },
      writable: true,
    });
  });

  it("clears refresh cookie on localhost when token is null", () => {
    const originalHostname = window.location.hostname;
    Object.defineProperty(window, "location", {
      value: { ...window.location, hostname: "localhost" },
      writable: true,
    });

    syncLocalhostRefreshCookie("refresh-token");
    expect(document.cookie).toContain("wai_refresh_token=refresh-token");

    syncLocalhostRefreshCookie(null);
    expect(document.cookie).not.toContain("wai_refresh_token=refresh-token");

    Object.defineProperty(window, "location", {
      value: { ...window.location, hostname: originalHostname },
      writable: true,
    });
  });
});

describe("apiFetchResponse", () => {
  it("returns raw Response for successful request", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response("file content", {
        status: 200,
        headers: { "Content-Type": "text/plain" },
      }),
    );

    const response = await apiFetchResponse("/api/export");
    expect(response).toBeInstanceOf(Response);
    const text = await response.text();
    expect(text).toBe("file content");
  });

  it("throws ApiError for non-ok response", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Not found" }), {
        status: 404,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(apiFetchResponse("/api/missing")).rejects.toMatchObject({
      name: "ApiError",
      status: 404,
      message: "Not found",
    });
  });

  it("throws ApiError with fallback for 500 errors", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Internal Server Error" }), {
        status: 500,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(apiFetchResponse("/api/fail")).rejects.toMatchObject({
      name: "ApiError",
      status: 500,
      message: "Something went wrong. Please try again in a moment.",
    });
  });

  it("retries after 401 token refresh", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");

    // First call: 401
    fetchSpy.mockResolvedValueOnce(
      new Response("", { status: 401 }),
    );

    // Refresh call: 200
    fetchSpy.mockResolvedValueOnce(
      new Response("", { status: 200 }),
    );

    // Retry: 200 with content
    fetchSpy.mockResolvedValueOnce(
      new Response("exported data", {
        status: 200,
        headers: { "Content-Type": "text/plain" },
      }),
    );

    const response = await apiFetchResponse("/api/export");
    const text = await response.text();
    expect(text).toBe("exported data");
    expect(fetchSpy).toHaveBeenCalledTimes(3);
  });

  it("throws original 401 when refresh fails", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");

    // First call: 401
    fetchSpy.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Expired" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      }),
    );

    // Refresh call: 403
    fetchSpy.mockResolvedValueOnce(
      new Response("", { status: 403 }),
    );

    await expect(apiFetchResponse("/api/export")).rejects.toMatchObject({
      name: "ApiError",
      status: 401,
    });
  });

  it("syncs localhost cookie after refresh with tokens", async () => {
    const originalHostname = window.location.hostname;
    Object.defineProperty(window, "location", {
      value: { ...window.location, hostname: "localhost" },
      writable: true,
    });

    document.cookie = "wai_access_token=; Path=/; Max-Age=0; SameSite=Lax";

    const fetchSpy = vi.spyOn(globalThis, "fetch");

    fetchSpy.mockResolvedValueOnce(
      new Response("", { status: 401 }),
    );

    fetchSpy.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          access_token: "new-access",
          refresh_token: "new-refresh",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    fetchSpy.mockResolvedValueOnce(
      new Response("ok", { status: 200 }),
    );

    await apiFetchResponse("/api/export");
    expect(document.cookie).toContain("wai_access_token=new-access");
    expect(document.cookie).toContain("wai_refresh_token=new-refresh");

    Object.defineProperty(window, "location", {
      value: { ...window.location, hostname: originalHostname },
      writable: true,
    });
  });

  it("throws ApiError on network error", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(
      new TypeError("Network unavailable"),
    );

    await expect(apiFetchResponse("/api/export")).rejects.toMatchObject({
      name: "ApiError",
      status: 0,
      message: "Network error — check your connection",
    });
  });

  it("falls through on refresh network error", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");

    fetchSpy.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Token expired" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      }),
    );

    // Refresh throws network error
    fetchSpy.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    await expect(apiFetchResponse("/api/export")).rejects.toMatchObject({
      name: "ApiError",
      status: 401,
    });
  });
});

describe("apiUpload", () => {
  it("syncs localhost access and refresh cookies after successful token refresh", async () => {
    const originalHostname = window.location.hostname;
    Object.defineProperty(window, "location", {
      value: { ...window.location, hostname: "localhost" },
      writable: true,
    });

    document.cookie = "wai_access_token=; Path=/; Max-Age=0; SameSite=Lax";
    document.cookie = "wai_refresh_token=; Path=/; Max-Age=0; SameSite=Lax";

    const fetchSpy = vi.spyOn(globalThis, "fetch");

    fetchSpy.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "Unauthorized" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      }),
    );

    fetchSpy.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          access_token: "upload-access-token",
          refresh_token: "upload-refresh-token",
          token_type: "bearer",
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    fetchSpy.mockResolvedValueOnce(
      new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    const formData = new FormData();
    formData.append("file", new File(["audio"], "upload.opus", { type: "audio/opus" }));

    await expect(apiUpload<{ ok: boolean }>("/api/upload", formData)).resolves.toEqual({ ok: true });
    expect(document.cookie).toContain("wai_access_token=upload-access-token");
    expect(document.cookie).toContain("wai_refresh_token=upload-refresh-token");

    Object.defineProperty(window, "location", {
      value: { ...window.location, hostname: originalHostname },
      writable: true,
    });
  });
});
