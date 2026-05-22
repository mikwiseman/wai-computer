import { ApiError, getApiBaseUrl } from "./http";

export interface AdminPromoCodeCreateInput {
  adminPassword: string;
  code: string | null;
  prefix: string;
  plan: string;
  billing_period: "month" | "year";
  duration_days: number;
  max_redemptions: number;
  expires_days: number | null;
  note: string | null;
}

export interface AdminPromoCode {
  code: string;
  normalized_code: string;
  plan: string;
  billing_period: string;
  duration_days: number;
  max_redemptions: number;
  redeemed_count: number;
  active: boolean;
  expires_at: string | null;
  note: string | null;
}

async function parsePayload(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text.trim()) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

function messageFromPayload(payload: unknown, fallback: string): string {
  if (payload && typeof payload === "object") {
    const detail = (payload as { detail?: unknown }).detail;
    if (typeof detail === "string" && detail.length > 0) {
      return detail;
    }
  }
  return fallback;
}

export async function createAdminPromoCode(
  input: AdminPromoCodeCreateInput,
): Promise<AdminPromoCode> {
  const { adminPassword, ...payload } = input;
  const response = await fetch(`${getApiBaseUrl()}/api/admin/promo-codes`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Wai-Admin-Password": adminPassword,
    },
    body: JSON.stringify(payload),
    credentials: "include",
    cache: "no-store",
  });
  const responsePayload = await parsePayload(response);
  if (!response.ok) {
    throw new ApiError(
      response.status,
      messageFromPayload(responsePayload, "Не удалось сгенерировать промокод."),
      responsePayload,
    );
  }
  return responsePayload as AdminPromoCode;
}
