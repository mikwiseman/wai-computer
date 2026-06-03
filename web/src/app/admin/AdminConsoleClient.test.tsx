import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  archiveAdminPromoCode,
  cancelAdminSubscription,
  createAdminPromoCode,
  getAdminAiUsage,
  getAdminDeepgramUsage,
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
  getAdminAiUsage: vi.fn(),
  getAdminDeepgramUsage: vi.fn(),
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
const mockedAiUsage = vi.mocked(getAdminAiUsage);
const mockedDeepgramUsage = vi.mocked(getAdminDeepgramUsage);
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
  mockedAiUsage.mockResolvedValue({
    generated_at: "2026-06-03T09:00:00Z",
    window_days: 7,
    filters: { days: 7 },
    summary: {
      events: 4,
      estimated_cost_usd: 1.25,
      input_tokens: 3000,
      output_tokens: 1200,
      cached_tokens: 500,
      reasoning_tokens: 100,
      total_tokens: 4200,
      billable_seconds: 120,
      audio_seconds: 120,
      failed_events: 1,
      refused_events: 1,
      unpriced_events: 2,
      avg_latency_ms: 240,
      p95_latency_ms: 900,
    },
    by_day: [
      {
        date: "2026-06-03",
        events: 4,
        estimated_cost_usd: 1.25,
        total_tokens: 4200,
        billable_seconds: 120,
        failed_events: 1,
        refused_events: 1,
      },
    ],
    by_provider: [
      {
        provider: "openai",
        events: 3,
        estimated_cost_usd: 1.25,
        total_tokens: 4200,
        input_tokens: 3000,
        output_tokens: 1200,
        billable_seconds: 0,
        failed_events: 1,
        refused_events: 0,
        unpriced_events: 1,
        last_event_at: "2026-06-03T09:00:00Z",
      },
      {
        provider: "deepgram",
        events: 1,
        estimated_cost_usd: 0,
        total_tokens: 0,
        input_tokens: 0,
        output_tokens: 0,
        billable_seconds: 120,
        failed_events: 0,
        refused_events: 1,
        unpriced_events: 1,
        last_event_at: "2026-06-03T09:00:00Z",
      },
    ],
    by_feature: [
      {
        feature: "companion",
        events: 2,
        estimated_cost_usd: 1.2,
        total_tokens: 4000,
        input_tokens: 2900,
        output_tokens: 1100,
        billable_seconds: 0,
        failed_events: 0,
        refused_events: 0,
        unpriced_events: 1,
        last_event_at: "2026-06-03T09:00:00Z",
      },
      {
        feature: "dictation",
        events: 1,
        estimated_cost_usd: 0,
        total_tokens: 0,
        input_tokens: 0,
        output_tokens: 0,
        billable_seconds: 120,
        failed_events: 0,
        refused_events: 1,
        unpriced_events: 1,
        last_event_at: "2026-06-03T09:00:00Z",
      },
    ],
    by_model: [
      {
        provider: "openai",
        model: "gpt-5.5",
        events: 2,
        estimated_cost_usd: 1.2,
        total_tokens: 4000,
        input_tokens: 2900,
        output_tokens: 1100,
        billable_seconds: 0,
        failed_events: 0,
        refused_events: 0,
        unpriced_events: 1,
        last_event_at: "2026-06-03T09:00:00Z",
      },
    ],
    by_user: [
      {
        user_id: "user-1",
        email: "user@example.com",
        events: 4,
        estimated_cost_usd: 1.25,
        total_tokens: 4200,
        billable_seconds: 120,
        failed_events: 1,
        refused_events: 1,
        unpriced_events: 2,
        last_event_at: "2026-06-03T09:00:00Z",
      },
    ],
    recent_events: [
      {
        id: "ai-event-1",
        created_at: "2026-06-03T09:00:00Z",
        user_id: "user-1",
        email: "user@example.com",
        recording_id: null,
        item_id: null,
        conversation_id: "conversation-1",
        message_id: "message-1",
        provider: "openai",
        feature: "companion",
        operation: "companion.turn",
        status: "succeeded",
        model: "gpt-5.5",
        input_tokens: 3000,
        output_tokens: 1200,
        cached_tokens: 500,
        reasoning_tokens: 100,
        total_tokens: 4200,
        billable_seconds: null,
        estimated_cost_usd: 1.25,
        pricing_status: "priced",
        latency_ms: 240,
        provider_status_code: null,
        provider_error_code: null,
        guard_code: null,
        error_type: null,
      },
    ],
    analysis: [
      {
        severity: "warning",
        code: "ai_usage.unpriced_models",
        title: "Some model calls cannot be costed yet",
        detail: "2 events have usage metrics but no configured provider/model price.",
      },
    ],
  });
  mockedDeepgramUsage.mockResolvedValue({
    generated_at: "2026-06-03T09:00:00Z",
    window_days: 7,
    captured: {
      events: 3,
      audio_seconds: 180,
      billable_seconds: 120,
      succeeded: 1,
      failed: 1,
      refused: 1,
      provider_402: 1,
    },
    estimated: {
      recording_seconds: 600,
      recording_words: 120,
      recording_count: 4,
      failed_recordings: 1,
      dictation_seconds: 12,
      dictation_words: 30,
      dictation_entries: 2,
      total_seconds: 612,
    },
    by_user: [
      {
        user_id: "user-1",
        email: "user@example.com",
        captured_events: 3,
        captured_billable_seconds: 120,
        captured_audio_seconds: 180,
        captured_failed_events: 1,
        captured_refused_events: 1,
        provider_402_events: 1,
        recording_count: 4,
        failed_recordings: 1,
        estimated_recording_seconds: 600,
        estimated_recording_words: 120,
        dictation_entries: 2,
        estimated_dictation_seconds: 12,
        estimated_dictation_words: 30,
        estimated_total_seconds: 612,
        last_event_at: "2026-06-03T09:00:00Z",
      },
    ],
    by_operation: [
      {
        operation: "file_stt",
        purpose: "recording",
        status: "failed",
        events: 1,
        audio_seconds: 120,
        billable_seconds: 0,
        provider_402: 1,
      },
    ],
    by_day: [
      {
        date: "2026-06-03",
        captured_events: 3,
        captured_audio_seconds: 180,
        captured_billable_seconds: 120,
        captured_failed_events: 1,
        captured_refused_events: 1,
        estimated_recordings: 4,
        estimated_recording_seconds: 600,
        estimated_dictation_entries: 2,
        estimated_dictation_seconds: 12,
      },
    ],
    top_recordings: [
      {
        recording_id: "recording-1",
        user_id: "user-1",
        email: "user@example.com",
        status: "failed",
        failure_code: "provider_unavailable",
        created_at: "2026-06-03T08:00:00Z",
        duration_seconds: 120,
        billed_word_count: 0,
        captured_events: 2,
        captured_billable_seconds: 0,
        failed_events: 1,
        refused_events: 1,
        provider_402_events: 1,
        last_event_at: "2026-06-03T09:00:00Z",
      },
    ],
    recent_events: [
      {
        id: "event-1",
        created_at: "2026-06-03T09:00:00Z",
        user_id: "user-1",
        email: "user@example.com",
        recording_id: "recording-1",
        operation: "file_stt",
        purpose: "recording",
        status: "failed",
        model: "nova-3",
        language: "ru",
        content_type: "audio/mp4",
        audio_seconds: 120,
        billable_seconds: 0,
        channel_count: 1,
        audio_bytes: 36066,
        latency_ms: 900,
        provider_status_code: 402,
        provider_error_code: "ASR_PAYMENT_REQUIRED",
        guard_code: null,
        error_type: "HTTPStatusError",
      },
    ],
    analysis: [
      {
        severity: "critical",
        code: "deepgram.provider.payment_required",
        title: "Deepgram is refusing requests with 402",
        detail: "1 provider attempts returned payment-required.",
      },
    ],
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
      dictation_duration_seconds: 12,
      recording_duration_seconds: 600,
      transcription_duration_seconds: 612,
      companion_input_tokens: 100,
      companion_output_tokens: 40,
      companion_cached_tokens: 25,
      companion_total_tokens: 140,
      revenue_by_currency: { USD: 12 },
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
    dictation_duration_seconds: 12,
    recording_duration_seconds: 600,
    transcription_duration_seconds: 612,
    companion_input_tokens: 100,
    companion_output_tokens: 40,
    companion_cached_tokens: 25,
    companion_total_tokens: 140,
    revenue_by_currency: { USD: 12 },
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
      current_period_start: "2026-05-25T00:00:00Z",
      current_period_end: "2026-06-25T00:00:00Z",
      cancel_at_period_end: false,
      canceled_at: null,
      trial_end: null,
      tinkoff_next_charge_at: null,
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
    {
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
    dictation_duration_seconds: 12,
    recording_duration_seconds: 600,
    transcription_duration_seconds: 612,
    companion_input_tokens: 100,
    companion_output_tokens: 40,
    companion_cached_tokens: 25,
    companion_total_tokens: 140,
    revenue_by_currency: { USD: 12 },
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
    const promoTable = screen.getByRole("table");
    expect(within(promoTable).queryByRole("columnheader", { name: "Plan" })).not.toBeInTheDocument();
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

  it("shows Deepgram usage analysis in the admin console", async () => {
    render(<AdminConsoleClient />);

    await screen.findByText("Total users");
    await userEvent.click(screen.getByRole("button", { name: "Deepgram" }));

    expect(await screen.findByText("Burn analysis")).toBeInTheDocument();
    expect(screen.getByText("Deepgram is refusing requests with 402")).toBeInTheDocument();
    expect(screen.getByText("Users by Deepgram usage")).toBeInTheDocument();
    expect(screen.getAllByText("file_stt/recording").length).toBeGreaterThan(0);
  });

  it("shows unified AI usage analysis and applies filters", async () => {
    render(<AdminConsoleClient />);

    await screen.findByText("Total users");
    await userEvent.click(screen.getByRole("button", { name: "AI usage" }));

    expect(await screen.findByText("Daily AI usage")).toBeInTheDocument();
    expect(screen.getByText("Spend analysis")).toBeInTheDocument();
    expect(screen.getByText("Some model calls cannot be costed yet")).toBeInTheDocument();
    expect(screen.getByText("Users by AI usage")).toBeInTheDocument();
    expect(screen.getByText("Recent AI events")).toBeInTheDocument();
    expect(screen.getAllByText("gpt-5.5").length).toBeGreaterThan(0);

    await userEvent.type(screen.getByPlaceholderText("email or id"), "user@example.com");
    await userEvent.click(screen.getByRole("button", { name: "Apply" }));

    await waitFor(() =>
      expect(mockedAiUsage).toHaveBeenLastCalledWith({
        days: 7,
        provider: "",
        feature: "",
        model: "",
        status: "",
        q: "user@example.com",
        limit: 100,
      }),
    );
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
        expires_at: "2026-06-25T23:59:59.000Z",
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
    const stripeItem = (await screen.findByText("stripe · pro · active · renewing")).closest(
      "section",
    ) as HTMLElement;
    await userEvent.type(screen.getByPlaceholderText("billing reason"), "billing issue");
    await userEvent.click(within(stripeItem).getByRole("button", { name: "Cancel later" }));

    await waitFor(() =>
      expect(mockedCancelSubscription).toHaveBeenCalledWith("sub-1", {
        mode: "period_end",
        reason: "billing issue",
      }),
    );

    await userEvent.click(within(stripeItem).getByRole("button", { name: "Cancel now" }));
    await waitFor(() =>
      expect(mockedCancelSubscription).toHaveBeenCalledWith("sub-1", {
        mode: "immediate",
        reason: "billing issue",
      }),
    );

    await userEvent.click(within(stripeItem).getByRole("button", { name: "Resume" }));
    await waitFor(() =>
      expect(mockedResumeSubscription).toHaveBeenCalledWith("sub-1", {
        reason: "billing issue",
      }),
    );

    await userEvent.click(within(stripeItem).getByRole("button", { name: "Refund" }));
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

  it("splits the promo benefit into Pro days and Discount % columns", async () => {
    render(<AdminConsoleClient />);
    await screen.findByText("Total users");
    await userEvent.click(screen.getByRole("button", { name: "Promo codes" }));
    const promoTable = await screen.findByRole("table");
    expect(
      within(promoTable).getByRole("columnheader", { name: "Pro days" }),
    ).toBeInTheDocument();
    expect(
      within(promoTable).getByRole("columnheader", { name: "Discount %" }),
    ).toBeInTheDocument();
    // The access promo shows a Pro-days input and a "—" in the discount column.
    const row = within(promoTable).getByDisplayValue("launch").closest("tr") as HTMLElement;
    expect(within(row).getByText("—")).toBeInTheDocument();
  });

  it("edits a Tinkoff subscription's next charge date", async () => {
    mockedUpdateSubscription.mockResolvedValue({} as never);
    render(<AdminConsoleClient />);
    await screen.findByText("Total users");
    await userEvent.click(screen.getByRole("button", { name: "Billing" }));
    const tinkoffItem = (await screen.findByText("tinkoff · pro · active · renewing")).closest(
      "section",
    ) as HTMLElement;
    await userEvent.click(within(tinkoffItem).getByRole("button", { name: "Edit" }));
    fireEvent.change(within(tinkoffItem).getByLabelText("Next charge"), {
      target: { value: "2026-05-30" },
    });
    await userEvent.click(within(tinkoffItem).getByRole("button", { name: "Save subscription" }));

    await waitFor(() =>
      expect(mockedUpdateSubscription).toHaveBeenCalledWith("sub-tinkoff", {
        next_charge_at: "2026-05-30T12:00:00.000Z",
        reason: null,
      }),
    );
  });

  it("runs a Tinkoff renewal on demand and reports the result", async () => {
    mockedRunRenewal.mockResolvedValue({ charged: true });
    render(<AdminConsoleClient />);
    await screen.findByText("Total users");
    await userEvent.click(screen.getByRole("button", { name: "Billing" }));
    const tinkoffItem = (await screen.findByText("tinkoff · pro · active · renewing")).closest(
      "section",
    ) as HTMLElement;
    await userEvent.click(within(tinkoffItem).getByRole("button", { name: "Run renewal now" }));

    await waitFor(() =>
      expect(mockedRunRenewal).toHaveBeenCalledWith("sub-tinkoff", { reason: null }),
    );
    expect(await screen.findByText("Renewal charged.")).toBeInTheDocument();
  });

  it("logs out and redirects to login", async () => {
    mockedLogout.mockResolvedValue({ message: "Logged out" });
    render(<AdminConsoleClient />);

    await screen.findByText("Total users");
    await userEvent.click(screen.getByTestId("admin-logout-button"));

    await waitFor(() => expect(mockedLogout).toHaveBeenCalledTimes(1));
    expect(mockReplace).toHaveBeenCalledWith("/login");
  });
});
