import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { createBillingCheckout } from "@/lib/billing";
import { PricingCards } from "./PricingCards";

vi.mock("@/lib/billing", () => ({
  createBillingCheckout: vi.fn(),
}));

const mockedCheckout = vi.mocked(createBillingCheckout);

describe("PricingCards", () => {
  beforeEach(() => {
    mockedCheckout.mockReset();
  });

  it("renders English pricing and toggles annual price", async () => {
    render(<PricingCards locale="en" currency="usd" />);

    expect(screen.getByRole("heading", { name: "Simple pricing." })).toBeInTheDocument();
    expect(screen.getByText("3,000 transcribed words per week")).toBeInTheDocument();
    expect(screen.getByText("50,000 transcribed words per week")).toBeInTheDocument();
    expect(screen.queryByText(/trial/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
    expect(screen.queryByText(/World|Russia/i)).not.toBeInTheDocument();
    expect(screen.getByText("$12 / month")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("tab", { name: /Yearly/i }));

    expect(screen.getByText("$96 / year")).toBeInTheDocument();
  });

  it("defaults Russian billing to T-Bank RUB with simple provider labels", async () => {
    mockedCheckout.mockResolvedValue({ provider: "tinkoff", checkout_url: "#checkout" });
    render(<PricingCards locale="ru" currency="rub" signedIn />);

    expect(screen.getByText("999 ₽ / мес")).toBeInTheDocument();
    expect(screen.getByText("RUB через Т-Банк")).toBeInTheDocument();
    expect(screen.getByText("USD через Stripe")).toBeInTheDocument();
    expect(screen.queryByText(/World|Russia|Мир|Россия/i)).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Оформить Pro/i }));

    expect(mockedCheckout).toHaveBeenCalledWith({
      plan: "pro",
      period: "month",
      provider: "tinkoff",
    });
  });

  it("uses selected provider and period for signed-in checkout", async () => {
    mockedCheckout.mockResolvedValue({ provider: "tinkoff", checkout_url: "#checkout" });
    render(<PricingCards locale="ru" currency="rub" signedIn />);

    await userEvent.click(screen.getByRole("tab", { name: /Годовая/i }));
    await userEvent.click(screen.getByRole("radio", { name: /Stripe/i }));
    await userEvent.click(screen.getByRole("button", { name: /Оформить Pro/i }));

    expect(mockedCheckout).toHaveBeenCalledWith({
      plan: "pro",
      period: "year",
      provider: "stripe",
    });
  });
});
