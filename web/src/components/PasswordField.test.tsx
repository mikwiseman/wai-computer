import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { PasswordField, scorePassword } from "./PasswordField";

function Harness({
  initial = "",
  showStrength = false,
  locale = "en" as "en" | "ru",
}: { initial?: string; showStrength?: boolean; locale?: "en" | "ru" }) {
  const [value, setValue] = useState(initial);
  return (
    <PasswordField
      id="password-test"
      label="Password"
      value={value}
      onChange={setValue}
      locale={locale}
      showStrength={showStrength}
      data-testid="pf"
    />
  );
}

describe("PasswordField", () => {
  it("renders input with type=password by default", () => {
    render(<Harness />);
    const input = screen.getByTestId("pf");
    expect(input).toHaveAttribute("type", "password");
    const toggle = screen.getByTestId("pf-toggle");
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    expect(toggle).toHaveAttribute("aria-label", "Show password");
  });

  it("toggles type=password to type=text when eye is clicked", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const input = screen.getByTestId("pf");
    const toggle = screen.getByTestId("pf-toggle");

    expect(input).toHaveAttribute("type", "password");
    await user.click(toggle);
    expect(input).toHaveAttribute("type", "text");
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect(toggle).toHaveAttribute("aria-label", "Hide password");
  });

  it("toggles back to type=password on a second click", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const input = screen.getByTestId("pf");
    const toggle = screen.getByTestId("pf-toggle");

    await user.click(toggle);
    expect(input).toHaveAttribute("type", "text");
    await user.click(toggle);
    expect(input).toHaveAttribute("type", "password");
    expect(toggle).toHaveAttribute("aria-pressed", "false");
  });

  it("uses Russian aria-labels when locale=ru", () => {
    render(<Harness locale="ru" />);
    const toggle = screen.getByTestId("pf-toggle");
    expect(toggle).toHaveAttribute("aria-label", "Показать пароль");
  });

  it("does not render a meter when showStrength is false", () => {
    render(<Harness initial="abc" />);
    expect(screen.queryByTestId("pf-meter")).not.toBeInTheDocument();
    expect(screen.queryByRole("meter")).not.toBeInTheDocument();
  });

  it("renders a meter with score=1 (Weak) for very short letter-only input", () => {
    render(<Harness initial="abc" showStrength />);
    const meter = screen.getByTestId("pf-meter");
    expect(meter).toHaveAttribute("data-score", "1");
    expect(meter).toHaveAttribute("aria-valuenow", "1");
    expect(meter).toHaveAttribute("aria-valuetext", "Weak");
  });

  it("renders score=2 (Fair) for 8+ chars with two classes", () => {
    render(<Harness initial="abcdef12" showStrength />);
    const meter = screen.getByTestId("pf-meter");
    expect(meter).toHaveAttribute("data-score", "2");
    expect(meter).toHaveAttribute("aria-valuetext", "Fair");
  });

  it("renders score=3 (Good) for 10+ chars with three classes", () => {
    render(<Harness initial="Abcdef1234" showStrength />);
    const meter = screen.getByTestId("pf-meter");
    expect(meter).toHaveAttribute("data-score", "3");
    expect(meter).toHaveAttribute("aria-valuetext", "Good");
  });

  it("renders score=4 (Strong) for 14+ chars with all four classes", () => {
    render(<Harness initial="Abcdef123456!@" showStrength />);
    const meter = screen.getByTestId("pf-meter");
    expect(meter).toHaveAttribute("data-score", "4");
    expect(meter).toHaveAttribute("aria-valuetext", "Strong");
  });
});

describe("scorePassword", () => {
  it("returns 0 for empty input", () => {
    expect(scorePassword("")).toBe(0);
  });

  it("returns 1 (Weak) when shorter than 8 chars", () => {
    expect(scorePassword("ab")).toBe(1);
    expect(scorePassword("Ab1!")).toBe(1);
  });

  it("returns 1 (Weak) when only one character class is used", () => {
    expect(scorePassword("abcdefghij")).toBe(1);
    expect(scorePassword("ABCDEFGHIJ")).toBe(1);
    expect(scorePassword("1234567890")).toBe(1);
    expect(scorePassword("!@#$%^&*()_")).toBe(1);
  });

  it("returns 2 (Fair) for >= 8 chars with two classes", () => {
    expect(scorePassword("abcdefg1")).toBe(2);
    expect(scorePassword("ABCDEFGH1")).toBe(2);
  });

  it("returns 3 (Good) for >= 10 chars with three classes", () => {
    expect(scorePassword("Abcdef1234")).toBe(3);
    expect(scorePassword("abcd1234!@")).toBe(3);
  });

  it("returns 4 (Strong) for >= 14 chars with all four classes", () => {
    expect(scorePassword("Abcdef123456!@")).toBe(4);
    expect(scorePassword("Aaaaaaaaaaaa1!Z")).toBe(4);
  });

  it("returns 3 (not 4) when length >= 14 but only three classes", () => {
    expect(scorePassword("Abcdefghijkl12")).toBe(3);
  });
});
