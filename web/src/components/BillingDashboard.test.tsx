import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  cancelBillingSubscription,
  createBillingCheckout,
  getBillingSubscription,
  getBillingUsage,
} from "@/lib/billing";
import { BillingDashboard } from "./BillingDashboard";

vi.mock("@/lib/billing", () => ({
  cancelBillingSubscription: vi.fn(),
  createBillingCheckout: vi.fn(),
  getBillingSubscription: vi.fn(),
  getBillingUsage: vi.fn(),
}));

const mockedSubscription = vi.mocked(getBillingSubscription);
const mockedUsage = vi.mocked(getBillingUsage);
const mockedCheckout = vi.mocked(createBillingCheckout);
const mockedCancel = vi.mocked(cancelBillingSubscription);

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
});
