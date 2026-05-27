import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch } from "./http";
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
} from "./billing";

vi.mock("./http", () => ({
  apiFetch: vi.fn(),
}));

const mockedApiFetch = vi.mocked(apiFetch);

describe("billing api wrappers", () => {
  beforeEach(() => {
    mockedApiFetch.mockReset();
    mockedApiFetch.mockResolvedValue({} as never);
  });

  it("calls billing read endpoints", async () => {
    await listBillingPlans();
    await getBillingSubscription();
    await getBillingUsage();

    expect(mockedApiFetch).toHaveBeenNthCalledWith(1, "/api/billing/plans");
    expect(mockedApiFetch).toHaveBeenNthCalledWith(2, "/api/billing/subscription");
    expect(mockedApiFetch).toHaveBeenNthCalledWith(3, "/api/billing/usage");
  });

  it("calls checkout and cancel endpoints", async () => {
    await createBillingCheckout({
      plan: "pro",
      period: "month",
      provider: "stripe",
      promo_code: "WAI-OFF-20",
    });
    await claimBillingPromoCode("WAI-TEST-30");
    await cancelBillingSubscription();

    expect(mockedApiFetch).toHaveBeenNthCalledWith(1, "/api/billing/checkout", {
      method: "POST",
      body: JSON.stringify({
        plan: "pro",
        period: "month",
        provider: "stripe",
        promo_code: "WAI-OFF-20",
      }),
    });
    expect(mockedApiFetch).toHaveBeenNthCalledWith(2, "/api/billing/promo/claim", {
      method: "POST",
      body: JSON.stringify({ code: "WAI-TEST-30" }),
    });
    expect(mockedApiFetch).toHaveBeenNthCalledWith(3, "/api/billing/cancel", {
      method: "POST",
    });
  });

  it("calls invoices and switch-plan endpoints", async () => {
    await getBillingInvoices();
    await switchBillingPlan("yearly");

    expect(mockedApiFetch).toHaveBeenNthCalledWith(1, "/api/billing/invoices");
    expect(mockedApiFetch).toHaveBeenNthCalledWith(2, "/api/billing/switch-plan", {
      method: "POST",
      body: JSON.stringify({ period: "yearly" }),
    });
  });

  it("posts to the Stripe portal endpoint", async () => {
    await openBillingPortal();

    expect(mockedApiFetch).toHaveBeenCalledWith("/api/billing/portal", {
      method: "POST",
    });
  });
});
