import { apiFetch } from "./http";

export interface AdminStats {
  users: {
    total: number;
    new_30d: number;
    by_status: Record<string, number>;
  };
  promo: AdminPromoStats;
  usage: {
    recording_words: number;
    dictation_words: number;
    total_words: number;
    recording_duration_seconds: number;
    dictation_duration_seconds: number;
    recording_count: number;
    failed_recordings: number;
    monthly: AdminUsageBucket[];
    yearly: AdminUsageBucket[];
  };
  billing: {
    subscriptions_by_provider: Record<string, number>;
    subscriptions_by_status: Record<string, number>;
    revenue_by_currency: Record<string, number>;
    monthly_revenue: AdminRevenueBucket[];
  };
}

export interface AdminObservabilityAlert {
  severity: "critical" | "warning" | "info";
  code: string;
  title: string;
  value: number;
  threshold: number;
}

export interface AdminObservability {
  generated_at: string;
  server: {
    database: string;
    release: string | null;
    environment: string;
    log_format: string;
  };
  sentry: {
    configured: boolean;
    release: string | null;
    environment: string | null;
    traces_sample_rate: number | null;
    profiles_sample_rate: number | null;
  };
  recording_pipeline: {
    status_counts: Record<string, number>;
    last_24h: {
      total: number;
      ready: number;
      failed: number;
      processing: number;
      pending_upload?: number;
      uploading?: number;
    };
    failed_rate_24h: number;
    stuck_processing_count: number;
    low_transcript_coverage_count_24h: number;
    median_transcript_coverage_24h: number | null;
  };
  alerts: AdminObservabilityAlert[];
}

export interface AdminUsageBucket {
  period: string;
  recording_words: number;
  dictation_words: number;
  total_words: number;
  recording_duration_seconds: number;
  dictation_duration_seconds: number;
  recording_count: number;
  failed_recordings: number;
}

export interface AdminRevenueBucket {
  period: string;
  currency: string;
  amount: number;
}

export interface AdminPromoRedemptionBucket {
  period: string;
  redemptions: number;
}

export interface AdminPromoStats {
  total: number;
  active: number;
  paused: number;
  archived: number;
  expired: number;
  exhausted: number;
  redemptions: number;
  monthly_redemptions: AdminPromoRedemptionBucket[];
}

export interface AdminPromoCodeCreateInput {
  code: string | null;
  prefix: string;
  plan: string;
  promotion_type: "access" | "discount";
  billing_period: "month" | "year";
  duration_days: number | null;
  discount_percent: number | null;
  max_redemptions: number;
  expires_at: string | null;
  note: string | null;
}

export interface AdminPromoRedemption {
  user_id: string;
  user_email: string;
  subscription_id: string;
  redeemed_at: string;
}

export interface AdminPromoCode {
  id: string;
  code?: string;
  normalized_code?: string;
  plan: string;
  promotion_type: "access" | "discount";
  billing_period: string;
  duration_days: number | null;
  discount_percent: number | null;
  max_redemptions: number;
  redeemed_count: number;
  redemption_rate: number;
  active: boolean;
  archived_at: string | null;
  expires_at: string | null;
  note: string | null;
  created_at: string;
  redemptions: AdminPromoRedemption[];
}

export interface AdminUserSummary {
  id: string;
  email: string;
  account_status: "active" | "paused" | "deactivated";
  account_status_reason: string | null;
  created_at: string;
  current_plan: string;
  current_subscription_status: string | null;
  current_subscription_provider: string | null;
  dictation_words: number;
  recording_words: number;
  recording_count: number;
  dictation_duration_seconds: number;
  recording_duration_seconds: number;
  transcription_duration_seconds: number;
  companion_input_tokens: number;
  companion_output_tokens: number;
  companion_cached_tokens: number;
  companion_total_tokens: number;
  revenue_by_currency: Record<string, number>;
}

export interface AdminUserDetail extends AdminUserSummary {
  subscriptions: Array<Record<string, unknown>>;
  promo_redemptions: Array<Record<string, unknown>>;
  weekly_usage: Array<Record<string, unknown>>;
}

export interface AdminBillingInvoice {
  id: string;
  amount: number;
  currency: string;
  status: string;
  provider_payment_id: string | null;
  paid_at: string | null;
  created_at: string;
}

export interface AdminBillingSubscription {
  id: string;
  user_id: string;
  user_email: string;
  plan: string;
  status: string;
  provider: string;
  billing_period: string;
  current_period_start: string | null;
  current_period_end: string | null;
  cancel_at_period_end: boolean;
  canceled_at: string | null;
  trial_end: string | null;
  tinkoff_next_charge_at: string | null;
  invoices: AdminBillingInvoice[];
}

