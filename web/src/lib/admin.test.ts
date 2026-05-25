import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  archiveAdminPromoCode,
  cancelAdminSubscription,
  createAdminPromoCode,
  getAdminStats,
  getAdminUser,
  grantAdminSubscription,
  listAdminAudit,
  listAdminBilling,
  listAdminPromoCodes,
  listAdminUsers,
  refundAdminInvoice,
  resumeAdminSubscription,
  updateAdminPromoCode,
  updateAdminUserStatus,
} from "./admin";
import { apiFetch } from "./http";

vi.mock("./http", () => ({
  apiFetch: vi.fn(),
}));

const mockedApiFetch = vi.mocked(apiFetch);

describe("admin api wrappers", () => {
  beforeEach(() => {
    mockedApiFetch.mockReset();
    mockedApiFetch.mockResolvedValue({ items: [] } as never);
  });

  it("calls stats and list endpoints", async () => {
    mockedApiFetch.mockResolvedValueOnce({ users: {}, promo: {}, usage: {}, billing: {} } as never);

    await getAdminStats();
    await listAdminPromoCodes();
    await listAdminUsers();
    await listAdminUsers("  test+admin@example.com  ");
    await listAdminBilling();
    await listAdminAudit();

    expect(mockedApiFetch).toHaveBeenNthCalledWith(1, "/api/admin/stats");
    expect(mockedApiFetch).toHaveBeenNthCalledWith(2, "/api/admin/promo-codes");
    expect(mockedApiFetch).toHaveBeenNthCalledWith(3, "/api/admin/users");
    expect(mockedApiFetch).toHaveBeenNthCalledWith(
      4,
      "/api/admin/users?q=test%2Badmin%40example.com",
    );
    expect(mockedApiFetch).toHaveBeenNthCalledWith(5, "/api/admin/billing");
    expect(mockedApiFetch).toHaveBeenNthCalledWith(6, "/api/admin/audit");
  });

  it("calls promo mutation endpoints", async () => {
    await createAdminPromoCode({
      code: null,
      prefix: "WAI",
      plan: "pro",
      billing_period: "month",
      duration_days: 30,
      max_redemptions: 10,
      expires_days: null,
      note: "launch",
    });
    await updateAdminPromoCode("promo-1", {
      active: false,
      note: "paused",
      duration_days: 14,
      max_redemptions: 5,
    });
    await archiveAdminPromoCode("promo-1");

    expect(mockedApiFetch).toHaveBeenNthCalledWith(1, "/api/admin/promo-codes", {
      method: "POST",
      body: JSON.stringify({
        code: null,
        prefix: "WAI",
        plan: "pro",
        billing_period: "month",
        duration_days: 30,
        max_redemptions: 10,
        expires_days: null,
        note: "launch",
      }),
    });
    expect(mockedApiFetch).toHaveBeenNthCalledWith(2, "/api/admin/promo-codes/promo-1", {
      method: "PATCH",
      body: JSON.stringify({
        active: false,
        note: "paused",
        duration_days: 14,
        max_redemptions: 5,
      }),
    });
    expect(mockedApiFetch).toHaveBeenNthCalledWith(3, "/api/admin/promo-codes/promo-1", {
      method: "DELETE",
    });
  });

  it("calls user admin endpoints", async () => {
    await getAdminUser("user-1");
    await updateAdminUserStatus("user-1", { status: "paused", reason: "billing dispute" });
    await grantAdminSubscription("user-1", { duration_days: 30, reason: "support credit" });

    expect(mockedApiFetch).toHaveBeenNthCalledWith(1, "/api/admin/users/user-1");
    expect(mockedApiFetch).toHaveBeenNthCalledWith(2, "/api/admin/users/user-1/status", {
      method: "PATCH",
      body: JSON.stringify({ status: "paused", reason: "billing dispute" }),
    });
    expect(mockedApiFetch).toHaveBeenNthCalledWith(
      3,
      "/api/admin/users/user-1/subscriptions/grant",
      {
        method: "POST",
        body: JSON.stringify({ duration_days: 30, reason: "support credit" }),
      },
    );
  });

  it("calls billing admin mutation endpoints", async () => {
    await cancelAdminSubscription("sub-1", { mode: "period_end", reason: "requested" });
    await resumeAdminSubscription("sub-1", { reason: "restored" });
    await refundAdminInvoice("invoice-1", { amount_minor: null, reason: "duplicate" });

    expect(mockedApiFetch).toHaveBeenNthCalledWith(1, "/api/admin/subscriptions/sub-1/cancel", {
      method: "POST",
      body: JSON.stringify({ mode: "period_end", reason: "requested" }),
    });
    expect(mockedApiFetch).toHaveBeenNthCalledWith(2, "/api/admin/subscriptions/sub-1/resume", {
      method: "POST",
      body: JSON.stringify({ reason: "restored" }),
    });
    expect(mockedApiFetch).toHaveBeenNthCalledWith(3, "/api/admin/invoices/invoice-1/refund", {
      method: "POST",
      body: JSON.stringify({ amount_minor: null, reason: "duplicate" }),
    });
  });
});
