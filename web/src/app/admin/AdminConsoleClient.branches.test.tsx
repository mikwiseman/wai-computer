import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  archiveAdminPromoCode,
  cancelAdminSubscription,
  createAdminPromoCode,
  getAdminObservability,
  getAdminUser,
  getAdminStats,
  grantAdminSubscription,
  listAdminAudit,
  listAdminBilling,
  listAdminPromoCodes,
  listAdminUsers,
  refundAdminInvoice,
  resumeAdminSubscription,
  runAdminSubscriptionRenewal,
  updateAdminPromoCode,
  updateAdminSubscription,
  updateAdminUserStatus,
  type AdminBillingSubscription,
  type AdminPromoCode,
  type AdminUserDetail,
  type AdminUserSummary,
} from "@/lib/admin";
import { logout } from "@/lib/api";
import { AdminConsoleClient } from "./AdminConsoleClient";

const mockReplace = vi.fn();

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams("tab=overview"),
  useRouter: () => ({ replace: mockReplace, push: vi.fn() }),
}));

vi.mock("@/lib/api", () => ({
  logout: vi.fn(),
}));

vi.mock("@/lib/admin", () => ({
  archiveAdminPromoCode: vi.fn(),
  cancelAdminSubscription: vi.fn(),
  createAdminPromoCode: vi.fn(),
  getAdminObservability: vi.fn(),
  getAdminStats: vi.fn(),
  getAdminUser: vi.fn(),
  grantAdminSubscription: vi.fn(),
  listAdminAudit: vi.fn(),
  listAdminBilling: vi.fn(),
  listAdminPromoCodes: vi.fn(),
  listAdminUsers: vi.fn(),
  refundAdminInvoice: vi.fn(),
  resumeAdminSubscription: vi.fn(),
  runAdminSubscriptionRenewal: vi.fn(),
  updateAdminPromoCode: vi.fn(),
  updateAdminSubscription: vi.fn(),
  updateAdminUserStatus: vi.fn(),
}));

const mockedStats = vi.mocked(getAdminStats);
const mockedObservability = vi.mocked(getAdminObservability);
const mockedPromos = vi.mocked(listAdminPromoCodes);
const mockedUsers = vi.mocked(listAdminUsers);
const mockedBilling = vi.mocked(listAdminBilling);
const mockedAudit = vi.mocked(listAdminAudit);
const mockedCreatePromo = vi.mocked(createAdminPromoCode);
const mockedUpdatePromo = vi.mocked(updateAdminPromoCode);
const mockedArchivePromo = vi.mocked(archiveAdminPromoCode);
const mockedGetUser = vi.mocked(getAdminUser);
const mockedUpdateUserStatus = vi.mocked(updateAdminUserStatus);
const mockedGrantSubscription = vi.mocked(grantAdminSubscription);
const mockedCancelSubscription = vi.mocked(cancelAdminSubscription);
const mockedResumeSubscription = vi.mocked(resumeAdminSubscription);
const mockedRefundInvoice = vi.mocked(refundAdminInvoice);
const mockedUpdateSubscription = vi.mocked(updateAdminSubscription);
const mockedRunRenewal = vi.mocked(runAdminSubscriptionRenewal);
const mockedLogout = vi.mocked(logout);

const STATS = {
  users: { total: 3, new_30d: 2, by_status: { active: 2, paused: 1 } },
  promo: {
    total: 2,
    active: 2,
    paused: 0,
    archived: 0,
    expired: 0,
    exhausted: 0,
    redemptions: 0,
    monthly_redemptions: [{ period: "2026-05", redemptions: 2 }],
  },
  usage: {
    recording_words: 120,
    dictation_words: 30,
    total_words: 150,
    recording_duration_seconds: 600,
    dictation_duration_seconds: 12,
    recording_count: 4,
    failed_recordings: 1,
    monthly: [
      {
        period: "2026-05",
        recording_words: 120,
        dictation_words: 30,
        total_words: 150,
        recording_duration_seconds: 600,
        dictation_duration_seconds: 12,
        recording_count: 4,
        failed_recordings: 1,
      },
    ],
    yearly: [
      {
        period: "2026",
        recording_words: 120,
        dictation_words: 30,
        total_words: 150,
        recording_duration_seconds: 600,
        dictation_duration_seconds: 12,
        recording_count: 4,
        failed_recordings: 1,
      },
    ],
  },
  billing: {
    subscriptions_by_provider: { stripe: 1, tinkoff: 1 },
    subscriptions_by_status: { active: 2 },
    revenue_by_currency: { USD: 12 },
    monthly_revenue: [{ period: "2026-05", currency: "USD", amount: 12 }],
  },
};

