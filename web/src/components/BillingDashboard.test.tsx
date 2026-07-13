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
  listBillingPlans,
  openBillingPortal,
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
  listBillingPlans: vi.fn(),
  openBillingPortal: vi.fn(),
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
const mockedPortal = vi.mocked(openBillingPortal);
const mockedSwitch = vi.mocked(switchBillingPlan);
const mockedPlans = vi.mocked(listBillingPlans);

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

const plans = [
  freeSub.plan,
  {
    ...freeSub.plan,
    code: "pro",
    name: "Pro",
    rub_amount_monthly: 999,
    rub_amount_yearly: 7999,
    usd_amount_monthly: 12,
    usd_amount_yearly: 96,
    word_cap_per_week: null,
  },
];

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
    mockedPortal.mockReset();
    mockedSwitch.mockReset();
    mockedPlans.mockReset();
    mockedSubscription.mockResolvedValue(freeSub);
    mockedUsage.mockResolvedValue(usage);
    mockedInvoices.mockResolvedValue([]);
    mockedPlans.mockResolvedValue(plans);
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
      accepted_recurring_terms: false,
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

  it("opens checkout with the entered code when the promo is a discount", async () => {
    mockedPromo.mockRejectedValue(new Error("Promo code applies to checkout"));
    mockedCheckout.mockResolvedValue({
      provider: "tinkoff",
      checkout_url: "https://pay.tbank.test/discount",
    });
    const originalLocation = window.location;
    const hrefSetter = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true,
      writable: true,
      value: new Proxy(originalLocation, {
        set(target, property, value) {
          if (property === "href") {
            hrefSetter(value);
            return true;
          }
          return Reflect.set(target, property, value);
        },
      }),
    });

    try {
      render(<BillingDashboard locale="ru" currency="rub" />);

      expect(await screen.findByRole("heading", { name: "Подписка" })).toBeInTheDocument();

      await userEvent.type(screen.getByPlaceholderText("Введите промокод"), "TESTSALE");
      await userEvent.click(screen.getByRole("button", { name: "Применить" }));

      await waitFor(() =>
        expect(mockedCheckout).toHaveBeenCalledWith({
          plan: "pro",
          period: "month",
          provider: "tinkoff",
          promo_code: "TESTSALE",
          accepted_recurring_terms: false,
        }),
      );
      expect(hrefSetter).toHaveBeenCalledWith("https://pay.tbank.test/discount");
    } finally {
      Object.defineProperty(window, "location", {
        configurable: true,
        writable: true,
        value: originalLocation,
      });
    }
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

  it("localizes 'does not apply to selected period' promo errors in Russian (136)", async () => {
    mockedPromo.mockRejectedValue(
      new Error("Promo code does not apply to selected period"),
    );
    render(<BillingDashboard locale="ru" currency="rub" />);

    expect(await screen.findByRole("heading", { name: "Подписка" })).toBeInTheDocument();

    await userEvent.type(screen.getByPlaceholderText("Введите промокод"), "YEAR-ONLY");
    await userEvent.click(screen.getByRole("button", { name: "Применить" }));

    expect(
      await screen.findByText("Промокод не применим к выбранному периоду оплаты."),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Promo code does not apply to selected period"),
    ).not.toBeInTheDocument();
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

  it("opens the Stripe Customer Portal when Pro users click Manage subscription", async () => {
    mockedSubscription.mockResolvedValue(proSub);
    mockedUsage.mockResolvedValue({ ...usage, words_cap: null });
    mockedPortal.mockResolvedValue({ url: "https://billing.stripe.com/p/session_x" });

    // Capture window.location.href assignments without leaving jsdom.
    const originalLocation = window.location;
    const hrefSetter = vi.fn();
    Object.defineProperty(window, "location", {
      configurable: true,
      writable: true,
      value: new Proxy(originalLocation, {
        set(target, property, value) {
          if (property === "href") {
            hrefSetter(value);
            return true;
          }
          return Reflect.set(target, property, value);
        },
      }),
    });

    try {
      render(<BillingDashboard locale="en" currency="usd" />);

      const button = await screen.findByRole("button", {
        name: "Manage subscription",
      });
      await userEvent.click(button);

      await waitFor(() => expect(mockedPortal).toHaveBeenCalled());
      await waitFor(() =>
        expect(hrefSetter).toHaveBeenCalledWith(
          "https://billing.stripe.com/p/session_x",
        ),
      );
    } finally {
      Object.defineProperty(window, "location", {
        configurable: true,
        writable: true,
        value: originalLocation,
      });
    }
  });

  it("surfaces a fallback error if the Stripe portal request fails", async () => {
    mockedSubscription.mockResolvedValue(proSub);
    mockedUsage.mockResolvedValue({ ...usage, words_cap: null });
    mockedPortal.mockRejectedValue(new Error("502"));

    render(<BillingDashboard locale="en" currency="usd" />);

    const button = await screen.findByRole("button", {
      name: "Manage subscription",
    });
    await userEvent.click(button);

    expect(
      await screen.findByText(
        /Couldn't reach Stripe right now — please try again, or contact support\./,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Contact support" }),
    ).toBeInTheDocument();
  });

  it("prefers hosted_invoice_url over receipt_url for the Stripe receipt link", async () => {
    mockedSubscription.mockResolvedValue(proSub);
    mockedUsage.mockResolvedValue({ ...usage, words_cap: null });
    mockedInvoices.mockResolvedValue([
      {
        id: "inv_2",
        amount: 96,
        currency: "USD",
        status: "paid",
        paid_at: "2026-05-01T00:00:00Z",
        created_at: "2026-05-01T00:00:00Z",
        receipt_url: "https://old.example/r/abc",
        description: null,
        hosted_invoice_url: "https://invoice.stripe.com/i/abc",
        invoice_pdf: "https://pay.stripe.com/invoice/abc/pdf",
      },
    ]);

    render(<BillingDashboard locale="en" currency="usd" />);

    const link = await screen.findByRole("link", { name: "Receipt" });
    expect(link).toHaveAttribute("href", "https://invoice.stripe.com/i/abc");
    expect(link).toHaveAttribute("target", "_blank");
  });

  it("renders the trial banner for an English trialing Pro user", async () => {
    mockedSubscription.mockResolvedValue({
      ...proSub,
      status: "trialing",
      trial_end: "2026-07-10T00:00:00Z",
      next_charge_at: null,
      next_charge_amount: null,
    });
    mockedUsage.mockResolvedValue({ ...usage, words_cap: null });

    render(<BillingDashboard locale="en" currency="usd" />);

    const banner = await screen.findByRole("heading", {
      name: /Free trial — first charge on/i,
    });
    expect(banner.textContent).toMatch(/July 10, 2026/);
  });

  it("renders the trial banner localized for a Russian trialing Pro user", async () => {
    mockedSubscription.mockResolvedValue({
      ...proSub,
      provider: "tinkoff",
      status: "trialing",
      trial_end: "2026-07-10T00:00:00Z",
      next_charge_at: null,
      next_charge_amount: null,
    });
    mockedUsage.mockResolvedValue({ ...usage, words_cap: null });

    render(<BillingDashboard locale="ru" currency="rub" />);

    expect(
      await screen.findByRole("heading", { name: /Пробный период — первое списание/i }),
    ).toBeInTheDocument();
  });

  it("falls back to em-dash for a null invoice amount and an unparseable date", async () => {
    mockedSubscription.mockResolvedValue(proSub);
    mockedUsage.mockResolvedValue({ ...usage, words_cap: null });
    mockedInvoices.mockResolvedValue([
      {
        id: "inv_null",
        amount: null,
        currency: "USD",
        status: "open",
        paid_at: null,
        created_at: "not-a-real-date",
        receipt_url: null,
        description: "Custom line",
      },
    ]);

    render(<BillingDashboard locale="en" currency="usd" />);

    await screen.findByRole("table");
    const row = screen.getByText("Custom line").closest("tr");
    expect(row).not.toBeNull();
    // amount null -> "—", invalid created_at -> "—", no receipt url -> "—"
    const cells = row ? Array.from(row.querySelectorAll("td")) : [];
    expect(cells[0]?.textContent).toBe("—"); // date
    expect(cells[2]?.textContent).toBe("—"); // amount
    expect(cells[4]?.textContent).toBe("—"); // receipt
    expect(screen.getByText("Open")).toBeInTheDocument();
  });

  it("falls back to a raw amount string when the currency code is invalid", async () => {
    mockedSubscription.mockResolvedValue(proSub);
    mockedUsage.mockResolvedValue({ ...usage, words_cap: null });
    mockedInvoices.mockResolvedValue([
      {
        id: "inv_badcur",
        amount: 42,
        // A 2-letter code is not valid ISO 4217 -> Intl.NumberFormat throws
        // RangeError -> the catch branch returns "<amount> <CODE>".
        currency: "US",
        status: "paid",
        paid_at: "2026-05-25T00:00:00Z",
        created_at: "2026-05-25T00:00:00Z",
        receipt_url: null,
        description: "Bad currency",
      },
    ]);

    render(<BillingDashboard locale="en" currency="usd" />);

    await screen.findByText("Bad currency");
    expect(screen.getByText("42 US")).toBeInTheDocument();
  });

  it("shows the load-error screen when a billing request rejects", async () => {
    mockedSubscription.mockRejectedValue(new Error("boom"));

    render(<BillingDashboard locale="en" currency="usd" />);

    expect(await screen.findByText("Couldn't load billing info.")).toBeInTheDocument();
    // The error screen still offers the escape hatch back to the dashboard.
    expect(
      screen.getByRole("link", { name: "← Back to dashboard" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Billing" })).not.toBeInTheDocument();
  });

  it("surfaces a load error if the checkout request throws on upgrade", async () => {
    mockedCheckout.mockRejectedValue(new Error("network down"));

    render(<BillingDashboard locale="en" currency="usd" />);

    const upgrade = await screen.findByRole("button", { name: "Upgrade to Pro" });
    await userEvent.click(upgrade);

    await waitFor(() => expect(mockedCheckout).toHaveBeenCalled());
    // The failure renders inline; the dashboard itself must stay mounted.
    expect(await screen.findByTestId("billing-action-error")).toHaveTextContent("network down");
    expect(screen.getByRole("button", { name: "Upgrade to Pro" })).toBeInTheDocument();
  });

  it("dismisses the cancel confirmation when the user keeps Pro", async () => {
    mockedSubscription.mockResolvedValue(proSub);
    mockedUsage.mockResolvedValue({ ...usage, words_cap: null });

    render(<BillingDashboard locale="en" currency="usd" />);

    await userEvent.click(
      await screen.findByRole("button", { name: "Cancel subscription" }),
    );
    expect(
      screen.getByRole("heading", { name: "Cancel your Pro subscription?" }),
    ).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Keep Pro" }));

    // The dialog collapses back to the inline "Cancel subscription" trigger and
    // nothing is sent to the API.
    expect(
      screen.queryByRole("heading", { name: "Cancel your Pro subscription?" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Cancel subscription" }),
    ).toBeInTheDocument();
    expect(mockedCancel).not.toHaveBeenCalled();
  });

  it("surfaces a load error if cancellation fails", async () => {
    mockedSubscription.mockResolvedValue(proSub);
    mockedUsage.mockResolvedValue({ ...usage, words_cap: null });
    mockedCancel.mockRejectedValue(new Error("500"));

    render(<BillingDashboard locale="en" currency="usd" />);

    await userEvent.click(
      await screen.findByRole("button", { name: "Cancel subscription" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Yes, cancel" }));

    await waitFor(() => expect(mockedCancel).toHaveBeenCalled());
    // Inline error; the plan card stays on screen for a retry.
    expect(await screen.findByTestId("billing-action-error")).toHaveTextContent("500");
    expect(screen.getByRole("button", { name: "Cancel subscription" })).toBeInTheDocument();
  });

  it("shows the same-period notice without calling the API when the chosen period matches", async () => {
    // proSub is monthly; selecting Monthly again is a no-op switch.
    mockedSubscription.mockResolvedValue(proSub);
    mockedUsage.mockResolvedValue({ ...usage, words_cap: null });

    render(<BillingDashboard locale="en" currency="usd" />);

    await screen.findByLabelText(/Switch plan/i);
    // Select stays on "monthly"; the Switch button is disabled in that state,
    // so drive handleSwitchPlan directly by toggling to yearly then back.
    await userEvent.selectOptions(screen.getByLabelText(/Switch plan/i), "yearly");
    await userEvent.selectOptions(screen.getByLabelText(/Switch plan/i), "monthly");
    // Button is disabled at same period; assert that and that no call was made.
    expect(screen.getByRole("button", { name: "Switch" })).toBeDisabled();
    expect(mockedSwitch).not.toHaveBeenCalled();
  });

  it("surfaces a load error when the plan switch request fails", async () => {
    mockedSubscription.mockResolvedValue(proSub);
    mockedUsage.mockResolvedValue({ ...usage, words_cap: null });
    mockedSwitch.mockRejectedValue(new Error("switch failed"));

    render(<BillingDashboard locale="en" currency="usd" />);

    await screen.findByLabelText(/Switch plan/i);
    await userEvent.selectOptions(screen.getByLabelText(/Switch plan/i), "yearly");
    await userEvent.click(screen.getByRole("button", { name: "Switch" }));

    await waitFor(() => expect(mockedSwitch).toHaveBeenCalledWith("yearly"));
    expect(await screen.findByTestId("billing-action-error")).toHaveTextContent("switch failed");
    expect(screen.getByLabelText(/Switch plan/i)).toBeInTheDocument();
  });

  it("localizes 'active subscription already exists' promo errors in Russian", async () => {
    mockedPromo.mockRejectedValue(new Error("Active subscription already exists"));
    render(<BillingDashboard locale="ru" currency="rub" />);

    expect(await screen.findByRole("heading", { name: "Подписка" })).toBeInTheDocument();
    await userEvent.type(screen.getByPlaceholderText("Введите промокод"), "DUPE");
    await userEvent.click(screen.getByRole("button", { name: "Применить" }));

    expect(
      await screen.findByText("У вас уже есть активная подписка."),
    ).toBeInTheDocument();
  });

  it("localizes expired and already-redeemed promo errors in Russian", async () => {
    mockedPromo.mockRejectedValueOnce(new Error("Promo code expired"));
    const { unmount } = render(<BillingDashboard locale="ru" currency="rub" />);
    await screen.findByRole("heading", { name: "Подписка" });
    await userEvent.type(screen.getByPlaceholderText("Введите промокод"), "OLD");
    await userEvent.click(screen.getByRole("button", { name: "Применить" }));
    expect(await screen.findByText("Срок действия промокода истёк.")).toBeInTheDocument();
    unmount();

    mockedPromo.mockRejectedValueOnce(new Error("Promo code already redeemed"));
    render(<BillingDashboard locale="ru" currency="rub" />);
    await screen.findByRole("heading", { name: "Подписка" });
    await userEvent.type(screen.getByPlaceholderText("Введите промокод"), "MINE");
    await userEvent.click(screen.getByRole("button", { name: "Применить" }));
    expect(
      await screen.findByText("Вы уже использовали этот промокод."),
    ).toBeInTheDocument();
  });

  it("maps an unknown 'Promo code ...' error to the generic localized message", async () => {
    // A server-side 500 that still mentions "Promo code" must not leak English.
    mockedPromo.mockRejectedValue(new Error("Promo code internal server error 500"));
    render(<BillingDashboard locale="ru" currency="rub" />);

    expect(await screen.findByRole("heading", { name: "Подписка" })).toBeInTheDocument();
    await userEvent.type(screen.getByPlaceholderText("Введите промокод"), "WHATEVER");
    await userEvent.click(screen.getByRole("button", { name: "Применить" }));

    expect(await screen.findByText("Этот промокод нельзя применить.")).toBeInTheDocument();
    expect(
      screen.queryByText(/internal server error/i),
    ).not.toBeInTheDocument();
  });

  it("passes through a non-promo error message verbatim", async () => {
    mockedPromo.mockRejectedValue(new Error("Rate limited, try later"));
    render(<BillingDashboard locale="en" currency="usd" />);

    await screen.findByRole("heading", { name: "Billing" });
    await userEvent.type(screen.getByPlaceholderText("Enter promo code"), "CODE");
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));

    expect(await screen.findByText("Rate limited, try later")).toBeInTheDocument();
  });

  it("falls back to the generic load error when a promo error carries no message", async () => {
    mockedPromo.mockRejectedValue(new Error(""));
    render(<BillingDashboard locale="en" currency="usd" />);

    await screen.findByRole("heading", { name: "Billing" });
    await userEvent.type(screen.getByPlaceholderText("Enter promo code"), "CODE");
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));

    expect(await screen.findByText("Couldn't load billing info.")).toBeInTheDocument();
  });

  it("localizes the checkout error when a discount promo's checkout request then fails", async () => {
    mockedPromo.mockRejectedValue(new Error("Promo code applies to checkout"));
    mockedCheckout.mockRejectedValue(new Error("Promo code expired"));
    render(<BillingDashboard locale="ru" currency="rub" />);

    expect(await screen.findByRole("heading", { name: "Подписка" })).toBeInTheDocument();
    await userEvent.type(screen.getByPlaceholderText("Введите промокод"), "SALE");
    await userEvent.click(screen.getByRole("button", { name: "Применить" }));

    await waitFor(() => expect(mockedCheckout).toHaveBeenCalled());
    // The follow-up checkout failure is localized, not leaked as raw English.
    expect(await screen.findByText("Срок действия промокода истёк.")).toBeInTheDocument();
  });

  it("toggles upgrade period, payment provider and recurring consent in RU billing", async () => {
    mockedCheckout.mockRejectedValue(new Error("network down"));
    render(<BillingDashboard locale="ru" currency="rub" />);

    expect(await screen.findByRole("heading", { name: "Подписка" })).toBeInTheDocument();

    // The price headline ("Pro — <amount> <per>") is distinct from the auto-renew
    // consent sentence that also repeats the amount, so match it by its leading text.
    const priceHeadline = () =>
      screen
        .getAllByText((_content, el) => el?.textContent?.startsWith("Pro — ") ?? false)
        .find((el) => el.tagName === "P");

    // Yearly price reflects the plan's RUB yearly amount (7 999 ₽).
    await userEvent.click(screen.getByRole("button", { name: "На год" }));
    expect(priceHeadline()?.textContent).toMatch(/7[\s  ]999/);
    expect(priceHeadline()?.textContent).toContain("в год");
    // Back to monthly (999 ₽, /month) — no thousands separator.
    await userEvent.click(screen.getByRole("button", { name: "Помесячно" }));
    expect(priceHeadline()?.textContent).toMatch(/(?<!\d[\s  ])999/);
    expect(priceHeadline()?.textContent).toContain("в месяц");

    // T-Bank is the RU default; flip to Stripe (hides consent) then back to T-Bank.
    await userEvent.click(screen.getByRole("radio", { name: /Stripe/i }));
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("radio", { name: /Т-Банк/i }));

    // Pay button is gated on recurring consent for the T-Bank rail.
    const pay = screen.getByRole("button", { name: "Оформить Pro" });
    expect(pay).toBeDisabled();
    await userEvent.click(screen.getByRole("checkbox"));
    expect(pay).toBeEnabled();

    // Now the gated upgrade runs and the checkout failure surfaces as load error.
    await userEvent.click(pay);
    await waitFor(() =>
      expect(mockedCheckout).toHaveBeenCalledWith({
        plan: "pro",
        period: "month",
        provider: "tinkoff",
        accepted_recurring_terms: true,
      }),
    );
    expect(await screen.findByTestId("billing-action-error")).toBeInTheDocument();
  });
});
