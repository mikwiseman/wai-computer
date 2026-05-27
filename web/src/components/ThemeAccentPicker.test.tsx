import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { ThemeAccentPicker } from "./ThemeAccentPicker";
import { apiFetch } from "@/lib/http";

vi.mock("@/lib/http", async () => {
  const actual = await vi.importActual<typeof import("@/lib/http")>("@/lib/http");
  return {
    ...actual,
    apiFetch: vi.fn(),
  };
});

const mockedApiFetch = vi.mocked(apiFetch);

const ACCENTS = ["teal", "amber", "blue", "green", "violet", "rose", "graphite"] as const;

let localStorageValues: Record<string, string>;
let setItemSpy: ReturnType<typeof vi.fn>;

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
    mockedApiFetch.mockReset();
    mockedApiFetch.mockResolvedValue(undefined as unknown as never);
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

  it("renders three theme options and cycles between system / light / dark", () => {
    render(<ThemeAccentPicker locale="en" />);

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

  it("clicking accent swatches cycles data-accent on the html element", () => {
    render(<ThemeAccentPicker locale="en" />);
    // Default applied on mount: teal.
    expect(document.documentElement.getAttribute("data-accent")).toBe("teal");

    fireEvent.click(screen.getByTestId("accent-option-amber"));
    expect(document.documentElement.getAttribute("data-accent")).toBe("amber");
    expect(screen.getByTestId("accent-option-amber").getAttribute("aria-checked")).toBe("true");
    expect(screen.getByTestId("accent-option-teal").getAttribute("aria-checked")).toBe("false");

    fireEvent.click(screen.getByTestId("accent-option-violet"));
    expect(document.documentElement.getAttribute("data-accent")).toBe("violet");
    expect(screen.getByTestId("accent-option-violet").getAttribute("aria-checked")).toBe("true");

    fireEvent.click(screen.getByTestId("accent-option-graphite"));
    expect(document.documentElement.getAttribute("data-accent")).toBe("graphite");
  });

  it("writes selections to localStorage", () => {
    render(<ThemeAccentPicker locale="en" />);

    fireEvent.click(screen.getByTestId("theme-option-dark"));
    fireEvent.click(screen.getByTestId("accent-option-violet"));

    expect(localStorageValues.wai_theme).toBe("dark");
    expect(localStorageValues.wai_accent).toBe("violet");
    expect(setItemSpy).toHaveBeenCalledWith("wai_theme", "dark");
    expect(setItemSpy).toHaveBeenCalledWith("wai_accent", "violet");
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
    expect(screen.getByTestId("theme-option-light").textContent).toBe("Светлая");
    expect(screen.getByTestId("theme-option-dark").textContent).toBe("Тёмная");
    expect(screen.getByTestId("accent-option-amber").getAttribute("aria-label")).toBe("Янтарный");
  });

  it("debounces and fires a PATCH to /api/settings/preferences after changes", () => {
    render(<ThemeAccentPicker locale="en" />);

    fireEvent.click(screen.getByTestId("theme-option-light"));
    fireEvent.click(screen.getByTestId("accent-option-blue"));

    // Both clicks should collapse into a single trailing PATCH call.
    vi.advanceTimersByTime(500);

    expect(mockedApiFetch).toHaveBeenCalledTimes(1);
    const [path, init] = mockedApiFetch.mock.calls[0];
    expect(path).toBe("/api/settings/preferences");
    expect(init?.method).toBe("PATCH");
    expect(JSON.parse(String(init?.body))).toEqual({ theme: "light", accent: "blue" });
  });

  it("swallows a 404 PATCH gracefully (no throw, no rejected promise leak)", async () => {
    const ApiErrorClass = (await vi.importActual<typeof import("@/lib/http")>("@/lib/http"))
      .ApiError;
    mockedApiFetch.mockRejectedValue(new ApiErrorClass(404, "not found"));
    render(<ThemeAccentPicker locale="en" />);

    fireEvent.click(screen.getByTestId("theme-option-dark"));

    expect(() => vi.advanceTimersByTime(500)).not.toThrow();
    expect(mockedApiFetch).toHaveBeenCalledTimes(1);
  });
});
