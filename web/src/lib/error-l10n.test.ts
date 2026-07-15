import { describe, expect, it } from "vitest";
import { localizeErrorMessage } from "./error-l10n";

describe("localizeErrorMessage", () => {
  it("translates known backend messages for RU users", () => {
    expect(localizeErrorMessage("Recording not found", "ru")).toBe(
      "Запись не найдена",
    );
    expect(
      localizeErrorMessage("Your session ended. Please sign in again.", "ru"),
    ).toBe("Сессия истекла. Войдите снова.");
  });

  it("passes unknown messages through untouched — no error hiding", () => {
    expect(localizeErrorMessage("Weird bespoke failure", "ru")).toBe(
      "Weird bespoke failure",
    );
  });

  it("returns EN messages as-is for EN users", () => {
    expect(localizeErrorMessage("Recording not found", "en")).toBe(
      "Recording not found",
    );
  });
});
