import { afterEach, describe, expect, it } from "vitest";

import { resolveApiProxyTarget } from "../next.config";

const originalApiBaseUrl = process.env.API_BASE_URL;
const originalPublicApiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;
const originalNodeEnv = process.env.NODE_ENV;

afterEach(() => {
  process.env.API_BASE_URL = originalApiBaseUrl;
  process.env.NEXT_PUBLIC_API_BASE_URL = originalPublicApiBaseUrl;
  process.env.NODE_ENV = originalNodeEnv;
});

describe("resolveApiProxyTarget", () => {
  it("prefers the internal API host when API_BASE_URL is set", () => {
    process.env.API_BASE_URL = "http://api:8000/";
    process.env.NEXT_PUBLIC_API_BASE_URL = "";
    process.env.NODE_ENV = "production";

    expect(resolveApiProxyTarget()).toBe("http://api:8000");
  });

  it("falls back to the public production host when no override is set", () => {
    delete process.env.API_BASE_URL;
    delete process.env.NEXT_PUBLIC_API_BASE_URL;
    process.env.NODE_ENV = "production";

    expect(resolveApiProxyTarget()).toBe("https://say.waiwai.is");
  });

  it("uses the local backend in development", () => {
    delete process.env.API_BASE_URL;
    delete process.env.NEXT_PUBLIC_API_BASE_URL;
    process.env.NODE_ENV = "development";

    expect(resolveApiProxyTarget()).toBe("http://127.0.0.1:8000");
  });
});
