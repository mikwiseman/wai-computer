import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { AppearanceMenu } from "./AppearanceMenu";

vi.mock("@/components/ThemeAccentPicker", () => ({
  ThemeAccentPicker: ({ locale }: { locale: string }) => (
    <div data-testid="appearance-picker">{locale}</div>
  ),
}));

describe("AppearanceMenu", () => {
  afterEach(cleanup);

  it("opens an accessible appearance dialog and closes with Escape", () => {
    render(<AppearanceMenu locale="en" />);

    const trigger = screen.getByRole("button", { name: "Appearance" });
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("dialog")).toBeNull();

    fireEvent.click(trigger);
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByRole("dialog", { name: "Appearance" })).toBeTruthy();
    expect(screen.getByTestId("appearance-picker").textContent).toBe("en");

    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });

  it("uses Russian labels", () => {
    render(<AppearanceMenu locale="ru" />);
    fireEvent.click(screen.getByRole("button", { name: "Оформление" }));
    expect(screen.getByRole("dialog", { name: "Оформление" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Закрыть оформление" })).toBeTruthy();
  });

  it("closes from the close button and an outside pointer press", () => {
    render(<AppearanceMenu locale="en" />);

    const trigger = screen.getByRole("button", { name: "Appearance" });
    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole("button", { name: "Close appearance" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(trigger);

    fireEvent.click(trigger);
    expect(screen.getByRole("dialog", { name: "Appearance" })).toBeTruthy();
    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
