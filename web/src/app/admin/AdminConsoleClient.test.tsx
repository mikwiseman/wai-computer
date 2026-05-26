import { render, screen, waitFor, within } from "@testing-library/react";
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
  updateAdminPromoCode,
  updateAdminUserStatus,
} from "@/lib/admin";
import { AdminConsoleClient } from "./AdminConsoleClient";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams("tab=overview"),
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
  updateAdminPromoCode: vi.fn(),
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

function setupMocks() {
  mockedStats.mockResolvedValue({
    users: { total: 3, new_30d: 2, by_status: { active: 2, paused: 1 } },
    promo: {
      total: 1,
      active: 1,
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
      subscriptions_by_provider: { stripe: 1 },
      subscriptions_by_status: { active: 1 },
      revenue_by_currency: { USD: 12 },
      monthly_revenue: [{ period: "2026-05", currency: "USD", amount: 12 }],
    },
  });
  mockedObservability.mockResolvedValue({
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
      last_24h: {
        total: 4,
        ready: 2,
        failed: 1,
        processing: 1,
      },
      failed_rate_24h: 0.25,
      stuck_processing_count: 1,
      low_transcript_coverage_count_24h: 1,
      median_transcript_coverage_24h: 0.68,
    },
    alerts: [
      {
        severity: "critical",
        code: "recording.processing.stuck",
        title: "Stuck processing recordings",
        value: 1,
        threshold: 0,
      },
    ],
  });
  mockedPromos.mockResolvedValue([
    {
      id: "promo-1",
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
    },
  ]);
  mockedUsers.mockResolvedValue([
    {
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
    },
  ]);
  mockedGetUser.mockResolvedValue({
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
    subscriptions: [],
    promo_redemptions: [],
    weekly_usage: [],
  });
  mockedBilling.mockResolvedValue([
    {
      id: "sub-1",
      user_id: "user-1",
      user_email: "user@example.com",
      plan: "pro",
      status: "active",
      provider: "stripe",
      billing_period: "month",
      current_period_end: "2026-06-25T00:00:00Z",
      cancel_at_period_end: false,
      invoices: [
        {
          id: "invoice-1",
          amount: 1200,
          currency: "USD",
          status: "paid",
          provider_payment_id: "pi_123",
          paid_at: "2026-05-25T00:00:00Z",
          created_at: "2026-05-25T00:00:00Z",
        },
      ],
    },
  ]);
  mockedAudit.mockResolvedValue([
    {
      id: "audit-1",
      actor_staff_member_id: "staff-1",
      actor_user_id: "admin-1",
      action: "admin.user_status.updated",
      target_type: "user",
      target_id: "user-1",
      reason: "support request",
      details: {},
      created_at: "2026-05-25T00:00:00Z",
    },
  ]);
  mockedArchivePromo.mockResolvedValue();
  mockedUpdateUserStatus.mockResolvedValue({
    id: "user-1",
    email: "user@example.com",
    account_status: "paused",
    account_status_reason: "support request",
    created_at: "2026-05-25T00:00:00Z",
    current_plan: "pro",
    current_subscription_status: "active",
    current_subscription_provider: "stripe",
    dictation_words: 30,
    recording_words: 120,
    recording_count: 4,
  });
  mockedGrantSubscription.mockResolvedValue({});
  mockedCancelSubscription.mockResolvedValue({});
  mockedResumeSubscription.mockResolvedValue({});
  mockedRefundInvoice.mockResolvedValue({});
}

