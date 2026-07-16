import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";

import { ThemeToggle } from "./ThemeToggle";
import { ApiError } from "@/lib/http";
import { updatePreferences } from "@/lib/api";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    updatePreferences: vi.fn(),
  };
});

const mockedUpdatePreferences = vi.mocked(updatePreferences);

let localStorageValues: Record<string, string>;
let setItemSpy: ReturnType<typeof vi.fn>;

// Drain the microtask queue so the debounced PATCH's `.catch` runs under fake
// timers (used by the 401 latch assertion).
async function flushMicrotasks(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe("ThemeToggle", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    localStorageValues = {};
    setItemSpy = vi.fn((key: string, value: string) => {
      localStorageValues[key] = value;
    });

    Object.defineProperty(window, "localStorage", {
      configurable: true,
      value: {
        getItem: vi.fn((key: string) => localStorageValues[key] ?? null),
        setItem: setItemSpy,
        removeItem: vi.fn((key: string) => {
          delete localStorageValues[key];
        }),
        clear: vi.fn(() => {
          localStorageValues = {};
        }),
        key: vi.fn((index: number) => Object.keys(localStorageValues)[index] ?? null),
        get length() {
          return Object.keys(localStorageValues).length;
        },
      },
    });

    // jsdom has no matchMedia; the toggle guards for it, but the "system"
    // subscription path exercises it, so provide a stable stub.
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      value: vi.fn((query: string) => ({
        matches: false,
        media: query,
        onchange: null,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        addListener: vi.fn(),
        removeListener: vi.fn(),
        dispatchEvent: vi.fn(),
      })),
    });

    document.documentElement.removeAttribute("data-theme");
    mockedUpdatePreferences.mockReset();
    mockedUpdatePreferences.mockResolvedValue({ theme: "system", accent: "amber" });
  });

  afterEach(() => {
    vi.useRealTimers();
    cleanup();
  });

  it("renders three theme radios", () => {
    render(<ThemeToggle locale="en" />);
    expect(screen.getAllByRole("radio")).toHaveLength(3);
    expect(screen.getByTestId("theme-toggle-system")).toBeTruthy();
    expect(screen.getByTestId("theme-toggle-light")).toBeTruthy();
    expect(screen.getByTestId("theme-toggle-dark")).toBeTruthy();
  });

  it("renders Russian labels when locale is ru", () => {
    render(<ThemeToggle locale="ru" />);
    expect(screen.getByTestId("theme-toggle-system").getAttribute("aria-label")).toBe("Системная");
    expect(screen.getByTestId("theme-toggle-light").getAttribute("aria-label")).toBe("Жемчужная");
    expect(screen.getByTestId("theme-toggle-dark").getAttribute("aria-label")).toBe("Полночь");
    expect(screen.getByRole("radiogroup").getAttribute("aria-label")).toBe("Тема");
  });

  it("selecting Dark applies data-theme, writes localStorage, and PATCHes preferences", async () => {
    render(<ThemeToggle locale="en" />);

    fireEvent.click(screen.getByTestId("theme-toggle-dark"));

    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(screen.getByTestId("theme-toggle-dark").getAttribute("aria-checked")).toBe("true");
    expect(screen.getByTestId("theme-toggle-system").getAttribute("aria-checked")).toBe("false");
    expect(localStorageValues.wai_theme).toBe("dark");
    expect(setItemSpy).toHaveBeenCalledWith("wai_theme", "dark");

    await act(async () => {
      vi.advanceTimersByTime(500);
    });

    expect(mockedUpdatePreferences).toHaveBeenCalledTimes(1);
    expect(mockedUpdatePreferences).toHaveBeenCalledWith({ theme: "dark" });
  });

  it("debounces rapid selections into a single trailing PATCH", async () => {
    render(<ThemeToggle locale="en" />);

    fireEvent.click(screen.getByTestId("theme-toggle-light"));
    fireEvent.click(screen.getByTestId("theme-toggle-dark"));

    await act(async () => {
      vi.advanceTimersByTime(500);
    });

    expect(mockedUpdatePreferences).toHaveBeenCalledTimes(1);
    expect(mockedUpdatePreferences).toHaveBeenCalledWith({ theme: "dark" });
  });

  it("swallows a 401 PATCH and disables further server writes", async () => {
    mockedUpdatePreferences.mockRejectedValue(new ApiError(401, "unauthenticated"));
    render(<ThemeToggle locale="en" />);

    fireEvent.click(screen.getByTestId("theme-toggle-dark"));
    expect(() => vi.advanceTimersByTime(500)).not.toThrow();
    await flushMicrotasks();

    expect(mockedUpdatePreferences).toHaveBeenCalledTimes(1);

    // The 401 latched skipServerWritesRef — a second change must not PATCH again.
    fireEvent.click(screen.getByTestId("theme-toggle-light"));
    await act(async () => {
      vi.advanceTimersByTime(500);
    });

    expect(mockedUpdatePreferences).toHaveBeenCalledTimes(1);
    // But localStorage still records the latest choice for the next visit.
    expect(localStorageValues.wai_theme).toBe("light");
  });

  it("syncs the selected radio from a cross-tab storage event", () => {
    render(<ThemeToggle locale="en" />);
    // Empty storage hydrates to the "system" default.
    expect(screen.getByTestId("theme-toggle-system").getAttribute("aria-checked")).toBe("true");

    act(() => {
      localStorageValues.wai_theme = "dark";
      window.dispatchEvent(
        new StorageEvent("storage", { key: "wai_theme", newValue: "dark" }),
      );
    });

    expect(screen.getByTestId("theme-toggle-dark").getAttribute("aria-checked")).toBe("true");
    expect(screen.getByTestId("theme-toggle-system").getAttribute("aria-checked")).toBe("false");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });
});
