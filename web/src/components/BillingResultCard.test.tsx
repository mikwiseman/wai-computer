import type React from "react";
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockReplace = vi.fn();

vi.mock("next/link", () => ({
  default: ({
    children,
    href,
    className,
    "data-testid": testId,
  }: {
    children: React.ReactNode;
    href: string;
    className?: string;
    "data-testid"?: string;
  }) => (
    <a href={href} className={className} data-testid={testId}>
      {children}
    </a>
  ),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockReplace }),
}));

const { BillingResultCard, resolveBillingResultLocale } = await import("./BillingResultCard");

describe("BillingResultCard", () => {
  beforeEach(() => {
    mockReplace.mockReset();
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("keeps bare result pages English without Russian or T-Bank context", () => {
    expect(resolveBillingResultLocale()).toBe("en");
  });

  it("uses Russian T-Bank copy for bare result pages in Russian browser context", () => {
    expect(resolveBillingResultLocale({}, { acceptLanguage: "ru-RU,ru;q=0.9,en;q=0.7" })).toBe(
      "ru",
    );
  });

  it("uses Russian T-Bank copy for bare result pages returning from T-Bank", () => {
    expect(resolveBillingResultLocale({}, { referer: "https://securepay.tinkoff.ru/new/abc" })).toBe(
      "ru",
    );
  });

  it("explains that 4242 is a Stripe test card, not a T-Bank test card", () => {
    render(<BillingResultCard kind="cancel" locale="ru" />);

    expect(screen.getByRole("heading", { name: "Оплата не прошла" })).toBeInTheDocument();
    expect(screen.getByText(/4242 4242 4242 4242/)).toHaveTextContent(
      /Stripe test card, а не тестовая карта Т-Банка/i,
    );
  });

  it("does not link unauthenticated browser returns back to billing", () => {
    render(<BillingResultCard kind="success" locale="ru" />);

    expect(screen.queryByRole("link", { name: /подписк/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /billing/i })).not.toBeInTheDocument();
  });

  it("offers a primary CTA back to the dashboard in English", () => {
    render(<BillingResultCard kind="success" locale="en" />);

    const cta = screen.getByTestId("billing-result-cta");
    expect(cta).toHaveAttribute("href", "/dashboard");
    expect(cta).toHaveTextContent(/Open WaiComputer/i);
  });

  it("offers a primary CTA back to the dashboard in Russian", () => {
    render(<BillingResultCard kind="cancel" locale="ru" />);

    const cta = screen.getByTestId("billing-result-cta");
    expect(cta).toHaveAttribute("href", "/dashboard");
    expect(cta).toHaveTextContent(/Открыть WaiComputer/i);
  });

  it("auto-redirects to the dashboard 5 seconds after a successful checkout", () => {
    render(<BillingResultCard kind="success" locale="en" />);

    expect(mockReplace).not.toHaveBeenCalled();
    vi.advanceTimersByTime(5000);
    expect(mockReplace).toHaveBeenCalledWith("/dashboard");
  });

  it("does not auto-redirect on the cancel page", () => {
    render(<BillingResultCard kind="cancel" locale="en" />);

    vi.advanceTimersByTime(10000);
    expect(mockReplace).not.toHaveBeenCalled();
  });
});