describe("AdminConsoleClient", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    setupMocks();
  });

  it("loads admin statistics and promo codes", async () => {
    render(<AdminConsoleClient />);

    expect(await screen.findByText("Total users")).toBeInTheDocument();
    expect(screen.getAllByText("150").length).toBeGreaterThan(0);
    expect(screen.getByText("Monthly usage")).toBeInTheDocument();
    expect(screen.getAllByText("2026-05").length).toBeGreaterThan(0);

    await userEvent.click(screen.getByRole("button", { name: "Promo codes" }));

    expect(await screen.findByDisplayValue("launch")).toBeInTheDocument();
    expect(screen.getByText("WAI-LAUNCH-30")).toBeInTheDocument();
    expect(screen.getByText("2 / 10")).toBeInTheDocument();
  });

  it("shows observability signals in the admin console", async () => {
    render(<AdminConsoleClient />);

    await screen.findByText("Total users");
    await userEvent.click(screen.getByRole("button", { name: "Observability" }));

    expect(await screen.findByText("Sentry")).toBeInTheDocument();
    expect(screen.getByText("configured")).toBeInTheDocument();
    expect(screen.getByText("Stuck processing recordings")).toBeInTheDocument();
    expect(screen.getByText("recording.processing.stuck")).toBeInTheDocument();
  });

  it("creates a promo code and shows plaintext once", async () => {
    mockedCreatePromo.mockResolvedValue({
      id: "promo-new",
      code: "WAI-NEW-30",
      normalized_code: "WAINEW30",
      plan: "pro",
      promotion_type: "access",
      billing_period: "month",
      duration_days: 30,
      discount_percent: null,
      max_redemptions: 1,
      redeemed_count: 0,
      redemption_rate: 0,
      active: true,
      archived_at: null,
      expires_at: "2026-06-25T00:00:00Z",
      note: null,
      created_at: "2026-05-25T00:00:00Z",
      redemptions: [],
    });
    render(<AdminConsoleClient />);

    await screen.findByText("Total users");
    await userEvent.click(screen.getByRole("button", { name: "Promo codes" }));
    await userEvent.clear(screen.getByLabelText("Redemptions"));
    await userEvent.type(screen.getByLabelText("Redemptions"), "5");
    await userEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() =>
      expect(mockedCreatePromo).toHaveBeenCalledWith({
        code: null,
        prefix: "WAI",
        plan: "pro",
        promotion_type: "access",
        billing_period: "month",
        duration_days: 30,
        discount_percent: null,
        max_redemptions: 5,
        expires_at: expect.any(String),
        note: null,
      }),
    );
    expect(await screen.findByText("WAI-NEW-30")).toBeInTheDocument();
  });

  it("creates a percent discount promo code with an expiry date", async () => {
    mockedCreatePromo.mockResolvedValue({
      id: "promo-discount",
      code: "WAI-OFF-25",
      normalized_code: "WAIOFF25",
      plan: "pro",
      promotion_type: "discount",
      billing_period: "year",
      duration_days: null,
      discount_percent: 25,
      max_redemptions: 3,
      redeemed_count: 0,
      redemption_rate: 0,
      active: true,
      archived_at: null,
      expires_at: "2026-06-25T23:59:59Z",
      note: null,
      created_at: "2026-05-25T00:00:00Z",
      redemptions: [],
    });
    render(<AdminConsoleClient />);

    await screen.findByText("Total users");
    await userEvent.click(screen.getByRole("button", { name: "Promo codes" }));
    await userEvent.selectOptions(screen.getByLabelText("Type"), "discount");
    await userEvent.selectOptions(screen.getByLabelText("Checkout period"), "year");
    await userEvent.clear(screen.getByLabelText("Discount %"));
    await userEvent.type(screen.getByLabelText("Discount %"), "25");
    await userEvent.clear(screen.getByLabelText("Redemptions"));
    await userEvent.type(screen.getByLabelText("Redemptions"), "3");
    await userEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() =>
      expect(mockedCreatePromo).toHaveBeenCalledWith({
        code: null,
        prefix: "WAI",
        plan: "pro",
        promotion_type: "discount",
        billing_period: "year",
        duration_days: null,
        discount_percent: 25,
        max_redemptions: 3,
        expires_at: expect.any(String),
        note: null,
      }),
    );
    expect(await screen.findByText("WAI-OFF-25")).toBeInTheDocument();
  });

  it("updates promo metadata from the table row", async () => {
    mockedUpdatePromo.mockResolvedValue({
      id: "promo-1",
      code: "WAI-LAUNCH-30",
      normalized_code: "WAILAUNCH30",
      plan: "pro",
      promotion_type: "access",
      billing_period: "month",
      duration_days: 45,
      discount_percent: null,
      max_redemptions: 10,
      redeemed_count: 2,
      redemption_rate: 0.2,
      active: true,
      archived_at: null,
      expires_at: null,
      note: "updated",
      created_at: "2026-05-25T00:00:00Z",
      redemptions: [],
    });
    render(<AdminConsoleClient />);

    await screen.findByText("Total users");
    await userEvent.click(screen.getByRole("button", { name: "Promo codes" }));
    const row = screen.getByDisplayValue("launch").closest("tr");
    expect(row).not.toBeNull();
    await userEvent.clear(within(row as HTMLTableRowElement).getByDisplayValue("launch"));
    await userEvent.type(within(row as HTMLTableRowElement).getByDisplayValue(""), "updated");
    await userEvent.click(within(row as HTMLTableRowElement).getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(mockedUpdatePromo).toHaveBeenCalledWith("promo-1", {
        note: "updated",
        duration_days: 30,
        max_redemptions: 10,
      }),
    );
  });

  it("pauses and archives promo codes from the row actions", async () => {
    render(<AdminConsoleClient />);

    await screen.findByText("Total users");
    await userEvent.click(screen.getByRole("button", { name: "Promo codes" }));
    const row = screen.getByDisplayValue("launch").closest("tr");
    expect(row).not.toBeNull();
    await userEvent.click(within(row as HTMLTableRowElement).getByRole("button", { name: "Pause" }));

    await waitFor(() => expect(mockedUpdatePromo).toHaveBeenCalledWith("promo-1", { active: false }));

    await userEvent.click(within(row as HTMLTableRowElement).getByRole("button", { name: "Archive" }));

    await waitFor(() => expect(mockedArchivePromo).toHaveBeenCalledWith("promo-1"));
  });

  it("opens users, changes account status, and grants admin Pro", async () => {
    render(<AdminConsoleClient />);

    await screen.findByText("Total users");
    await userEvent.click(screen.getByRole("button", { name: "Users" }));
    await userEvent.click(await screen.findByText("user@example.com"));
    await waitFor(() => expect(mockedGetUser).toHaveBeenCalledWith("user-1"));
    await userEvent.type(screen.getByPlaceholderText("reason"), "support request");
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));

    await waitFor(() =>
      expect(mockedUpdateUserStatus).toHaveBeenCalledWith("user-1", {
        status: "paused",
        reason: "support request",
      }),
    );

    await userEvent.click(screen.getByRole("button", { name: "Grant Pro" }));

    await waitFor(() =>
      expect(mockedGrantSubscription).toHaveBeenCalledWith("user-1", {
        duration_days: 30,
        reason: "support request",
      }),
    );
  });

  it("runs billing provider actions and invoice refunds", async () => {
    render(<AdminConsoleClient />);

    await screen.findByText("Total users");
    await userEvent.click(screen.getByRole("button", { name: "Billing" }));
    await screen.findByText("stripe · pro · active · renewing");
    await userEvent.type(screen.getByPlaceholderText("billing reason"), "billing issue");
    await userEvent.click(screen.getByRole("button", { name: "Cancel later" }));

    await waitFor(() =>
      expect(mockedCancelSubscription).toHaveBeenCalledWith("sub-1", {
        mode: "period_end",
        reason: "billing issue",
      }),
    );

    await userEvent.click(screen.getByRole("button", { name: "Cancel now" }));
    await waitFor(() =>
      expect(mockedCancelSubscription).toHaveBeenCalledWith("sub-1", {
        mode: "immediate",
        reason: "billing issue",
      }),
    );

    await userEvent.click(screen.getByRole("button", { name: "Resume" }));
    await waitFor(() =>
      expect(mockedResumeSubscription).toHaveBeenCalledWith("sub-1", {
        reason: "billing issue",
      }),
    );

    await userEvent.click(screen.getByRole("button", { name: "Refund" }));
    await waitFor(() =>
      expect(mockedRefundInvoice).toHaveBeenCalledWith("invoice-1", {
        amount_minor: null,
        reason: "billing issue",
      }),
    );
  });

  it("shows audit events", async () => {
    render(<AdminConsoleClient />);

    await screen.findByText("Total users");
    await userEvent.click(screen.getByRole("button", { name: "Audit" }));

    expect(await screen.findByText("admin.user_status.updated")).toBeInTheDocument();
    expect(screen.getByText("user:user-1")).toBeInTheDocument();
    expect(screen.getByText("support request")).toBeInTheDocument();
  });
});
