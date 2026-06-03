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

export interface AdminDeepgramUsage {
  generated_at: string;
  window_days: number;
  captured: {
    events: number;
    audio_seconds: number;
    billable_seconds: number;
    succeeded: number;
    failed: number;
    refused: number;
    provider_402: number;
  };
  estimated: {
    recording_seconds: number;
    recording_words: number;
    recording_count: number;
    failed_recordings: number;
    dictation_seconds: number;
    dictation_words: number;
    dictation_entries: number;
    total_seconds: number;
  };
  by_user: AdminDeepgramUserUsage[];
  by_operation: AdminDeepgramOperationUsage[];
  by_day: AdminDeepgramDayUsage[];
  top_recordings: AdminDeepgramRecordingUsage[];
  recent_events: AdminDeepgramUsageEvent[];
  analysis: AdminDeepgramAnalysisItem[];
}

export interface AdminAiUsage {
  generated_at: string;
  window_days: number;
  filters: Record<string, string | number | null>;
  summary: AdminAiUsageSummary;
  by_day: AdminAiUsageDay[];
  by_provider: AdminAiUsageGroup[];
  by_feature: AdminAiUsageGroup[];
  by_model: AdminAiUsageModel[];
  by_user: AdminAiUsageUser[];
  recent_events: AdminAiUsageEvent[];
  analysis: AdminAiUsageAnalysisItem[];
}

export interface AdminAiUsageSummary {
  events: number;
  estimated_cost_usd: number;
  input_tokens: number;
  output_tokens: number;
  cached_tokens: number;
  reasoning_tokens: number;
  total_tokens: number;
  billable_seconds: number;
  audio_seconds: number;
  failed_events: number;
  refused_events: number;
  unpriced_events: number;
  avg_latency_ms: number;
  p95_latency_ms: number | null;
}

export interface AdminAiUsageAnalysisItem {
  severity: "critical" | "warning" | "info";
  code: string;
  title: string;
  detail: string;
}

export interface AdminAiUsageDay {
  date: string;
  events: number;
  estimated_cost_usd: number;
  total_tokens: number;
  billable_seconds: number;
  failed_events: number;
  refused_events: number;
}

export interface AdminAiUsageGroup {
  provider?: string;
  feature?: string;
  events: number;
  estimated_cost_usd: number;
  total_tokens: number;
  input_tokens: number;
  output_tokens: number;
  billable_seconds: number;
  failed_events: number;
  refused_events: number;
  unpriced_events: number;
  last_event_at: string | null;
}

export interface AdminAiUsageModel extends AdminAiUsageGroup {
  provider: string;
  model: string | null;
}

export interface AdminAiUsageUser {
  user_id: string;
  email: string | null;
  events: number;
  estimated_cost_usd: number;
  total_tokens: number;
  billable_seconds: number;
  failed_events: number;
  refused_events: number;
  unpriced_events: number;
  last_event_at: string | null;
}

export interface AdminAiUsageEvent {
  id: string;
  created_at: string;
  user_id: string | null;
  email: string | null;
  recording_id: string | null;
  item_id: string | null;
  conversation_id: string | null;
  message_id: string | null;
  provider: string;
  feature: string;
  operation: string;
  status: string;
  model: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  cached_tokens: number | null;
  reasoning_tokens: number | null;
  total_tokens: number | null;
  billable_seconds: number | null;
  estimated_cost_usd: number | null;
  pricing_status: string;
  latency_ms: number | null;
  provider_status_code: number | null;
  provider_error_code: string | null;
  guard_code: string | null;
  error_type: string | null;
}

export interface AdminAiUsageFilters {
  days?: number;
  provider?: string;
  feature?: string;
  model?: string;
  status?: string;
  user_id?: string;
  q?: string;
  limit?: number;
}

export interface AdminDeepgramAnalysisItem {
  severity: "critical" | "warning" | "info";
  code: string;
  title: string;
  detail: string;
}

export interface AdminDeepgramUserUsage {
  user_id: string;
  email: string | null;
  captured_events: number;
  captured_billable_seconds: number;
  captured_audio_seconds: number;
  captured_failed_events: number;
  captured_refused_events: number;
  provider_402_events: number;
  recording_count: number;
  failed_recordings: number;
  estimated_recording_seconds: number;
  estimated_recording_words: number;
  dictation_entries: number;
  estimated_dictation_seconds: number;
  estimated_dictation_words: number;
  estimated_total_seconds: number;
  last_event_at: string | null;
}

export interface AdminDeepgramOperationUsage {
  operation: string;
  purpose: string;
  status: string;
  events: number;
  audio_seconds: number;
  billable_seconds: number;
  provider_402: number;
}

export interface AdminDeepgramDayUsage {
  date: string;
  captured_events: number;
  captured_audio_seconds: number;
  captured_billable_seconds: number;
  captured_failed_events: number;
  captured_refused_events: number;
  estimated_recordings: number;
  estimated_recording_seconds: number;
  estimated_dictation_entries: number;
  estimated_dictation_seconds: number;
}

export interface AdminDeepgramRecordingUsage {
  recording_id: string;
  user_id: string;
  email: string | null;
  status: string;
  failure_code: string | null;
  created_at: string | null;
  duration_seconds: number;
  billed_word_count: number;
  captured_events: number;
  captured_billable_seconds: number;
  failed_events: number;
  refused_events: number;
  provider_402_events: number;
  last_event_at: string | null;
}

export interface AdminDeepgramUsageEvent {
  id: string;
  created_at: string;
  user_id: string | null;
  email: string | null;
  recording_id: string | null;
  operation: string;
  purpose: string;
  status: string;
  model: string | null;
  language: string | null;
  content_type: string | null;
  audio_seconds: number | null;
  billable_seconds: number | null;
  channel_count: number | null;
  audio_bytes: number | null;
  latency_ms: number | null;
  provider_status_code: number | null;
  provider_error_code: string | null;
  guard_code: string | null;
  error_type: string | null;
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

export function getAdminDeepgramUsage(days = 7): Promise<AdminDeepgramUsage> {
  return apiFetch<AdminDeepgramUsage>(`/api/admin/deepgram-usage?days=${days}`);
}

export function getAdminAiUsage(filters: AdminAiUsageFilters = {}): Promise<AdminAiUsage> {
  const params = new URLSearchParams();
  params.set("days", String(filters.days ?? 7));
  if (filters.provider?.trim()) params.set("provider", filters.provider.trim());
  if (filters.feature?.trim()) params.set("feature", filters.feature.trim());
  if (filters.model?.trim()) params.set("model", filters.model.trim());
  if (filters.status?.trim()) params.set("status", filters.status.trim());
  if (filters.user_id?.trim()) params.set("user_id", filters.user_id.trim());
  if (filters.q?.trim()) params.set("q", filters.q.trim());
  if (filters.limit) params.set("limit", String(filters.limit));
  return apiFetch<AdminAiUsage>(`/api/admin/ai-usage?${params.toString()}`);
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
