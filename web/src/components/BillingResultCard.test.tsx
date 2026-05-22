import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  BillingResultCard,
  resolveBillingResultLocale,
} from "./BillingResultCard";

describe("BillingResultCard", () => {
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
});