const OBSERVABILITY = {
  generated_at: "2026-05-25T12:00:00Z",
  server: {
    database: "connected",
    release: "waicomputer@test",
    environment: "production",
    log_format: "json",
  },
  sentry: {
    configured: true,
    release: "waicomputer@test",
    environment: "production",
    traces_sample_rate: 0.1,
    profiles_sample_rate: 0.1,
  },
  recording_pipeline: {
    status_counts: { ready: 2, failed: 1, processing: 1 },
    last_24h: { total: 4, ready: 2, failed: 1, processing: 1 },
    failed_rate_24h: 0.25,
    stuck_processing_count: 1,
    low_transcript_coverage_count_24h: 1,
    median_transcript_coverage_24h: 0.68,
  },
  alerts: [],
};

const ACCESS_PROMO: AdminPromoCode = {
  id: "promo-access",
  code: "WAI-LAUNCH-30",
  normalized_code: "WAILAUNCH30",
  plan: "pro",
  promotion_type: "access",
  billing_period: "month",
  duration_days: 30,
  discount_percent: null,
  max_redemptions: 10,
  redeemed_count: 2,
  redemption_rate: 0.2,
  active: true,
  archived_at: null,
  expires_at: "2026-06-25T00:00:00Z",
  note: "launch",
  created_at: "2026-05-25T00:00:00Z",
  redemptions: [],
};

// A discount promo exercises the discount-only input cells in the promo table
// (duration_days hidden, discount_percent editable).
const DISCOUNT_PROMO: AdminPromoCode = {
  id: "promo-discount",
  code: "WAI-OFF-25",
  normalized_code: "WAIOFF25",
  plan: "pro",
  promotion_type: "discount",
  billing_period: "year",
  duration_days: null,
  discount_percent: 25,
  max_redemptions: 5,
  redeemed_count: 1,
  redemption_rate: 0.2,
  active: true,
  archived_at: null,
  expires_at: "2026-07-01T00:00:00Z",
  note: "summer",
  created_at: "2026-05-20T00:00:00Z",
  redemptions: [],
};

const USER_SUMMARY: AdminUserSummary = {
  id: "user-1",
  email: "user@example.com",
  account_status: "active",
  account_status_reason: null,
  created_at: "2026-05-25T00:00:00Z",
  current_plan: "pro",
  current_subscription_status: "active",
  current_subscription_provider: "stripe",
  dictation_words: 30,
  recording_words: 120,
  recording_count: 4,
  dictation_duration_seconds: 12,
  recording_duration_seconds: 600,
  transcription_duration_seconds: 612,
  companion_input_tokens: 100,
  companion_output_tokens: 40,
  companion_cached_tokens: 25,
  companion_total_tokens: 140,
  revenue_by_currency: { USD: 12 },
};

const USER_DETAIL: AdminUserDetail = {
  ...USER_SUMMARY,
  subscriptions: [],
  promo_redemptions: [],
  weekly_usage: [],
};

// A Tinkoff subscription is the only provider whose edit form lets the admin
// change plan/period/dates/cancel-flag, so the full subPatchDiff is reachable.
const TINKOFF_SUB: AdminBillingSubscription = {
  id: "sub-tinkoff",
  user_id: "user-2",
  user_email: "ru-user@example.com",
  plan: "pro",
  status: "active",
  provider: "tinkoff",
  billing_period: "month",
  current_period_start: "2026-05-25T00:00:00Z",
  current_period_end: "2026-06-25T00:00:00Z",
  cancel_at_period_end: false,
  canceled_at: null,
  trial_end: null,
  tinkoff_next_charge_at: "2026-06-25T00:00:00Z",
  invoices: [],
};

function setupMocks() {
  mockedStats.mockResolvedValue(structuredClone(STATS));
  mockedObservability.mockResolvedValue(structuredClone(OBSERVABILITY));
  mockedPromos.mockResolvedValue([structuredClone(ACCESS_PROMO), structuredClone(DISCOUNT_PROMO)]);
  mockedUsers.mockResolvedValue([structuredClone(USER_SUMMARY)]);
  mockedGetUser.mockResolvedValue(structuredClone(USER_DETAIL));
  mockedBilling.mockResolvedValue([structuredClone(TINKOFF_SUB)]);
  mockedAudit.mockResolvedValue([]);
  mockedArchivePromo.mockResolvedValue();
  mockedUpdatePromo.mockResolvedValue(structuredClone(DISCOUNT_PROMO));
  mockedGrantSubscription.mockResolvedValue({});
  mockedCancelSubscription.mockResolvedValue({});
  mockedResumeSubscription.mockResolvedValue({});
  mockedRefundInvoice.mockResolvedValue({});
  mockedUpdateSubscription.mockResolvedValue({} as never);
  mockedUpdateUserStatus.mockResolvedValue(structuredClone(USER_DETAIL));
  mockedRunRenewal.mockResolvedValue({ charged: true });
}