export interface AdminSubscriptionPatchInput {
  status?: string;
  plan?: string;
  billing_period?: "month" | "year";
  current_period_start?: string | null;
  current_period_end?: string | null;
  trial_end?: string | null;
  canceled_at?: string | null;
  cancel_at_period_end?: boolean;
  next_charge_at?: string | null;
  reason?: string | null;
}

export interface AdminAuditLog {
  id: string;
  actor_staff_member_id: string | null;
  actor_user_id: string | null;
  action: string;
  target_type: string;
  target_id: string | null;
  reason: string | null;
  details: Record<string, unknown>;
  created_at: string;
}

export function getAdminStats(): Promise<AdminStats> {
  return apiFetch<AdminStats>("/api/admin/stats");
}

export function getAdminObservability(): Promise<AdminObservability> {
  return apiFetch<AdminObservability>("/api/admin/observability");
}

export async function createAdminPromoCode(
  input: AdminPromoCodeCreateInput,
): Promise<AdminPromoCode> {
  return apiFetch<AdminPromoCode>("/api/admin/promo-codes", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function listAdminPromoCodes(): Promise<AdminPromoCode[]> {
  const payload = await apiFetch<{ items: AdminPromoCode[] }>("/api/admin/promo-codes");
  return payload.items;
}

export function updateAdminPromoCode(
  id: string,
  input: Partial<
    Pick<
      AdminPromoCode,
      "active" | "note" | "duration_days" | "discount_percent" | "max_redemptions" | "expires_at"
    >
  >,
): Promise<AdminPromoCode> {
  return apiFetch<AdminPromoCode>(`/api/admin/promo-codes/${id}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export async function archiveAdminPromoCode(id: string): Promise<void> {
  await apiFetch<void>(`/api/admin/promo-codes/${id}`, { method: "DELETE" });
}

export async function listAdminUsers(q = ""): Promise<AdminUserSummary[]> {
  const suffix = q.trim() ? `?q=${encodeURIComponent(q.trim())}` : "";
  const payload = await apiFetch<{ items: AdminUserSummary[] }>(`/api/admin/users${suffix}`);
  return payload.items;
}

export function getAdminUser(id: string): Promise<AdminUserDetail> {
  return apiFetch<AdminUserDetail>(`/api/admin/users/${id}`);
}

export function updateAdminUserStatus(
  id: string,
  input: { status: AdminUserSummary["account_status"]; reason: string | null },
): Promise<AdminUserSummary> {
  return apiFetch<AdminUserSummary>(`/api/admin/users/${id}/status`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export function grantAdminSubscription(
  id: string,
  input: { duration_days: number; reason: string | null },
): Promise<Record<string, unknown>> {
  return apiFetch<Record<string, unknown>>(`/api/admin/users/${id}/subscriptions/grant`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function listAdminBilling(): Promise<AdminBillingSubscription[]> {
  const payload = await apiFetch<{ items: AdminBillingSubscription[] }>("/api/admin/billing");
  return payload.items;
}

export function cancelAdminSubscription(
  id: string,
  input: { mode: "period_end" | "immediate"; reason: string | null },
): Promise<Record<string, unknown>> {
  return apiFetch<Record<string, unknown>>(`/api/admin/subscriptions/${id}/cancel`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function resumeAdminSubscription(
  id: string,
  input: { reason: string | null },
): Promise<Record<string, unknown>> {
  return apiFetch<Record<string, unknown>>(`/api/admin/subscriptions/${id}/resume`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function updateAdminSubscription(
  id: string,
  input: AdminSubscriptionPatchInput,
): Promise<AdminBillingSubscription> {
  return apiFetch<AdminBillingSubscription>(`/api/admin/subscriptions/${id}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export function runAdminSubscriptionRenewal(
  id: string,
  input: { reason: string | null } = { reason: null },
): Promise<{ charged: boolean; skipped?: boolean; reason?: string; result?: string; status?: string }> {
  return apiFetch(`/api/admin/subscriptions/${id}/run-renewal`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function refundAdminInvoice(
  id: string,
  input: { amount_minor: number | null; reason: string | null },
): Promise<Record<string, unknown>> {
  return apiFetch<Record<string, unknown>>(`/api/admin/invoices/${id}/refund`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function listAdminAudit(): Promise<AdminAuditLog[]> {
  const payload = await apiFetch<{ items: AdminAuditLog[] }>("/api/admin/audit");
  return payload.items;
}
