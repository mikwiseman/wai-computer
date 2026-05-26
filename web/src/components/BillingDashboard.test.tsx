import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  cancelBillingSubscription,
  claimBillingPromoCode,
  createBillingCheckout,
  getBillingSubscription,
  getBillingUsage,
} from "@/lib/billing";
import { BillingDashboard } from "./BillingDashboard";

vi.mock("@/lib/billing", () => ({
  cancelBillingSubscription: vi.fn(),
  claimBillingPromoCode: vi.fn(),
  createBillingCheckout: vi.fn(),
  getBillingSubscription: vi.fn(),
  getBillingUsage: vi.fn(),
}));

const mockedSubscription = vi.mocked(getBillingSubscription);
const mockedUsage = vi.mocked(getBillingUsage);
const mockedCheckout = vi.mocked(createBillingCheckout);
const mockedCancel = vi.mocked(cancelBillingSubscription);
const mockedPromo = vi.mocked(claimBillingPromoCode);

const freeSub = {
  plan: {
    code: "free",
    name: "Free",
    description: null,
    usd_amount_monthly: null,
    usd_amount_yearly: null,
    rub_amount_monthly: null,
    rub_amount_yearly: null,
    word_cap_per_week: 3000,
    memory_retention_days: 30,
    features: {},
  },
  status: "active",
  provider: null,
  billing_period: null,
  current_period_end: null,
  cancel_at_period_end: false,
  trial_end: null,
  enforcement_enabled: false,
};

const proSub = {
  ...freeSub,
  plan: { ...freeSub.plan, code: "pro", name: "Pro", word_cap_per_week: null },
  provider: "stripe",
  billing_period: "month",
  current_period_end: "2026-06-01T00:00:00Z",
};

const usage = {
  words_used: 1200,
  words_cap: 3000,
  reset_at: "2026-05-24T00:00:00Z",
  cap_exceeded: false,
};

describe("BillingDashboard", () => {
  beforeEach(() => {
    mockedSubscription.mockReset();
    mockedUsage.mockReset();
    mockedCheckout.mockReset();
    mockedCancel.mockReset();
    mockedPromo.mockReset();
    mockedSubscription.mockResolvedValue(freeSub);
    mockedUsage.mockResolvedValue(usage);
  });

  it("loads free billing state and opens checkout with selected provider", async () => {
    mockedCheckout.mockResolvedValue({ provider: "stripe", checkout_url: "#checkout" });
    render(<BillingDashboard locale="ru" currency="rub" />);

    expect(screen.getByText("Загрузка…")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Подписка" })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("radio", { name: /Stripe/i }));
    await userEvent.click(screen.getByRole("button", { name: /Оформить Pro/i }));

    expect(mockedCheckout).toHaveBeenCalledWith({
      plan: "pro",
      period: "month",
      provider: "stripe",
    });
  });

  it("does not show multiple payment provider choices outside Russian RUB billing", async () => {
    render(<BillingDashboard locale="en" currency="usd" />);

    expect(await screen.findByRole("heading", { name: "Billing" })).toBeInTheDocument();
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
    expect(screen.queryByText(/World|Russia/i)).not.toBeInTheDocument();
  });

  it("cancels active pro subscriptions", async () => {
    mockedSubscription.mockResolvedValueOnce(proSub).mockResolvedValueOnce({
      ...proSub,
      cancel_at_period_end: true,
    });
    mockedUsage.mockResolvedValue({ ...usage, words_cap: null });
    render(<BillingDashboard locale="en" currency="usd" />);

    await screen.findByRole("button", { name: "Cancel subscription" });
    await userEvent.click(screen.getByRole("button", { name: "Cancel subscription" }));

    await waitFor(() => expect(mockedCancel).toHaveBeenCalled());
    expect(await screen.findByText(/Pro is active through/i)).toBeInTheDocument();
  });

  it("applies promo codes for free users", async () => {
    mockedPromo.mockResolvedValue({ ...proSub, provider: "promo", cancel_at_period_end: true });
    render(<BillingDashboard locale="ru" currency="rub" />);

    expect(await screen.findByRole("heading", { name: "Подписка" })).toBeInTheDocument();

    await userEvent.type(screen.getByPlaceholderText("Введи промокод"), "WAI-TEST-30");
    await userEvent.click(screen.getByRole("button", { name: "Применить" }));

    await waitFor(() => expect(mockedPromo).toHaveBeenCalledWith("WAI-TEST-30"));
    expect(await screen.findByText(/Pro активен до/i)).toBeInTheDocument();
  });

  it("localizes promo code errors in Russian billing", async () => {
    mockedPromo.mockRejectedValue(new Error("Promo code not found"));
    render(<BillingDashboard locale="ru" currency="rub" />);

    expect(await screen.findByRole("heading", { name: "Подписка" })).toBeInTheDocument();

    await userEvent.type(screen.getByPlaceholderText("Введи промокод"), "BAD-CODE");
    await userEvent.click(screen.getByRole("button", { name: "Применить" }));

    expect(await screen.findByText("Промокод не найден.")).toBeInTheDocument();
    expect(screen.queryByText("Promo code not found")).not.toBeInTheDocument();
  });

  it("localizes exhausted promo code errors in Russian billing", async () => {
    mockedPromo.mockRejectedValue(new Error("Promo code exhausted"));
    render(<BillingDashboard locale="ru" currency="rub" />);

    expect(await screen.findByRole("heading", { name: "Подписка" })).toBeInTheDocument();

    await userEvent.type(screen.getByPlaceholderText("Введи промокод"), "USED-CODE");
    await userEvent.click(screen.getByRole("button", { name: "Применить" }));

    expect(await screen.findByText("Промокод уже исчерпан.")).toBeInTheDocument();
    expect(screen.queryByText("Promo code exhausted")).not.toBeInTheDocument();
  });

  it("shows Pro usage as unlimited even if a stale plan payload still includes the old cap", async () => {
    mockedSubscription.mockResolvedValue({
      ...proSub,
      plan: { ...proSub.plan, word_cap_per_week: 50000 },
    });
    mockedUsage.mockResolvedValue({ ...usage, words_cap: null });

    render(<BillingDashboard locale="ru" currency="rub" />);

    expect(await screen.findByText("Без недельного лимита")).toBeInTheDocument();
    expect(screen.queryByText(/50[\s,]000/)).not.toBeInTheDocument();
  });
});
