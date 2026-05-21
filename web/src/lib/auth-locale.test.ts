import { describe, expect, it } from "vitest";
import {
  normalizeAuthLocale,
  resolveAuthLocaleFromAcceptLanguage,
} from "./auth-locale";

describe("auth locale helpers", () => {
  it("normalizes explicit auth locale values", () => {
    expect(normalizeAuthLocale("ru")).toBe("ru");
    expect(normalizeAuthLocale("ru-RU")).toBe("ru");
    expect(normalizeAuthLocale("en-US")).toBe("en");
    expect(normalizeAuthLocale(null)).toBe("en");
  });

  it("resolves preferred browser locale from Accept-Language", () => {
    expect(resolveAuthLocaleFromAcceptLanguage("ru-RU,ru;q=0.9,en-US;q=0.8")).toBe("ru");
    expect(resolveAuthLocaleFromAcceptLanguage("en-US,ru;q=0.9")).toBe("en");
    expect(resolveAuthLocaleFromAcceptLanguage("en-US;q=0.4,ru;q=0.9")).toBe("ru");
  });
});
