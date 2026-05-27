import type React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  cancelBillingSubscription,
  claimBillingPromoCode,
  createBillingCheckout,
  getBillingInvoices,
  getBillingSubscription,
  getBillingUsage,
  switchBillingPlan,
} from "@/lib/billing";
import { BillingDashboard } from "./BillingDashboard";

vi.mock("@/lib/billing", () => ({
  cancelBillingSubscription: vi.fn(),
  claimBillingPromoCode: vi.fn(),
  createBillingCheckout: vi.fn(),
  getBillingInvoices: vi.fn(),
  getBillingSubscription: vi.fn(),
  getBillingUsage: vi.fn(),
  switchBillingPlan: vi.fn(),
}));

vi.mock("next/link", () => ({
  default: ({
    children,
    href,
    className,
  }: {
    children: React.ReactNode;
    href: string;
    className?: string;
  }) => (
    <a href={href} className={className}>
      {children}
    </a>
  ),
}));

const mockedSubscription = vi.mocked(getBillingSubscription);
const mockedUsage = vi.mocked(getBillingUsage);
const mockedCheckout = vi.mocked(createBillingCheckout);
const mockedCancel = vi.mocked(cancelBillingSubscription);
const mockedPromo = vi.mocked(claimBillingPromoCode);
const mockedInvoices = vi.mocked(getBillingInvoices);
const mockedSwitch = vi.mocked(switchBillingPlan);

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
  next_charge_at: null,
  next_charge_amount: null,
  next_charge_currency: null,
  enforcement_enabled: false,
};

