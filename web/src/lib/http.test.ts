import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiFetch, getApiBaseUrl } from "./http";

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
    expect(getApiBaseUrl()).toBe("https://api.wai.computer");
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
});