async function gotoBilling() {
  render(<AdminConsoleClient />);
  await screen.findByText("Total users");
  await userEvent.click(screen.getByRole("button", { name: "Billing" }));
  return (await screen.findByText("tinkoff · pro · active · renewing")).closest(
    "section",
  ) as HTMLElement;
}

describe("AdminConsoleClient — error and branch coverage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupMocks();
  });

  it("surfaces the initial-load error when a data fetch rejects", async () => {
    mockedStats.mockRejectedValueOnce(new Error("stats endpoint down"));
    render(<AdminConsoleClient />);

    expect(await screen.findByText("stats endpoint down")).toBeInTheDocument();
    // The error banner replaces the metrics — no stats grid is rendered.
    expect(screen.queryByText("Total users")).not.toBeInTheDocument();
  });

  it("falls back to a generic message when the rejection is not an Error", async () => {
    mockedStats.mockRejectedValueOnce("boom");
    render(<AdminConsoleClient />);

    expect(await screen.findByText("Admin data failed to load.")).toBeInTheDocument();
  });

  it("reports a runAction failure via the Refresh button", async () => {
    render(<AdminConsoleClient />);
    await screen.findByText("Total users");

    // The second refresh (triggered by the button) rejects.
    mockedStats.mockRejectedValueOnce(new Error("refresh blew up"));
    await userEvent.click(screen.getByRole("button", { name: "Refresh" }));

    expect(await screen.findByText("refresh blew up")).toBeInTheDocument();
  });

  it("shows a generic runAction error for a non-Error throw", async () => {
    render(<AdminConsoleClient />);
    await screen.findByText("Total users");

    mockedStats.mockRejectedValueOnce("nope");
    await userEvent.click(screen.getByRole("button", { name: "Refresh" }));

    expect(await screen.findByText("Admin action failed.")).toBeInTheDocument();
  });

  it("surfaces a logout failure without redirecting", async () => {
    mockedLogout.mockRejectedValueOnce(new Error("logout failed"));
    render(<AdminConsoleClient />);
    await screen.findByText("Total users");

    await userEvent.click(screen.getByTestId("admin-logout-button"));

    expect(await screen.findByText("logout failed")).toBeInTheDocument();
    expect(mockReplace).not.toHaveBeenCalled();
  });

  it("searches users from the search form and clears the selection", async () => {
    render(<AdminConsoleClient />);
    await screen.findByText("Total users");
    await userEvent.click(screen.getByRole("button", { name: "Users" }));

    // Select a user so the detail panel is open, then re-run the search.
    await userEvent.click(await screen.findByText("user@example.com"));
    await waitFor(() => expect(mockedGetUser).toHaveBeenCalledWith("user-1"));
    expect(screen.getByRole("heading", { level: 3, name: "user@example.com" })).toBeInTheDocument();

    mockedUsers.mockClear();
    await userEvent.type(screen.getByPlaceholderText("email or id"), "user@example.com");
    await userEvent.click(screen.getByRole("button", { name: "Search" }));

    await waitFor(() => expect(mockedUsers).toHaveBeenCalledWith("user@example.com"));
    // Selection is cleared on a fresh search → the detail heading disappears.
    await waitFor(() =>
      expect(
        screen.queryByRole("heading", { level: 3, name: "user@example.com" }),
      ).not.toBeInTheDocument(),
    );
  });

  it("reports when opening a user detail fails", async () => {
    render(<AdminConsoleClient />);
    await screen.findByText("Total users");
    await userEvent.click(screen.getByRole("button", { name: "Users" }));

    mockedGetUser.mockRejectedValueOnce(new Error("user lookup failed"));
    await userEvent.click(await screen.findByText("user@example.com"));

    expect(await screen.findByText("user lookup failed")).toBeInTheDocument();
  });

  it("reports a skipped Tinkoff renewal with the gate reason", async () => {
    const tinkoffItem = await gotoBilling();

    mockedRunRenewal.mockResolvedValueOnce({
      charged: false,
      skipped: true,
      reason: "cancellation pending",
    });
    await userEvent.click(within(tinkoffItem).getByRole("button", { name: "Run renewal now" }));

    expect(await screen.findByText("Renewal skipped: cancellation pending.")).toBeInTheDocument();
  });

  it("defaults the skipped renewal reason when the API omits one", async () => {
    const tinkoffItem = await gotoBilling();

    mockedRunRenewal.mockResolvedValueOnce({ charged: false, skipped: true });
    await userEvent.click(within(tinkoffItem).getByRole("button", { name: "Run renewal now" }));

    expect(await screen.findByText("Renewal skipped: not eligible.")).toBeInTheDocument();
  });

  it("reports a provider-rejected renewal as an error with the status", async () => {
    const tinkoffItem = await gotoBilling();

    mockedRunRenewal.mockResolvedValueOnce({ charged: false, status: "past_due" });
    await userEvent.click(within(tinkoffItem).getByRole("button", { name: "Run renewal now" }));

    expect(
      await screen.findByText("Renewal attempt failed at the provider (status: past_due)."),
    ).toBeInTheDocument();
  });

  it("reports the renewal status as unknown when the provider omits it", async () => {
    const tinkoffItem = await gotoBilling();

    mockedRunRenewal.mockResolvedValueOnce({ charged: false });
    await userEvent.click(within(tinkoffItem).getByRole("button", { name: "Run renewal now" }));

    expect(
      await screen.findByText("Renewal attempt failed at the provider (status: unknown)."),
    ).toBeInTheDocument();
  });

  it("surfaces a thrown renewal error", async () => {
    const tinkoffItem = await gotoBilling();

    mockedRunRenewal.mockRejectedValueOnce(new Error("renewal exploded"));
    await userEvent.click(within(tinkoffItem).getByRole("button", { name: "Run renewal now" }));

    expect(await screen.findByText("renewal exploded")).toBeInTheDocument();
  });

  it("disables the auto prefix once a manual code is typed", async () => {
    render(<AdminConsoleClient />);
    await screen.findByText("Total users");
    await userEvent.click(screen.getByRole("button", { name: "Promo codes" }));

    const prefixInput = screen.getByLabelText("Auto prefix");
    expect(prefixInput).not.toBeDisabled();

    await userEvent.type(screen.getByLabelText("Code"), "VIP-PASS");
    expect(prefixInput).toBeDisabled();
  });

  it("switches the create form to discount mode and edits the discount percent", async () => {
    mockedCreatePromo.mockResolvedValue(structuredClone(DISCOUNT_PROMO));
    render(<AdminConsoleClient />);
    await screen.findByText("Total users");
    await userEvent.click(screen.getByRole("button", { name: "Promo codes" }));

    await userEvent.selectOptions(screen.getByLabelText("Type"), "discount");
    // The "Pro days" label flips to "Discount %" and drives discountPercent.
    await userEvent.clear(screen.getByLabelText("Discount %"));
    await userEvent.type(screen.getByLabelText("Discount %"), "40");
    await userEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() =>
      expect(mockedCreatePromo).toHaveBeenCalledWith(
        expect.objectContaining({
          promotion_type: "discount",
          discount_percent: 40,
          duration_days: null,
        }),
      ),
    );
  });

  it("edits a discount promo's draft fields and saves the discount_percent", async () => {
    render(<AdminConsoleClient />);
    await screen.findByText("Total users");
    await userEvent.click(screen.getByRole("button", { name: "Promo codes" }));

    const promoTable = await screen.findByRole("table");
    const row = within(promoTable).getByDisplayValue("summer").closest("tr") as HTMLElement;

    // discount_percent input cell (only present for discount promos).
    const discountInput = within(row).getByDisplayValue("25");
    await userEvent.clear(discountInput);
    await userEvent.type(discountInput, "35");

    // max_redemptions input cell.
    const maxInput = within(row).getByDisplayValue("5");
    await userEvent.clear(maxInput);
    await userEvent.type(maxInput, "8");

    // note input cell.
    const noteInput = within(row).getByDisplayValue("summer");
    await userEvent.clear(noteInput);
    await userEvent.type(noteInput, "summer-extended");

    await userEvent.click(within(row).getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(mockedUpdatePromo).toHaveBeenCalledWith("promo-discount", {
        note: "summer-extended",
        discount_percent: 35,
        max_redemptions: 8,
        expires_at: "2026-07-01T23:59:59.000Z",
      }),
    );
  });

  it("resumes a paused promo from the row Resume action", async () => {
    mockedPromos.mockResolvedValue([
      structuredClone({ ...ACCESS_PROMO, active: false }),
    ]);
    render(<AdminConsoleClient />);
    await screen.findByText("Total users");
    await userEvent.click(screen.getByRole("button", { name: "Promo codes" }));

    const row = (await screen.findByDisplayValue("launch")).closest("tr") as HTMLElement;
    await userEvent.click(within(row).getByRole("button", { name: "Resume" }));

    await waitFor(() =>
      expect(mockedUpdatePromo).toHaveBeenCalledWith("promo-access", { active: true }),
    );
  });

  it("toggles a subscription edit form open and closed without saving", async () => {
    const tinkoffItem = await gotoBilling();

    await userEvent.click(within(tinkoffItem).getByRole("button", { name: "Edit" }));
    expect(within(tinkoffItem).getByLabelText("Status")).toBeInTheDocument();

    await userEvent.click(within(tinkoffItem).getByRole("button", { name: "Close" }));
    await waitFor(() =>
      expect(within(tinkoffItem).queryByLabelText("Status")).not.toBeInTheDocument(),
    );
    expect(mockedUpdateSubscription).not.toHaveBeenCalled();
  });

  it("submits an unchanged subscription edit as a no-op", async () => {
    const tinkoffItem = await gotoBilling();

    await userEvent.click(within(tinkoffItem).getByRole("button", { name: "Edit" }));
    // Submit immediately — subPatchDiff yields an empty patch, so no API call.
    await userEvent.click(within(tinkoffItem).getByRole("button", { name: "Save subscription" }));

    // Give any pending microtasks a chance to run, then assert nothing fired.
    await Promise.resolve();
    expect(mockedUpdateSubscription).not.toHaveBeenCalled();
    // The form stays open because the no-op path returns before closing it.
    expect(within(tinkoffItem).getByLabelText("Status")).toBeInTheDocument();
  });

  it("sends every changed field through subPatchDiff", async () => {
    const tinkoffItem = await gotoBilling();
    await userEvent.type(screen.getByPlaceholderText("billing reason"), "manual edit");
    await userEvent.click(within(tinkoffItem).getByRole("button", { name: "Edit" }));

    await userEvent.selectOptions(within(tinkoffItem).getByLabelText("Status"), "past_due");
    await userEvent.selectOptions(within(tinkoffItem).getByLabelText("Plan"), "free");
    await userEvent.selectOptions(within(tinkoffItem).getByLabelText("Billing period"), "year");
    fireEvent.change(within(tinkoffItem).getByLabelText("Period start"), {
      target: { value: "2026-05-01" },
    });
    fireEvent.change(within(tinkoffItem).getByLabelText("Period end"), {
      target: { value: "2026-07-01" },
    });
    fireEvent.change(within(tinkoffItem).getByLabelText("Trial end"), {
      target: { value: "2026-06-15" },
    });
    fireEvent.change(within(tinkoffItem).getByLabelText("Next charge"), {
      target: { value: "2026-06-20" },
    });
    await userEvent.click(within(tinkoffItem).getByLabelText("Cancel at period end"));

    await userEvent.click(within(tinkoffItem).getByRole("button", { name: "Save subscription" }));

    await waitFor(() =>
      expect(mockedUpdateSubscription).toHaveBeenCalledWith("sub-tinkoff", {
        status: "past_due",
        plan: "free",
        billing_period: "year",
        cancel_at_period_end: true,
        current_period_start: "2026-05-01T12:00:00.000Z",
        current_period_end: "2026-07-01T12:00:00.000Z",
        trial_end: "2026-06-15T12:00:00.000Z",
        next_charge_at: "2026-06-20T12:00:00.000Z",
        reason: "manual edit",
      }),
    );
  });

  it("changes a user status with an empty reason (null) from the detail panel", async () => {
    render(<AdminConsoleClient />);
    await screen.findByText("Total users");
    await userEvent.click(screen.getByRole("button", { name: "Users" }));
    await userEvent.click(await screen.findByText("user@example.com"));
    await waitFor(() => expect(mockedGetUser).toHaveBeenCalledWith("user-1"));

    // Default selected status flips to "paused" for an active user; switch to
    // "deactivated" to exercise the status <select> onChange handler.
    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "" }) ?? screen.getByDisplayValue("paused"),
      "deactivated",
    );
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));

    await waitFor(() =>
      expect(mockedUpdateUserStatus).toHaveBeenCalledWith("user-1", {
        status: "deactivated",
        reason: null,
      }),
    );
  });
});
