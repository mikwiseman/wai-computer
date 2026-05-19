import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch } from "./http";
import {
  cancelBillingSubscription,
  createBillingCheckout,
  getBillingSubscription,
  getBillingUsage,
  listBillingPlans,
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
    await createBillingCheckout({ plan: "pro", period: "month", provider: "stripe" });
    await cancelBillingSubscription();

    expect(mockedApiFetch).toHaveBeenNthCalledWith(1, "/api/billing/checkout", {
      method: "POST",
      body: JSON.stringify({ plan: "pro", period: "month", provider: "stripe" }),
    });
    expect(mockedApiFetch).toHaveBeenNthCalledWith(2, "/api/billing/cancel", {
      method: "POST",
    });
  });
});
