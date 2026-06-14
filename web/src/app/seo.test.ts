import { describe, expect, it } from "vitest";

import { metadata as homeMetadata } from "./page";
import { metadata as privacyMetadata } from "./privacy/page";
import robots from "./robots";
import { metadata as ruPrivacyMetadata } from "./ru/privacy/page";
import { metadata as ruTermsMetadata } from "./ru/terms/page";
import sitemap from "./sitemap";
import { metadata as termsMetadata } from "./terms/page";

describe("robots.ts", () => {
  it("exposes a single rule that allows / and disallows private surfaces", () => {
    const result = robots();
    const rule = Array.isArray(result.rules) ? result.rules[0] : result.rules;
    expect(rule.userAgent).toBe("*");
    expect(rule.allow).toBe("/");
    // Sentry replay + magic-link tokens live behind /auth and /share; never index them.
    expect(rule.disallow).toEqual(
      expect.arrayContaining([
        "/api/",
        "/dashboard",
        "/billing",
        "/login",
        "/register",
        "/onboarding",
        "/auth/",
        "/admin",
        "/share/",
      ]),
    );
  });

  it("points at /sitemap.xml on the canonical host", () => {
    const result = robots();
    expect(result.sitemap).toBe("https://wai.computer/sitemap.xml");
    expect(result.host).toBe("https://wai.computer");
  });
});

describe("sitemap.ts", () => {
  it("includes all public routes for both locales", () => {
    const entries = sitemap();
    const urls = entries.map((entry) => entry.url);
    for (const path of [
      "https://wai.computer",
      "https://wai.computer/ru",
      "https://wai.computer/pricing",
      "https://wai.computer/ru/pricing",
      "https://wai.computer/privacy",
      "https://wai.computer/ru/privacy",
      "https://wai.computer/terms",
      "https://wai.computer/ru/terms",
      "https://wai.computer/benchmarks/dictation",
      "https://wai.computer/ru/benchmarks/dictation",
    ]) {
      expect(urls).toContain(path);
    }
  });

  it("never leaks private routes (dashboard, share, admin, auth)", () => {
    const urls = sitemap().map((entry) => entry.url);
    for (const fragment of [
      "/dashboard",
      "/billing",
      "/login",
      "/register",
      "/onboarding",
      "/auth/",
      "/admin",
      "/share/",
    ]) {
      for (const url of urls) {
        expect(url).not.toContain(fragment);
      }
    }
  });

  it("assigns higher priority to the landing pages", () => {
    const entries = sitemap();
    const landingEn = entries.find((entry) => entry.url === "https://wai.computer");
    const landingRu = entries.find((entry) => entry.url === "https://wai.computer/ru");
    const pricing = entries.find((entry) => entry.url === "https://wai.computer/pricing");
    expect(landingEn?.priority).toBe(1.0);
    expect(landingRu?.priority).toBe(1.0);
    expect(pricing?.priority).toBe(0.6);
  });
});

describe("public page metadata", () => {
  it("exposes reciprocal canonical and hreflang alternates", () => {
    expect(homeMetadata.alternates).toEqual({
      canonical: "https://wai.computer",
      languages: {
        en: "https://wai.computer",
        ru: "https://wai.computer/ru",
      },
    });
    expect(termsMetadata.alternates).toEqual({
      canonical: "https://wai.computer/terms",
      languages: {
        en: "https://wai.computer/terms",
        ru: "https://wai.computer/ru/terms",
      },
    });
    expect(ruTermsMetadata.alternates).toEqual({
      canonical: "https://wai.computer/ru/terms",
      languages: {
        en: "https://wai.computer/terms",
        ru: "https://wai.computer/ru/terms",
      },
    });
    expect(privacyMetadata.alternates).toEqual({
      canonical: "https://wai.computer/privacy",
      languages: {
        en: "https://wai.computer/privacy",
        ru: "https://wai.computer/ru/privacy",
      },
    });
    expect(ruPrivacyMetadata.alternates).toEqual({
      canonical: "https://wai.computer/ru/privacy",
      languages: {
        en: "https://wai.computer/privacy",
        ru: "https://wai.computer/ru/privacy",
      },
    });
  });
});
