import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";

import { ThemeAccentPicker } from "./ThemeAccentPicker";
import { ApiError } from "@/lib/http";
import { getPreferences, updatePreferences } from "@/lib/api";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    getPreferences: vi.fn(),
    updatePreferences: vi.fn(),
  };
});

const mockedGetPreferences = vi.mocked(getPreferences);
const mockedUpdatePreferences = vi.mocked(updatePreferences);

const ACCENTS = ["teal", "amber", "blue", "green", "violet", "rose", "graphite"] as const;

let localStorageValues: Record<string, string>;
let setItemSpy: ReturnType<typeof vi.fn>;

async function flushHydration(): Promise<void> {
  // Drain the microtask queue used by the server-fetch promise chain
  // so the hydration `finally` block clears `hydratingRef`.
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe("ThemeAccentPicker", () => {
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

    document.documentElement.removeAttribute("data-theme");
    document.documentElement.removeAttribute("data-accent");
    mockedGetPreferences.mockReset();
    mockedUpdatePreferences.mockReset();
    // Default: unauthenticated -> 401. Component falls back to localStorage.
    mockedGetPreferences.mockRejectedValue(new ApiError(401, "unauthenticated"));
    mockedUpdatePreferences.mockResolvedValue({ theme: "system", accent: "teal" });
  });

  afterEach(() => {
    vi.useRealTimers();
    cleanup();
  });

  it("renders all 7 accent swatches", () => {
    render(<ThemeAccentPicker locale="en" />);
    for (const accent of ACCENTS) {
      expect(screen.getByTestId(`accent-option-${accent}`)).toBeTruthy();
    }
    expect(
      screen.getAllByRole("radio", { name: /Teal|Amber|Blue|Green|Violet|Rose|Graphite/ }),
    ).toHaveLength(ACCENTS.length);
  });

  it("renders three theme options and cycles between system / light / dark", async () => {
    render(<ThemeAccentPicker locale="en" />);
    await flushHydration();

    const systemBtn = screen.getByTestId("theme-option-system");
    const lightBtn = screen.getByTestId("theme-option-light");
    const darkBtn = screen.getByTestId("theme-option-dark");

    // Default after hydration: system selected.
    expect(systemBtn.getAttribute("aria-checked")).toBe("true");
    expect(lightBtn.getAttribute("aria-checked")).toBe("false");
    expect(darkBtn.getAttribute("aria-checked")).toBe("false");

    fireEvent.click(lightBtn);
    expect(lightBtn.getAttribute("aria-checked")).toBe("true");
    expect(systemBtn.getAttribute("aria-checked")).toBe("false");
    expect(document.documentElement.getAttribute("data-theme")).toBe("light");

    fireEvent.click(darkBtn);
    expect(darkBtn.getAttribute("aria-checked")).toBe("true");
    expect(lightBtn.getAttribute("aria-checked")).toBe("false");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");

    fireEvent.click(systemBtn);
    expect(systemBtn.getAttribute("aria-checked")).toBe("true");
    expect(document.documentElement.getAttribute("data-theme")).toBe("system");
  });

  it("clicking accent swatches cycles data-accent on the html element", async () => {
    render(<ThemeAccentPicker locale="en" />);
    await flushHydration();
    // Default applied on mount: amber (matches the Mac app's default accent).
    expect(document.documentElement.getAttribute("data-accent")).toBe("amber");

    fireEvent.click(screen.getByTestId("accent-option-teal"));
    expect(document.documentElement.getAttribute("data-accent")).toBe("teal");
    expect(screen.getByTestId("accent-option-teal").getAttribute("aria-checked")).toBe("true");
    expect(screen.getByTestId("accent-option-amber").getAttribute("aria-checked")).toBe("false");

    fireEvent.click(screen.getByTestId("accent-option-violet"));
    expect(document.documentElement.getAttribute("data-accent")).toBe("violet");
    expect(screen.getByTestId("accent-option-violet").getAttribute("aria-checked")).toBe("true");

    fireEvent.click(screen.getByTestId("accent-option-graphite"));
    expect(document.documentElement.getAttribute("data-accent")).toBe("graphite");
  });

  it("writes selections to localStorage", async () => {
    render(<ThemeAccentPicker locale="en" />);
    await flushHydration();

    fireEvent.click(screen.getByTestId("theme-option-dark"));
    fireEvent.click(screen.getByTestId("accent-option-violet"));

    expect(localStorageValues.wai_theme).toBe("dark");
    expect(localStorageValues.wai_accent).toBe("violet");
    expect(setItemSpy).toHaveBeenCalledWith("wai_theme", "dark");
    expect(setItemSpy).toHaveBeenCalledWith("wai_accent", "violet");
  });

  it("keeps the selected theme and accent when localStorage rejects writes", async () => {
    render(<ThemeAccentPicker locale="en" />);
    await flushHydration();
    setItemSpy.mockImplementation(() => {
      throw new DOMException("Storage is unavailable", "QuotaExceededError");
    });

    fireEvent.click(screen.getByTestId("theme-option-dark"));
    fireEvent.click(screen.getByTestId("accent-option-violet"));

    expect(screen.getByTestId("theme-option-dark").getAttribute("aria-checked")).toBe("true");
    expect(screen.getByTestId("accent-option-violet").getAttribute("aria-checked")).toBe("true");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(document.documentElement.getAttribute("data-accent")).toBe("violet");

    // Restore persistent storage so the module-level snapshots do not leak
    // into later tests in this file.
    setItemSpy.mockImplementation((key: string, value: string) => {
      localStorageValues[key] = value;
    });
    fireEvent.click(screen.getByTestId("theme-option-system"));
    fireEvent.click(screen.getByTestId("accent-option-amber"));
  });

  it("keeps multiple mounted appearance controls synchronized", async () => {
    render(
      <>
        <div data-testid="picker-a"><ThemeAccentPicker locale="en" /></div>
        <div data-testid="picker-b"><ThemeAccentPicker locale="en" /></div>
      </>,
    );
    await flushHydration();

    const pickerA = within(screen.getByTestId("picker-a"));
    const pickerB = within(screen.getByTestId("picker-b"));
    fireEvent.click(pickerA.getByTestId("theme-option-dark"));
    fireEvent.click(pickerA.getByTestId("accent-option-violet"));

    expect(pickerB.getByTestId("theme-option-dark").getAttribute("aria-checked")).toBe("true");
    expect(pickerB.getByTestId("accent-option-violet").getAttribute("aria-checked")).toBe("true");
  });

  it("applies an accent received from another browser tab", async () => {
    render(<ThemeAccentPicker locale="en" />);
    await flushHydration();

    localStorageValues.wai_accent = "rose";
    act(() => {
      window.dispatchEvent(new StorageEvent("storage", {
        key: "wai_accent",
        newValue: "rose",
      }));
    });

    expect(screen.getByTestId("accent-option-rose").getAttribute("aria-checked")).toBe("true");
    expect(document.documentElement.getAttribute("data-accent")).toBe("rose");
  });

  it("hydrates from localStorage on mount", () => {
    localStorageValues.wai_theme = "dark";
    localStorageValues.wai_accent = "rose";

    render(<ThemeAccentPicker locale="en" />);

    expect(screen.getByTestId("theme-option-dark").getAttribute("aria-checked")).toBe("true");
    expect(screen.getByTestId("accent-option-rose").getAttribute("aria-checked")).toBe("true");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(document.documentElement.getAttribute("data-accent")).toBe("rose");
  });

  it("renders Russian copy when locale is ru", () => {
    render(<ThemeAccentPicker locale="ru" />);
    expect(screen.getByTestId("theme-option-system").textContent).toBe("Системная");
    expect(screen.getByTestId("theme-option-light").textContent).toBe("Жемчужная");
    expect(screen.getByTestId("theme-option-dark").textContent).toBe("Полночь");
    expect(screen.getByTestId("accent-option-amber").getAttribute("aria-label")).toBe("Янтарный");
  });

  it("debounces and fires a PATCH to updatePreferences after user changes", async () => {
    mockedGetPreferences.mockResolvedValueOnce({ theme: "system", accent: "teal" });
    render(<ThemeAccentPicker locale="en" />);
    await flushHydration();

    fireEvent.click(screen.getByTestId("theme-option-light"));
    fireEvent.click(screen.getByTestId("accent-option-blue"));

    // Both clicks should collapse into a single trailing PATCH call.
    vi.advanceTimersByTime(500);

    expect(mockedUpdatePreferences).toHaveBeenCalledTimes(1);
    expect(mockedUpdatePreferences).toHaveBeenCalledWith({ theme: "light", accent: "blue" });
  });

  it("swallows a 404 PATCH gracefully (no throw, no rejected promise leak)", async () => {
    mockedGetPreferences.mockResolvedValueOnce({ theme: "system", accent: "teal" });
    mockedUpdatePreferences.mockRejectedValue(new ApiError(404, "not found"));
    render(<ThemeAccentPicker locale="en" />);
    await flushHydration();

    fireEvent.click(screen.getByTestId("theme-option-dark"));

    expect(() => vi.advanceTimersByTime(500)).not.toThrow();
    expect(mockedUpdatePreferences).toHaveBeenCalledTimes(1);
  });

  it("does NOT call updatePreferences when unauthenticated (401 on initial fetch)", async () => {
    // Default beforeEach already rejects getPreferences with 401.
    render(<ThemeAccentPicker locale="en" />);
    await flushHydration();

    fireEvent.click(screen.getByTestId("theme-option-dark"));
    vi.advanceTimersByTime(500);

    // Unauthenticated users stay localStorage-only — no PATCH calls.
    expect(mockedUpdatePreferences).not.toHaveBeenCalled();
    // But localStorage still records the change for next visit.
    expect(localStorageValues.wai_theme).toBe("dark");
  });

  it("overwrites localStorage when the server returns different preferences", async () => {
    localStorageValues.wai_theme = "system";
    localStorageValues.wai_accent = "teal";
    mockedGetPreferences.mockResolvedValueOnce({ theme: "dark", accent: "violet" });

    render(<ThemeAccentPicker locale="en" />);
    await flushHydration();

    // After server reply, the UI reflects the server values.
    expect(screen.getByTestId("theme-option-dark").getAttribute("aria-checked")).toBe("true");
    expect(screen.getByTestId("accent-option-violet").getAttribute("aria-checked")).toBe("true");
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
    expect(document.documentElement.getAttribute("data-accent")).toBe("violet");
    // localStorage was overwritten so cross-device drift is resolved.
    expect(localStorageValues.wai_theme).toBe("dark");
    expect(localStorageValues.wai_accent).toBe("violet");
    // And the hydration itself must not fire a PATCH back to the server.
    expect(mockedUpdatePreferences).not.toHaveBeenCalled();
  });
});
