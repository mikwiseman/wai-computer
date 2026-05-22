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
  enforcement_enabled: boolean;
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
}): Promise<BillingCheckoutResponse> {
  return apiFetch<BillingCheckoutResponse>("/api/billing/checkout", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function cancelBillingSubscription(): Promise<void> {
  await apiFetch<unknown>("/api/billing/cancel", { method: "POST" });
}
