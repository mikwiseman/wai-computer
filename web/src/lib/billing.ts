import { apiFetch } from "./http";

export interface BillingPlan {
  code: string;
  name: string;
  description: string | null;
  usd_amount_monthly: number | null;
  usd_amount_yearly: number | null;
  rub_amount_monthly: number | null;
  rub_amount_yearly: number | null;
  word_cap_per_week: number | null;
  memory_retention_days: number | null;
  features: Record<string, boolean>;
}

export interface BillingSubscription {
  plan: BillingPlan;
  status: string;
  provider: string | null;
  billing_period: string | null;
  current_period_end: string | null;
  cancel_at_period_end: boolean;
  trial_end: string | null;
  next_charge_at: string | null;
  next_charge_amount: number | null;
  next_charge_currency: string | null;
  enforcement_enabled: boolean;
}

export interface BillingInvoice {
  id: string;
  amount: number | null;
  currency: string;
  status: string;
  paid_at: string | null;
  created_at: string;
  receipt_url: string | null;
  description: string | null;
  // Populated when the row comes from Stripe directly. Frontend prefers
  // `hosted_invoice_url` for the "Receipt" link and exposes the PDF where
  // available.
  hosted_invoice_url?: string | null;
  invoice_pdf?: string | null;
  period_start?: string | null;
  period_end?: string | null;
}

export interface BillingPortalSession {
  url: string;
}

export interface BillingSwitchPlanResponse {
  status: string;
  requested_period: string;
}

export interface BillingUsage {
  words_used: number;
  words_cap: number | null;
  reset_at: string;
  cap_exceeded: boolean;
}

export interface BillingCheckoutResponse {
  provider: string;
  checkout_url: string;
}

export async function listBillingPlans(): Promise<BillingPlan[]> {
  return apiFetch<BillingPlan[]>("/api/billing/plans");
}

export async function getBillingSubscription(): Promise<BillingSubscription> {
  return apiFetch<BillingSubscription>("/api/billing/subscription");
}

export async function getBillingUsage(): Promise<BillingUsage> {
  return apiFetch<BillingUsage>("/api/billing/usage");
}

export async function createBillingCheckout(input: {
  plan: string;
  period: "month" | "year";
  provider?: "stripe" | "tinkoff";
  promo_code?: string;
  // Required by the backend for the T-Bank (RU) rail: the user's explicit
  // consent to recurring auto-charges + personal-data processing.
  accepted_recurring_terms?: boolean;
}): Promise<BillingCheckoutResponse> {
  return apiFetch<BillingCheckoutResponse>("/api/billing/checkout", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function claimBillingPromoCode(code: string): Promise<BillingSubscription> {
  return apiFetch<BillingSubscription>("/api/billing/promo/claim", {
    method: "POST",
    body: JSON.stringify({ code }),
  });
}

export async function cancelBillingSubscription(): Promise<void> {
  await apiFetch<unknown>("/api/billing/cancel", { method: "POST" });
}

export async function getBillingInvoices(): Promise<BillingInvoice[]> {
  return apiFetch<BillingInvoice[]>("/api/billing/invoices");
}

export async function switchBillingPlan(
  period: "monthly" | "yearly",
): Promise<BillingSwitchPlanResponse> {
  return apiFetch<BillingSwitchPlanResponse>("/api/billing/switch-plan", {
    method: "POST",
    body: JSON.stringify({ period }),
  });
}

export async function openBillingPortal(): Promise<BillingPortalSession> {
  return apiFetch<BillingPortalSession>("/api/billing/portal", {
    method: "POST",
  });
}