const proSub = {
  ...freeSub,
  plan: { ...freeSub.plan, code: "pro", name: "Pro", word_cap_per_week: null },
  provider: "stripe",
  billing_period: "month",
  current_period_end: "2026-06-25T00:00:00Z",
  next_charge_at: "2026-06-25T00:00:00Z",
  next_charge_amount: 12,
  next_charge_currency: "USD",
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
    mockedInvoices.mockReset();
    mockedSwitch.mockReset();
    mockedSubscription.mockResolvedValue(freeSub);
    mockedUsage.mockResolvedValue(usage);
    mockedInvoices.mockResolvedValue([]);
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

  it("cancels active pro subscriptions after an inline confirmation", async () => {
    mockedSubscription.mockResolvedValueOnce(proSub).mockResolvedValueOnce({
      ...proSub,
      cancel_at_period_end: true,
      next_charge_at: null,
      next_charge_amount: null,
      next_charge_currency: null,
    });
    mockedUsage.mockResolvedValue({ ...usage, words_cap: null });
    render(<BillingDashboard locale="en" currency="usd" />);

    await screen.findByRole("button", { name: "Cancel subscription" });
    await userEvent.click(screen.getByRole("button", { name: "Cancel subscription" }));

    expect(mockedCancel).not.toHaveBeenCalled();
    expect(
      screen.getByRole("heading", { name: "Cancel your Pro subscription?" }),
    ).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Yes, cancel" }));

    await waitFor(() => expect(mockedCancel).toHaveBeenCalled());
    expect(await screen.findByText(/Pro is active through/i)).toBeInTheDocument();
  });

  it("renders next-charge banner with localized amount and date for an active pro user", async () => {
    mockedSubscription.mockResolvedValue(proSub);
    mockedUsage.mockResolvedValue({ ...usage, words_cap: null });

    render(<BillingDashboard locale="en" currency="usd" />);

    const banner = await screen.findByText(/Next charge \$12/i);
    expect(banner).toBeInTheDocument();
    expect(banner.textContent).toMatch(/June 25, 2026/);
  });

  it("shows the free-plan banner for free users", async () => {
    render(<BillingDashboard locale="en" currency="usd" />);

    expect(
      await screen.findByText("You're on the Free plan — no charges scheduled."),
    ).toBeInTheDocument();
  });

  it("renders invoices in a localized table when present", async () => {
    mockedSubscription.mockResolvedValue(proSub);
    mockedUsage.mockResolvedValue({ ...usage, words_cap: null });
    mockedInvoices.mockResolvedValue([
      {
        id: "inv_1",
        amount: 12,
        currency: "USD",
        status: "paid",
        paid_at: "2026-05-25T00:00:00Z",
        created_at: "2026-05-25T00:00:00Z",
        receipt_url: "https://stripe.test/r/abc",
        description: null,
      },
    ]);

    render(<BillingDashboard locale="en" currency="usd" />);

    await screen.findByRole("table");
    expect(screen.getByText("Paid")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Receipt" })).toHaveAttribute(
      "href",
      "https://stripe.test/r/abc",
    );
  });

  it("shows an empty state for invoices when the API returns no rows", async () => {
    mockedSubscription.mockResolvedValue(proSub);
    mockedUsage.mockResolvedValue({ ...usage, words_cap: null });
    mockedInvoices.mockResolvedValue([]);

    render(<BillingDashboard locale="en" currency="usd" />);

    expect(
      await screen.findByText(
        "No invoices yet — your first charge will appear here.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("requests a plan switch when the user picks Yearly", async () => {
    mockedSubscription.mockResolvedValue(proSub);
    mockedUsage.mockResolvedValue({ ...usage, words_cap: null });
    mockedSwitch.mockResolvedValue({ status: "accepted", requested_period: "year" });

    render(<BillingDashboard locale="en" currency="usd" />);

    await screen.findByLabelText(/Switch plan/i);
    await userEvent.selectOptions(screen.getByLabelText(/Switch plan/i), "yearly");
    await userEvent.click(screen.getByRole("button", { name: "Switch" }));

    await waitFor(() => expect(mockedSwitch).toHaveBeenCalledWith("yearly"));
    expect(
      await screen.findByText(
        /Our team will switch your plan on the next billing cycle/i,
      ),
    ).toBeInTheDocument();
  });

  it("renders the back-to-dashboard link in both locales", async () => {
    render(<BillingDashboard locale="ru" currency="rub" />);

    expect(
      await screen.findByRole("link", { name: /Назад в кабинет/ }),
    ).toBeInTheDocument();
  });

  it("applies promo codes for free users", async () => {
    mockedPromo.mockResolvedValue({ ...proSub, provider: "promo", cancel_at_period_end: true });
    render(<BillingDashboard locale="ru" currency="rub" />);

    expect(await screen.findByRole("heading", { name: "Подписка" })).toBeInTheDocument();

    await userEvent.type(screen.getByPlaceholderText("Введите промокод"), "WAI-TEST-30");
    await userEvent.click(screen.getByRole("button", { name: "Применить" }));

    await waitFor(() => expect(mockedPromo).toHaveBeenCalledWith("WAI-TEST-30"));
    expect(await screen.findByText(/Pro активен до/i)).toBeInTheDocument();
  });

  it("localizes promo code errors in Russian billing", async () => {
    mockedPromo.mockRejectedValue(new Error("Promo code not found"));
    render(<BillingDashboard locale="ru" currency="rub" />);

    expect(await screen.findByRole("heading", { name: "Подписка" })).toBeInTheDocument();

    await userEvent.type(screen.getByPlaceholderText("Введите промокод"), "BAD-CODE");
    await userEvent.click(screen.getByRole("button", { name: "Применить" }));

    expect(await screen.findByText("Промокод не найден.")).toBeInTheDocument();
    expect(screen.queryByText("Promo code not found")).not.toBeInTheDocument();
  });

  it("localizes exhausted promo code errors in Russian billing", async () => {
    mockedPromo.mockRejectedValue(new Error("Promo code exhausted"));
    render(<BillingDashboard locale="ru" currency="rub" />);

    expect(await screen.findByRole("heading", { name: "Подписка" })).toBeInTheDocument();

    await userEvent.type(screen.getByPlaceholderText("Введите промокод"), "USED-CODE");
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
